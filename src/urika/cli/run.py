"""Run command and related helpers."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click

from urika.cli._base import cli
from urika.core.experiment import create_experiment, list_experiments
from urika.core.progress import load_progress

from urika.cli._helpers import (
    _make_on_message,
    _resolve_project,
    _ensure_project,
    _prompt_numbered,
)


def _update_repl_activity(event: str, detail: str) -> None:
    """Push orchestrator progress events to the REPL session's activity bar.

    Called from _on_progress callbacks so the TUI's ActivityBar shows
    the current subagent (e.g. "run — planning_agent — Thinking…").
    """
    if not os.environ.get("URIKA_REPL"):
        return
    try:
        from urika.repl_commands import _get_repl_session

        session = _get_repl_session()
        if session is None:
            return
        if event == "agent":
            # detail = "Planning agent — designing method"
            agent_key = detail.split("\u2014")[0].strip().lower().replace(" ", "_")
            session.update_agent_activity(activity=agent_key)
        elif event == "turn":
            session.update_agent_activity(turn=detail)
        elif event == "phase":
            session.update_agent_activity(activity=detail)
    except Exception:
        pass


def _print_dry_run_plan(
    *,
    project: str,
    project_path: Path,
    experiment_id: str | None,
    max_turns: int | None,
    max_experiments: int | None,
    instructions: str,
    resume: bool,
) -> None:
    """Print the planned pipeline without touching any agent or creating dirs.

    Called when ``urika run --dry-run`` is invoked. Must not import or
    instantiate AgentRunner, orchestrator, or create experiment directories.
    """
    from urika.cli_display import print_step, print_success

    click.echo()
    click.echo("  Urika dry run — no agents will be invoked.")
    click.echo()
    print_step("Project:", project)
    print_step("Path:", str(project_path))
    print_step("Experiment:", experiment_id or "(auto — will be selected at run time)")
    if max_experiments is not None:
        print_step(
            "Mode:",
            f"meta-orchestrator (up to {max_experiments} experiments)",
        )
    else:
        print_step("Mode:", "single experiment")
    if max_turns is not None:
        print_step("Max turns:", str(max_turns))
    if resume:
        print_step("Resume:", "yes")
    if instructions:
        preview = (
            instructions[:80] + "..." if len(instructions) > 80 else instructions
        )
        print_step("Instructions:", preview)
    click.echo()
    click.echo("  Pipeline stages (per experiment):")
    click.echo("    planning  →  task  →  evaluator  →  advisor")
    click.echo()
    click.echo("  Writable directories agents will touch:")
    click.echo(f"    {project_path / 'experiments'}/         (experiment records)")
    click.echo(
        f"    {project_path / 'experiments'}/<exp>/code/  (task-agent Python code)"
    )
    click.echo(f"    {project_path / 'methods'}/            (agent-authored methods)")
    click.echo(f"    {project_path / 'progress.jsonl'}       (append-only run log)")
    click.echo(f"    {project_path / 'methods.json'}         (method registry)")
    click.echo()
    click.echo(
        "  Note: the task agent writes and executes Python under"
        " experiments/<exp>/code/."
    )
    click.echo()
    print_success("Remove --dry-run to execute.")


def _determine_next_experiment(
    project_path: Path,
    project_name: str,
    *,
    auto: bool = False,
    panel: object = None,
    instructions: str = "",
) -> str | None:
    """Determine and create the next experiment based on project state.

    Reads methods.json, criteria.json, completed experiments, and the initial
    plan to decide what should run next. If the initial plan is exhausted,
    calls the suggestion agent for next steps.
    """
    import json

    from urika.cli_display import print_step, print_success
    from urika.cli_helpers import interactive_prompt

    # Gather project state
    existing_experiments = list_experiments(project_path)
    completed = [
        e
        for e in existing_experiments
        if load_progress(project_path, e.experiment_id).get("status") == "completed"
    ]

    # Load methods registry
    methods_path = project_path / "methods.json"
    methods_summary = ""
    if methods_path.exists():
        try:
            mdata = json.loads(methods_path.read_text(encoding="utf-8"))
            mlist = mdata.get("methods", [])
            if mlist:
                methods_summary = f"{len(mlist)} methods tried. Best: "

                def _best_metric_val(m: dict) -> float:
                    nums = [
                        v
                        for v in m.get("metrics", {}).values()
                        if isinstance(v, (int, float))
                    ]
                    return max(nums) if nums else 0

                best = max(
                    (m for m in mlist if m.get("metrics")),
                    key=_best_metric_val,
                    default=None,
                )
                if best:
                    methods_summary += f"{best['name']} ({best.get('metrics', {})})"
        except (json.JSONDecodeError, KeyError):
            pass

    # Load criteria
    criteria_summary = ""
    criteria_path = project_path / "criteria.json"
    if criteria_path.exists():
        try:
            cdata = json.loads(criteria_path.read_text(encoding="utf-8"))
            versions = cdata.get("versions", [])
            if versions:
                latest = versions[-1]
                ctype = latest.get("criteria", {}).get("type", "unknown")
                criteria_summary = f"Criteria: {ctype} (v{latest['version']})"
        except (json.JSONDecodeError, KeyError):
            pass

    # If user provided instructions, always call advisor agent to think
    # Otherwise fall back to initial plan
    next_suggestion = None
    call_advisor_agent = bool(instructions) or bool(completed)

    # Check for pending suggestions from remote advisor (Telegram/Slack)
    pending_path = project_path / "suggestions" / "pending.json"
    if pending_path.exists():
        try:
            data = json.loads(pending_path.read_text(encoding="utf-8"))
            suggestions = data.get("suggestions", [])
            if suggestions:
                next_suggestion = suggestions[0]
                # Consume the pending file
                pending_path.unlink(missing_ok=True)
                if not auto:
                    print_step("Using suggestion from recent advisor conversation")
        except (json.JSONDecodeError, KeyError):
            pass

    if not call_advisor_agent and next_suggestion is None:
        # First experiment, no instructions — use initial plan
        suggestions_path = project_path / "suggestions" / "initial.json"
        if suggestions_path.exists():
            try:
                data = json.loads(suggestions_path.read_text(encoding="utf-8"))
                suggestions = data.get("suggestions", [])
                if suggestions:
                    next_suggestion = suggestions[0]
            except (json.JSONDecodeError, KeyError):
                pass

    # Call suggestion agent to think about next steps
    if next_suggestion is None:
        try:
            import asyncio

            from urika.agents.runner import get_runner
            from urika.agents.registry import AgentRegistry

            runner = get_runner()
            registry = AgentRegistry()
            registry.discover()
            suggest_role = registry.get("advisor_agent")

            if suggest_role is not None:
                context = (
                    f"Project: {project_name}\n"
                    f"Completed experiments: {len(completed)}\n"
                    f"{methods_summary}\n{criteria_summary}\n"
                )
                if instructions:
                    context += f"\nUser instructions: {instructions}\n"
                context += "\nPropose the next experiment."

                config = suggest_role.build_config(
                    project_dir=project_path, experiment_id=""
                )

                from urika.cli_display import (
                    format_agent_output,
                    print_agent,
                    print_tool_use,
                )

                print_agent("advisor_agent")
                if panel is not None:
                    panel.update(agent="advisor_agent", activity="Analyzing…")

                def _on_msg(msg: object) -> None:
                    """Show tool use from suggestion agent."""
                    try:
                        model = getattr(msg, "model", None)
                        if model and panel is not None:
                            panel.set_model(model)
                        if hasattr(msg, "content"):
                            for block in msg.content:
                                tool_name = getattr(block, "name", None)
                                if tool_name:
                                    inp = getattr(block, "input", {}) or {}
                                    detail = ""
                                    if isinstance(inp, dict):
                                        detail = (
                                            inp.get("command", "")
                                            or inp.get("file_path", "")
                                            or inp.get("pattern", "")
                                        )
                                    print_tool_use(tool_name, detail)
                                    if panel is not None:
                                        panel.set_thinking(tool_name)
                                else:
                                    if panel is not None:
                                        panel.set_thinking("Thinking…")
                    except Exception:
                        pass

                result = asyncio.run(runner.run(config, context, on_message=_on_msg))

                if result.success:
                    from urika.orchestrator.parsing import parse_suggestions

                    parsed = parse_suggestions(result.text_output)
                    if parsed and parsed.get("suggestions"):
                        next_suggestion = parsed["suggestions"][0]
                        click.echo(format_agent_output(result.text_output))
        except Exception:
            pass

    if next_suggestion is None:
        return None

    exp_name = next_suggestion.get("name", "auto-experiment").replace(" ", "-").lower()
    description = next_suggestion.get("method", next_suggestion.get("description", ""))
    if instructions:
        description = f"{instructions}\n\n{description}"

    # Show plan and confirm (unless --auto)
    print_step(f"Next experiment: {exp_name}")
    if description:
        short = description[:200] + "..." if len(description) > 200 else description
        click.echo(f"    {short}")
    if methods_summary:
        click.echo(f"    {methods_summary}")
    if criteria_summary:
        click.echo(f"    {criteria_summary}")

    if not auto:
        choice = _prompt_numbered(
            "\n  Proceed?",
            [
                "Yes — create and run it",
                "Different instructions",
                "Skip — exit",
            ],
            default=1,
        )

        if choice.startswith("Skip"):
            return None

        if choice.startswith("Different"):
            instructions = interactive_prompt("Your instructions")
            if instructions:
                description = f"{instructions}\n\n{description}"

    exp = create_experiment(
        project_path,
        name=exp_name,
        hypothesis=description[:500] if description else "",
    )
    print_success(f"Created experiment: {exp.experiment_id}")
    return exp.experiment_id


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--experiment", "experiment_id", default=None, help="Experiment ID to run."
)
@click.option("--max-turns", default=None, type=int, help="Maximum orchestrator turns.")
@click.option(
    "--resume",
    is_flag=True,
    default=False,
    help="Resume a paused or failed experiment.",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress verbose tool-use streaming output.",
)
@click.option(
    "--auto",
    is_flag=True,
    default=False,
    help="Fully autonomous — no confirmation prompts.",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    default=False,
    help="Print the planned pipeline (agents, tools, writable dirs) without executing.",
)
@click.option(
    "--instructions",
    default="",
    help="Guide the next experiment (e.g. 'focus on FOV-constrained models').",
)
@click.option(
    "--max-experiments",
    default=None,
    type=int,
    help="Run multiple experiments via meta-orchestrator (capped mode).",
)
@click.option(
    "--review-criteria",
    is_flag=True,
    default=False,
    help="Ask advisor to review criteria when met (may raise the bar).",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option(
    "--audience",
    type=click.Choice(["novice", "standard", "expert"]),
    default=None,
    help="Output audience level (default: standard).",
)
@click.option(
    "--legacy",
    is_flag=True,
    default=False,
    help="Use the deterministic Python orchestrator (default behavior for now).",
)
def run(
    project: str,
    experiment_id: str | None,
    max_turns: int | None,
    resume: bool,
    quiet: bool,
    auto: bool,
    dry_run: bool,
    instructions: str,
    max_experiments: int | None,
    review_criteria: bool,
    json_output: bool = False,
    audience: str | None = None,
    legacy: bool = False,
) -> None:
    """Run an experiment using the orchestrator."""
    # TODO: When --legacy is False and TUI binary is available,
    # launch TS orchestrator in headless mode instead.
    # For now, both paths use the Python orchestrator.
    try:
        from urika.agents.runner import get_runner
    except ImportError:
        raise click.ClickException(
            "Claude Agent SDK not installed. Run: pip install claude-agent-sdk"
        )
    import signal
    import threading
    import time

    _is_main_thread = threading.current_thread() is threading.main_thread()

    from urika.cli_display import (
        ThinkingPanel,
        print_agent,
        print_error,
        print_footer,
        print_header,
        print_step,
        print_success,
        print_tool_use,
        print_warning,
    )
    from urika.orchestrator import run_experiment, run_project

    from urika.cli_display import thinking_phrase
    from urika.cli_helpers import interactive_prompt

    # Pick up queued-input callback when invoked from the REPL
    _get_user_input = None
    if os.environ.get("URIKA_REPL"):
        try:
            from urika.repl_commands import _user_input_callback

            _get_user_input = _user_input_callback
        except ImportError:
            pass

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    # Dry-run: print planned pipeline and exit WITHOUT any agent setup.
    if dry_run:
        _print_dry_run_plan(
            project=project,
            project_path=project_path,
            experiment_id=experiment_id,
            max_turns=max_turns,
            max_experiments=max_experiments,
            instructions=instructions,
            resume=resume,
        )
        return

    # Resolve audience from project config if not explicitly provided
    if audience is None:
        audience = _config.audience

    # If --max-turns was not explicitly provided, read from urika.toml
    if max_turns is None:
        import tomllib

        toml_path = project_path / "urika.toml"
        if toml_path.exists():
            try:
                with open(toml_path, "rb") as f:
                    data = tomllib.load(f)
                max_turns = data.get("preferences", {}).get(
                    "max_turns_per_experiment", 5
                )
            except Exception:
                max_turns = 5
        else:
            max_turns = 5

    # If no flags provided and not from REPL, show settings dialog
    if (
        not json_output
        and not os.environ.get("URIKA_REPL")
        and experiment_id is None
        and max_experiments is None
        and not auto
        and not resume
        and not instructions
    ):
        click.echo(f"\n  Run settings for {project}:")
        click.echo(f"    Max turns: {max_turns}")

        choice = _prompt_numbered(
            "\n  Proceed?",
            [
                "Run with defaults",
                "Run multiple experiments (meta-orchestrator)",
                "Custom max turns",
                "Skip",
            ],
            default=1,
        )

        if choice.startswith("Skip"):
            return
        elif choice.startswith("Run multiple"):
            try:
                max_experiments = int(
                    interactive_prompt("How many experiments?", default="3")
                )
            except ValueError:
                max_experiments = 3
            auto = True
        elif choice.startswith("Custom"):
            try:
                max_turns = int(
                    interactive_prompt("Max turns per experiment", default=str(max_turns))
                )
            except ValueError:
                pass  # keep existing max_turns

        # Show settings summary before starting
        click.echo()
        click.echo("  Starting with:")
        click.echo(f"    Max turns:    {max_turns}")
        if max_experiments:
            click.echo(f"    Experiments:  up to {max_experiments} (autonomous)")
        else:
            click.echo("    Mode:         single experiment")
        if instructions:
            instr_preview = (
                instructions[:80] + "..."
                if len(instructions) > 80
                else instructions
            )
            click.echo(f"    Instructions: {instr_preview}")
        click.echo()

    # Show header (skip if called from REPL — already has header)
    if not json_output and not os.environ.get("URIKA_REPL"):
        print_header(
            project_name=project,
            agent="orchestrator",
            mode=_config.mode,
        )

    # Create panel early so it's available during experiment selection.
    if json_output:
        panel = None
    else:
        from urika.agents.config import load_runtime_config as _load_rc

        _rc = _load_rc(project_path)
        panel = ThinkingPanel()
        panel.project = f"{project} \u00b7 {_rc.privacy_mode}"
        panel._project_dir = project_path
        panel.activity = "Determining next experiment\u2026"
        panel.activate()
        panel.start_spinner()

    # --- Meta-orchestrator path: --max-experiments delegates to run_project ---
    if max_experiments is not None:
        if not json_output:
            print_step(
                f"Meta-orchestrator: up to {max_experiments} experiments"
                f" (max {max_turns} turns each)"
            )

        # Determine mode: capped auto unless auto flag gives unlimited
        meta_mode = "unlimited" if auto else "capped"

        # Create pause controller and key listener for ESC-to-pause
        from urika.orchestrator.pause import KeyListener, PauseController

        pause_ctrl = PauseController()

        # Start notification bus — reuse REPL's persistent bus if available
        notif_bus = None
        _owns_bus_meta = False
        if os.environ.get("URIKA_REPL"):
            try:
                from urika.repl_commands import _get_repl_bus

                notif_bus = _get_repl_bus()
            except Exception:
                pass

        if notif_bus is None and not os.environ.get("URIKA_REMOTE_RUN"):
            from urika.notifications import build_bus

            notif_bus = build_bus(project_path)
            if notif_bus is not None:
                notif_bus.start(controller=pause_ctrl)
            _owns_bus_meta = True
        elif notif_bus is not None:
            # Update the persistent bus with this run's controller
            notif_bus._controller = pause_ctrl

        key_listener: KeyListener | None = None
        if not json_output:

            def _on_pause_esc_meta() -> None:
                if panel is not None:
                    panel.update(pause_requested=True)
                print_warning(
                    "\n\u23f8 Pause requested \u2014 will pause after current turn"
                    " completes..."
                )

            key_listener = KeyListener(
                pause_ctrl, on_pause_requested=_on_pause_esc_meta
            )
            key_listener.start()

        original_handler = signal.getsignal(signal.SIGINT) if _is_main_thread else None

        def _cleanup_meta(signum: int, frame: object) -> None:
            if key_listener is not None:
                key_listener.stop()
            print_warning("\n  Autonomous run stopped")
            print_step("  Options:")
            print_step(
                "    urika run --resume              Resume from where you left off"
            )
            print_step("    urika advisor <project> <text>   Chat with advisor first")
            print_step("    urika run --instructions '...'   Run with new instructions")
            raise SystemExit(1)

        if _is_main_thread:
            signal.signal(signal.SIGINT, _cleanup_meta)

        from datetime import datetime, timezone

        start_ms = int(time.monotonic() * 1000)
        start_iso = datetime.now(timezone.utc).isoformat()
        sdk_runner = get_runner()

        try:
            if json_output:

                def _on_progress(event: str, detail: str = "") -> None:
                    _update_repl_activity(event, detail)
                    if notif_bus is not None:
                        notif_bus.on_progress(event, detail)

                def _on_message(msg: object) -> None:
                    pass

            else:

                def _on_progress(event: str, detail: str = "") -> None:
                    _update_repl_activity(event, detail)
                    if event == "turn":
                        print_step(detail)
                        panel.update(turn=detail, activity=thinking_phrase())
                    elif event == "agent":
                        agent_key = (
                            detail.split("\u2014")[0].strip().lower().replace(" ", "_")
                        )
                        print_agent(agent_key)
                        panel.update(agent=agent_key, activity=detail)
                    elif event == "result":
                        print_success(detail)
                    elif event == "phase":
                        print_step(detail)
                        panel.update(activity=detail)
                    # Show pause in footer if requested (from any source)
                    if pause_ctrl.is_pause_requested():
                        panel.update(pause_requested=True)
                    # Dispatch to notification bus
                    if notif_bus is not None:
                        notif_bus.on_progress(event, detail)

                def _on_message(msg: object) -> None:
                    model = getattr(msg, "model", None)
                    if model:
                        panel.set_model(model)
                    content = getattr(msg, "content", None)
                    if content is None:
                        return
                    for block in content:
                        tool_name = getattr(block, "name", None) or getattr(
                            block, "tool_name", None
                        )
                        if tool_name:
                            detail = ""
                            input_data = getattr(block, "input", None) or getattr(
                                block, "tool_input", {}
                            )
                            if isinstance(input_data, dict):
                                if "command" in input_data:
                                    detail = input_data["command"]
                                elif "file_path" in input_data:
                                    detail = input_data["file_path"]
                                elif "pattern" in input_data:
                                    detail = input_data["pattern"]
                            if not quiet:
                                print_tool_use(tool_name, detail)
                            panel.set_thinking(tool_name)
                        else:
                            panel.set_thinking("Thinking\u2026")

            result = asyncio.run(
                run_project(
                    project_path,
                    sdk_runner,
                    mode=meta_mode,
                    max_experiments=max_experiments,
                    max_turns=max_turns,
                    instructions=instructions,
                    review_criteria=review_criteria,
                    on_progress=_on_progress,
                    on_message=_on_message,
                    get_user_input=_get_user_input,
                    pause_controller=pause_ctrl,
                    audience=audience,
                )
            )

        finally:
            if _owns_bus_meta and notif_bus is not None:
                notif_bus.stop()
            elif not _owns_bus_meta and notif_bus is not None:
                notif_bus._controller = None
            if key_listener is not None:
                key_listener.stop()
            if panel is not None:
                panel.cleanup()
            if _is_main_thread and original_handler is not None:
                signal.signal(signal.SIGINT, original_handler)

        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        n_exp = result.get("experiments_run", 0)

        # Send completion notification
        if notif_bus is not None:
            from urika.notifications.events import NotificationEvent

            auto_state = result.get("autonomous_state")
            if auto_state:
                notif_bus.notify(
                    NotificationEvent(
                        event_type="meta_paused",
                        project_name=project,
                        summary=(
                            f"Autonomous run paused after"
                            f" {auto_state.get('experiments_completed', 0)}"
                            " experiment(s)"
                        ),
                        priority="medium",
                    )
                )
            else:
                notif_bus.notify(
                    NotificationEvent(
                        event_type="meta_completed",
                        project_name=project,
                        summary=f"Meta-orchestrator completed: {n_exp} experiment(s)",
                        priority="high",
                    )
                )

        # Aggregate usage from all experiment results
        _meta_tokens_in = 0
        _meta_tokens_out = 0
        _meta_cost_usd = 0.0
        _meta_agent_calls = 0
        for exp_result in result.get("results", []):
            _meta_tokens_in += exp_result.get("tokens_in", 0)
            _meta_tokens_out += exp_result.get("tokens_out", 0)
            _meta_cost_usd += exp_result.get("cost_usd", 0.0)
            _meta_agent_calls += exp_result.get("agent_calls", 0)

        # Record usage for this CLI session
        try:
            from urika.core.usage import record_session

            record_session(
                project_path,
                started=start_iso,
                ended=datetime.now(timezone.utc).isoformat(),
                duration_ms=elapsed_ms,
                tokens_in=_meta_tokens_in,
                tokens_out=_meta_tokens_out,
                cost_usd=_meta_cost_usd,
                agent_calls=_meta_agent_calls,
                experiments_run=n_exp,
            )
        except Exception:
            pass

        if json_output:
            from urika.cli_helpers import output_json

            result["duration_ms"] = elapsed_ms
            output_json(result)
            return

        # Check if paused (autonomous_state present means mid-run pause)
        auto_state = result.get("autonomous_state")
        if auto_state:
            n_done = auto_state.get("experiments_completed", 0)
            print_step(f"\u23f8 Autonomous run paused after {n_done} experiment(s)")
            print_step("  Options:")
            print_step("    urika run --resume              Continue autonomous run")
            print_step("    urika advisor <project> <text>   Chat with advisor first")
            print_step("    urika run --instructions '...'   Resume with new guidance")
            print_footer(duration_ms=elapsed_ms, turns=n_done, status="paused")
            return

        print_success(f"Meta-orchestrator completed: {n_exp} experiment(s) run.")
        print_footer(duration_ms=elapsed_ms, turns=n_exp, status="completed")
        return

    # --- Single experiment path ---
    if experiment_id is None:
        experiments = list_experiments(project_path)
        # Find pending (non-completed, non-failed, non-stopped) experiments
        pending = [
            e
            for e in experiments
            if load_progress(project_path, e.experiment_id).get("status")
            not in ("completed", "failed", "stopped")
        ]
        if pending:
            if resume and len(pending) > 1 and not json_output:
                # Multiple resumable — let the user pick
                from urika.cli_helpers import interactive_numbered

                options = []
                for e in pending:
                    p = load_progress(project_path, e.experiment_id)
                    status = p.get("status", "pending")
                    options.append(f"{e.experiment_id} [{status}]")
                choice = interactive_numbered(
                    "\n  Multiple experiments can be resumed:", options
                )
                experiment_id = choice.split(" [")[0]
            else:
                experiment_id = pending[-1].experiment_id
            if not json_output:
                print_step(
                    f"Resuming pending experiment: {experiment_id}",
                    f"({len(pending)} pending)" if len(pending) > 1 else "",
                )
        else:
            # No pending — determine next experiment from state
            experiment_id = _determine_next_experiment(
                project_path,
                project,
                auto=auto or json_output,
                instructions=instructions,
                panel=panel,
            )
            if experiment_id is not None:
                if not json_output:
                    print_step(
                        f"Created new experiment: {experiment_id}",
                        "based on advisor suggestions",
                    )
            elif experiment_id is None:
                if not experiments:
                    raise click.ClickException(
                        "No experiments and no plan found. Create one with:\n"
                        f"  urika experiment create {project} <experiment-name>"
                    )
                experiment_id = experiments[-1].experiment_id
                if not json_output:
                    print_step(f"All experiments completed. Re-running {experiment_id}")

    if not json_output:
        if resume:
            print_step(f"Resuming experiment {experiment_id}")
        else:
            print_step(f"Running experiment {experiment_id} (max {max_turns} turns)")

    # Set experiment ID on panel
    if panel is not None:
        panel.update(experiment_id=experiment_id)

    # Create pause controller and key listener for ESC-to-pause
    from urika.orchestrator.pause import KeyListener, PauseController

    pause_ctrl = PauseController()

    # Start notification bus if configured — reuse REPL's persistent bus if available
    notif_bus = None
    _owns_bus = False
    if os.environ.get("URIKA_REPL"):
        try:
            from urika.repl_commands import _get_repl_bus

            notif_bus = _get_repl_bus()
        except Exception:
            pass

    if notif_bus is None and not os.environ.get("URIKA_REMOTE_RUN"):
        from urika.notifications import build_bus as _build_bus

        notif_bus = _build_bus(project_path)
        if notif_bus is not None:
            notif_bus.start(controller=pause_ctrl)
        _owns_bus = True
    elif notif_bus is not None:
        # Update the persistent bus with this run's controller
        notif_bus._controller = pause_ctrl

    if notif_bus is not None:
        notif_bus.set_experiment(experiment_id)

    key_listener: KeyListener | None = None
    if not json_output:

        def _on_pause_esc() -> None:
            if panel is not None:
                panel.update(pause_requested=True)
            print_warning(
                "\n\u23f8 Pause requested \u2014 will pause after current turn completes..."
            )

        key_listener = KeyListener(pause_ctrl, on_pause_requested=_on_pause_esc)
        key_listener.start()

    # Register Ctrl+C handler to clean up lockfile
    def _cleanup_on_interrupt(signum: int, frame: object) -> None:
        if key_listener is not None:
            key_listener.stop()
        print_warning(f"\n  Experiment run stopped ({experiment_id})")
        try:
            from urika.core.session import stop_session

            stop_session(project_path, experiment_id, reason="Stopped by user")
        except Exception:
            # Force remove lockfile if stop_session fails
            lock = project_path / "experiments" / experiment_id / ".lock"
            lock.unlink(missing_ok=True)
        print_step("  Options:")
        print_step("    urika run --resume              Resume from next turn")
        print_step("    urika advisor <project> <text>   Chat with advisor first")
        print_step("    urika run --instructions '...'   Run with new instructions")
        raise SystemExit(1)

    original_handler = signal.getsignal(signal.SIGINT) if _is_main_thread else None
    if _is_main_thread:
        signal.signal(signal.SIGINT, _cleanup_on_interrupt)

    from datetime import datetime, timezone

    start_ms = int(time.monotonic() * 1000)
    start_iso = datetime.now(timezone.utc).isoformat()

    sdk_runner = get_runner()

    # Panel already created and active from experiment selection above
    try:
        if json_output:

            def _on_progress(event: str, detail: str = "") -> None:
                _update_repl_activity(event, detail)
                if notif_bus is not None:
                    notif_bus.on_progress(event, detail)

            def _on_message(msg: object) -> None:
                pass

        else:

            def _on_progress(event: str, detail: str = "") -> None:
                _update_repl_activity(event, detail)
                if event == "turn":
                    print_step(detail)
                    panel.update(turn=detail, activity=thinking_phrase())
                elif event == "agent":
                    # Extract agent key from "Planning agent — designing method"
                    agent_key = (
                        detail.split("\u2014")[0].strip().lower().replace(" ", "_")
                    )
                    print_agent(agent_key)
                    panel.update(agent=agent_key, activity=detail)
                elif event == "result":
                    print_success(detail)
                elif event == "phase":
                    print_step(detail)
                    panel.update(activity=detail)
                # Show pause in footer if requested (from any source)
                if pause_ctrl.is_pause_requested():
                    panel.update(pause_requested=True)
                # Dispatch to notification bus
                if notif_bus is not None:
                    notif_bus.on_progress(event, detail)

            def _on_message(msg: object) -> None:
                """Handle streaming SDK messages for verbose output."""
                # Capture model name from AssistantMessage
                model = getattr(msg, "model", None)
                if model:
                    panel.set_model(model)

                # Use getattr for safe access — SDK types may vary
                content = getattr(msg, "content", None)
                if content is None:
                    return
                for block in content:
                    tool_name = getattr(block, "name", None) or getattr(
                        block, "tool_name", None
                    )
                    if tool_name:
                        detail = ""
                        input_data = getattr(block, "input", None) or getattr(
                            block, "tool_input", {}
                        )
                        if isinstance(input_data, dict):
                            if "command" in input_data:
                                detail = input_data["command"]
                            elif "file_path" in input_data:
                                detail = input_data["file_path"]
                            elif "pattern" in input_data:
                                detail = input_data["pattern"]
                        if not quiet:
                            print_tool_use(tool_name, detail)
                        panel.set_thinking(tool_name)
                    else:
                        # Text block — agent is thinking
                        panel.set_thinking("Thinking\u2026")

        result = asyncio.run(
            run_experiment(
                project_path,
                experiment_id,
                sdk_runner,
                max_turns=max_turns,
                resume=resume,
                review_criteria=review_criteria,
                on_progress=_on_progress,
                on_message=_on_message,
                instructions=instructions,
                get_user_input=_get_user_input,
                pause_controller=pause_ctrl,
                audience=audience,
            )
        )

    finally:
        if _owns_bus and notif_bus is not None:
            notif_bus.stop()
        elif not _owns_bus and notif_bus is not None:
            notif_bus._controller = None
        if key_listener is not None:
            key_listener.stop()
        if panel is not None:
            panel.cleanup()
        # Restore original handler
        if _is_main_thread and original_handler is not None:
            signal.signal(signal.SIGINT, original_handler)

    elapsed_ms = int(time.monotonic() * 1000) - start_ms
    run_status = result.get("status", "unknown")
    turns = result.get("turns", 0)
    error = result.get("error")

    # Send completion/failure notification with outcome summary
    if notif_bus is not None:
        from urika.notifications.events import NotificationEvent as _NE

        summary_text = ""
        if run_status in ("completed", "paused", "stopped"):
            # Build outcome summary from progress
            try:
                exp_progress = load_progress(project_path, experiment_id)
                runs = exp_progress.get("runs", [])
                if runs:
                    methods = list({r["method"] for r in runs})
                    summary_text = f"{len(runs)} runs, {len(methods)} methods. "
                    # Find best metric, respecting direction
                    from urika.core.labbook import _LOWER_IS_BETTER as _LIB

                    best_val = None
                    best_method = None
                    best_metric = None
                    lower_better = False
                    for r in runs:
                        for k, v in r.get("metrics", {}).items():
                            if isinstance(v, (int, float)):
                                if best_metric is None:
                                    best_metric = k
                                    lower_better = k in _LIB
                                if k == best_metric:
                                    if best_val is None:
                                        best_val = v
                                        best_method = r["method"]
                                    elif lower_better and v < best_val:
                                        best_val = v
                                        best_method = r["method"]
                                    elif not lower_better and v > best_val:
                                        best_val = v
                                        best_method = r["method"]
                    if best_val is not None:
                        if 0 <= best_val <= 1:
                            summary_text += f"Best: {best_method} ({best_metric}={best_val:.1%})"
                        else:
                            summary_text += f"Best: {best_method} ({best_metric}={best_val:.4g})"
            except Exception:
                pass

        if run_status == "completed":
            notif_bus.notify(
                _NE(
                    event_type="experiment_completed",
                    project_name=project,
                    experiment_id=experiment_id,
                    summary=f"Experiment completed ({turns} turns). {summary_text}".strip(),
                    priority="high",
                )
            )
        elif run_status == "failed":
            notif_bus.notify(
                _NE(
                    event_type="experiment_failed",
                    project_name=project,
                    experiment_id=experiment_id,
                    summary=f"Experiment failed: {error}",
                    priority="high",
                )
            )
        elif run_status == "paused":
            notif_bus.notify(
                _NE(
                    event_type="experiment_paused",
                    project_name=project,
                    experiment_id=experiment_id,
                    summary=f"Experiment paused ({turns} turns). {summary_text}".strip(),
                    priority="medium",
                )
            )
        elif run_status == "stopped":
            notif_bus.notify(
                _NE(
                    event_type="experiment_stopped",
                    project_name=project,
                    experiment_id=experiment_id,
                    summary=f"Experiment stopped ({turns} turns). {summary_text}".strip(),
                    priority="medium",
                )
            )

    # Record usage for this CLI session
    try:
        from urika.core.usage import record_session

        record_session(
            project_path,
            started=start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=elapsed_ms,
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
            cost_usd=result.get("cost_usd", 0.0),
            agent_calls=result.get("agent_calls", 0),
            experiments_run=1,
        )
    except Exception:
        pass

    if json_output:
        from urika.cli_helpers import output_json

        result["duration_ms"] = elapsed_ms
        output_json(result)
        return

    if run_status == "paused":
        print_step(f"\u23f8 Paused after turn {turns}/{max_turns} ({experiment_id})")
        print_step("  Options:")
        print_step("    urika run --resume              Pick up at next turn")
        print_step("    urika advisor <project> <text>   Chat with advisor first")
        print_step("    urika run --instructions '...'   Resume with new guidance")
    elif run_status == "stopped":
        print_warning(f"  Experiment stopped after turn {turns} ({experiment_id})")
        print_step("  Options:")
        print_step("    urika run --resume              Resume from next turn")
        print_step("    urika advisor <project> <text>   Chat with advisor first")
        print_step("    urika run --instructions '...'   Run with new instructions")
    elif run_status == "completed":
        print_success(f"Experiment completed after {turns} turns.")
    elif run_status == "failed":
        print_error(f"Experiment failed after {turns} turns: {error}")
    else:
        print_step(f"Experiment finished with status: {run_status} ({turns} turns)")

    print_footer(duration_ms=elapsed_ms, turns=turns, status=run_status)



def _offer_to_run_advisor_suggestions(
    advisor_output: str, project_name: str, project_path: Path
) -> None:
    """Parse advisor suggestions and offer to run them via the CLI."""
    from urika.orchestrator.parsing import parse_suggestions

    parsed = parse_suggestions(advisor_output)
    if not parsed or not parsed.get("suggestions"):
        return

    suggestions = parsed["suggestions"]

    from urika.cli_display import _C

    click.echo(
        f"  {_C.BOLD}The advisor suggested {len(suggestions)} experiment(s):{_C.RESET}"
    )
    for i, s in enumerate(suggestions, 1):
        name = s.get("name", f"experiment-{i}")
        click.echo(f"    {i}. {name}")
    click.echo()

    try:
        choice = _prompt_numbered(
            "  Run these experiments?",
            [
                "Yes \u2014 start running now",
                "No \u2014 I'll run later with urika run",
            ],
            default=1,
        )
    except (click.Abort, click.exceptions.Abort):
        return

    if not choice.startswith("Yes"):
        return

    # Create experiment from first suggestion and run it
    suggestion = suggestions[0]
    exp_name = suggestion.get("name", "advisor-experiment").replace(" ", "-").lower()
    description = suggestion.get("method", suggestion.get("description", ""))

    from urika.core.experiment import create_experiment
    from urika.cli_display import print_success

    exp = create_experiment(
        project_path,
        name=exp_name,
        hypothesis=description[:500] if description else "",
    )
    print_success(f"Created experiment: {exp.experiment_id}")

    ctx = click.Context(run)
    ctx.invoke(
        run,
        project=project_name,
        experiment_id=exp.experiment_id,
        max_turns=None,
        resume=False,
        quiet=False,
        auto=False,
        dry_run=False,
        instructions=description,
        max_experiments=None,
        review_criteria=False,
        json_output=False,
    )

