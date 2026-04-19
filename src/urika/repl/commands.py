"""Slash command handlers for the REPL."""

from __future__ import annotations
import asyncio
from pathlib import Path
import click
from urika.cli_display import _C
from urika.repl.session import ReplSession

# ── Imported helpers (re-exported for backward compat) ──
from urika.repl.helpers import (  # noqa: F401
    _pick_experiment,
    _run_single_agent,
    _save_presentation,
    _get_audience,
    _file_link,
    _fmt_tokens,
    _prompt_numbered,
    _load_run_defaults,
    get_global_stats,
    get_all_commands,
    get_command_names,
    get_project_names,
    get_experiment_ids,
)

# ── Imported agent command functions ──
from urika.repl.cmd_agents import (  # noqa: F401
    cmd_advisor,
    cmd_evaluate,
    cmd_plan,
    cmd_report,
    cmd_present,
    cmd_finalize,
    cmd_build_tool,
)


# Registry of commands
GLOBAL_COMMANDS = {}
PROJECT_COMMANDS = {}

# Module-level callback for passing queued user input into the orchestrator.
# Set before invoking the CLI run command from the REPL, cleared after.
_user_input_callback = None

# Module-level ref to the REPL session so cli.py can access the persistent bus.
_repl_session_ref: ReplSession | None = None


def _get_repl_bus():
    """Return the REPL session's notification bus, or None."""
    if _repl_session_ref is not None:
        return _repl_session_ref.notification_bus
    return None


def command(name: str, requires_project: bool = False, description: str = ""):
    """Decorator to register a REPL command."""

    def decorator(func):
        entry = {"func": func, "description": description}
        if requires_project:
            PROJECT_COMMANDS[name] = entry
        else:
            GLOBAL_COMMANDS[name] = entry
        return func

    return decorator


# ── Global commands ─────────────────────────────────────────


@command("help", description="Show available commands")
def cmd_help(session: ReplSession, args: str) -> None:

    click.echo(f"\n  {_C.BOLD}Commands:{_C.RESET}")
    for name, entry in sorted(GLOBAL_COMMANDS.items()):
        click.echo(f"    /{name:<16s} {entry['description']}")
    if session.has_project:
        for name, entry in sorted(PROJECT_COMMANDS.items()):
            click.echo(f"    /{name:<16s} {entry['description']}")
    click.echo()


@command("list", description="List all projects")
def cmd_list(session: ReplSession, args: str) -> None:
    from urika.core.registry import ProjectRegistry

    registry = ProjectRegistry()
    projects = registry.list_all()
    if not projects:
        click.echo("  No projects registered.")
        return
    click.echo()
    for name, path in projects.items():
        marker = " \u25c6" if session.project_name == name else "  "
        click.echo(f"  {marker} {name}")
    click.echo()


@command("project", description="Load a project")
def cmd_project(session: ReplSession, args: str) -> None:
    from urika.core.registry import ProjectRegistry
    from urika.core.workspace import load_project_config
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress
    from urika.cli_display import print_success

    name = args.strip()
    if not name:
        click.echo("  Usage: /project <name>")
        return

    registry = ProjectRegistry()
    path = registry.get(name)
    if path is None:
        click.echo(f"  Project '{name}' not found.")
        return

    if session.has_project:
        session.save_usage()

    # Stop old notification bus if switching projects
    if session.notification_bus is not None:
        try:
            session.notification_bus.stop()
        except Exception:
            pass
        session.notification_bus = None

    try:
        config = load_project_config(path)
    except FileNotFoundError:
        click.echo(f"  Project directory missing: {path}")
        return

    session.load_project(path, name)

    # Sync chat orchestrator to new project (if active)
    from urika.repl.main import _orchestrator

    if _orchestrator is not None:
        _orchestrator.set_project(path)

    # Start notification bus for this project
    try:
        from urika.notifications import build_bus

        bus = build_bus(path)
        if bus is not None:
            bus.start(session=session)
            session.notification_bus = bus
    except Exception:
        pass  # Notifications are best-effort

    experiments = list_experiments(path)
    completed = sum(
        1
        for e in experiments
        if load_progress(path, e.experiment_id).get("status") == "completed"
    )

    # Show privacy mode and notifications
    import tomllib

    toml_path = path / "urika.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                tdata = tomllib.load(f)
            privacy = tdata.get("privacy", {}).get("mode", "open")
            notif_channels = tdata.get("notifications", {}).get("channels", [])
            notif_str = ", ".join(notif_channels) if notif_channels else "off"
        except Exception:
            privacy = "open"
            notif_str = "off"
    else:
        privacy = "open"
        notif_str = "off"

    click.echo()
    print_success(f"Project: {name} \u00b7 {config.mode}")
    click.echo(f"    {len(experiments)} experiments \u00b7 {completed} completed")
    click.echo(f"    Privacy: {privacy} \u00b7 Notifications: {notif_str}")

    # Check private endpoint reachability for hybrid/private mode
    from urika.core.privacy import check_private_endpoint, requires_private_endpoint

    if requires_private_endpoint(session.project_path):
        reachable, msg = check_private_endpoint(session.project_path)
        if reachable:
            click.echo(f"    Local model: {msg}")
            session._private_endpoint_ok = True
        else:
            click.echo(f"    \u2717 {msg}")
            click.echo(
                "    Agent commands disabled. Start your local model or switch to open: /config"
            )
            session._private_endpoint_ok = False
    else:
        session._private_endpoint_ok = True  # open mode, no restriction

    # After project is loaded, check for recent sessions
    try:
        from urika.core.orchestrator_sessions import get_most_recent

        recent = get_most_recent(session.project_path)
        if recent:
            from datetime import datetime

            updated = datetime.fromisoformat(recent.updated).strftime("%Y-%m-%d %H:%M")
            click.echo(
                f"  Previous session from {updated} available. Type /resume-session to reload."
            )
    except Exception:
        pass

    click.echo()


@command("new", description="Create a new project")
def cmd_new(session: ReplSession, args: str) -> None:
    import os as _os

    from urika.cli import _sanitize_project_name, new as cli_new
    from urika.core.registry import ProjectRegistry

    name = args.strip() if args.strip() else None
    if name is not None:
        name = _sanitize_project_name(name)

    # Snapshot existing projects so we can detect a new one
    registry = ProjectRegistry()
    before = set(registry.list_all().keys())

    _os.environ["URIKA_REPL"] = "1"
    ctx = click.Context(cli_new)
    try:
        ctx.invoke(
            cli_new,
            name=name,
            question=None,
            mode=None,
            data_path=None,
            description=None,
        )
    except SystemExit:
        pass
    finally:
        _os.environ.pop("URIKA_REPL", None)

    # Auto-load the newly created project (only if one was actually created)
    registry = ProjectRegistry()
    after = registry.list_all()
    new_projects = set(after.keys()) - before
    if new_projects:
        new_name = new_projects.pop()
        session.load_project(after[new_name], new_name)
        click.echo(f"  Loaded project: {new_name}")


@command("quit", description="Exit Urika")
def cmd_quit(session: ReplSession, args: str) -> None:
    session.save_usage()
    raise SystemExit(0)


@command("config", description="Configure privacy mode and models")
def cmd_config(session: ReplSession, args: str) -> None:
    from urika.cli import config_command

    arg = args.strip().lstrip("-")
    ctx = click.Context(config_command)

    if arg == "show":
        # Show project config if project loaded, else global
        ctx.invoke(
            config_command,
            project=session.project_name if session.has_project else None,
            show=True,
            json_output=False,
        )
    elif arg == "global":
        # Force global config
        ctx.invoke(
            config_command,
            project=None,
            show=False,
            json_output=False,
        )
    elif arg == "global show":
        ctx.invoke(
            config_command,
            project=None,
            show=True,
            json_output=False,
        )
    else:
        # Default: configure current project if loaded, else global
        ctx.invoke(
            config_command,
            project=session.project_name if session.has_project else None,
            show=False,
            json_output=False,
        )


@command("notifications", description="Configure notification channels")
def cmd_notifications(session: ReplSession, args: str) -> None:
    from urika.cli import notifications_command

    arg = args.strip().lstrip("-")
    ctx = click.Context(notifications_command)

    project = session.project_name if session.has_project else None

    if arg == "show":
        ctx.invoke(
            notifications_command,
            show=True,
            send_test=False,
            disable=False,
            project=project,
        )
    elif arg == "test":
        ctx.invoke(
            notifications_command,
            show=False,
            send_test=True,
            disable=False,
            project=project,
        )
    elif arg == "disable":
        ctx.invoke(
            notifications_command,
            show=False,
            send_test=False,
            disable=True,
            project=project,
        )
    else:
        ctx.invoke(
            notifications_command,
            show=False,
            send_test=False,
            disable=False,
            project=project,
        )


@command("usage", description="Show usage stats")
def cmd_usage(session: ReplSession, args: str) -> None:
    from urika.cli_display import _format_duration
    from urika.core.usage import format_usage, get_last_session, get_totals

    # Check if on subscription (SDK cost returns None)
    is_sub = session.total_cost_usd == 0 and session.agent_calls > 0

    if session.has_project:
        click.echo(f"\n  {_C.BOLD}Usage: {session.project_name}{_C.RESET}")

        # Current session
        elapsed = _format_duration(session.elapsed_ms)
        tokens = session.total_tokens_in + session.total_tokens_out
        cost_str = f"~${session.total_cost_usd:.2f}"
        if is_sub:
            cost_str += " (estimated \u2014 plan user)"
        click.echo(
            f"  This session: {elapsed} \u00b7 {_fmt_tokens(tokens)} tokens \u00b7 "
            f"{cost_str} \u00b7 {session.agent_calls} agent calls"
        )

        # Historical
        last = get_last_session(session.project_path)
        totals = get_totals(session.project_path)
        if totals.get("sessions", 0) > 0:
            click.echo(format_usage(last, totals, is_subscription=is_sub))
    else:
        # Show usage across all projects
        from urika.core.registry import ProjectRegistry

        registry = ProjectRegistry()
        projects = registry.list_all()
        if not projects:
            click.echo("  No projects.")
            return

        click.echo(f"\n  {_C.BOLD}Usage across all projects:{_C.RESET}")
        grand_tokens = 0
        grand_cost = 0.0
        grand_calls = 0
        grand_sessions = 0
        for name, path in projects.items():
            totals = get_totals(path)
            if totals.get("sessions", 0) > 0:
                tokens = totals.get("total_tokens_in", 0) + totals.get(
                    "total_tokens_out", 0
                )
                click.echo(
                    f"  {name}: {totals['sessions']} sessions \u00b7 "
                    f"{_fmt_tokens(tokens)} tokens \u00b7 "
                    f"~${totals['total_cost_usd']:.2f}"
                )
                grand_tokens += tokens
                grand_cost += totals["total_cost_usd"]
                grand_calls += totals["total_agent_calls"]
                grand_sessions += totals["sessions"]
        if grand_sessions > 0:
            click.echo(
                f"\n  {_C.BOLD}Total: {grand_sessions} sessions \u00b7 "
                f"{_fmt_tokens(grand_tokens)} tokens \u00b7 "
                f"~${grand_cost:.2f} \u00b7 {grand_calls} agent calls{_C.RESET}"
            )
    click.echo()


@command("tools", description="List available tools")
def cmd_tools(session: ReplSession, args: str) -> None:
    from urika.tools import ToolRegistry

    registry = ToolRegistry()
    registry.discover()

    # Also discover project-specific tools if a project is loaded
    if session.has_project:
        registry.discover_project(session.project_path / "tools")

    names = registry.list_all()
    if not names:
        click.echo("  No tools found.")
        return
    click.echo()
    for name in names:
        tool = registry.get(name)
        if tool is not None:
            click.echo(f"    {tool.name()}  [{tool.category()}]  {tool.description()}")
    click.echo()


@command("stop", requires_project=True, description="Stop the running agent/experiment")
def cmd_stop(session: ReplSession, args: str) -> None:
    """Stop the currently running agent or experiment immediately."""
    if not session.agent_active:
        click.echo("  No agent is currently running.")
        return

    # Write stop flag for run_experiment's PauseController
    if session.project_path:
        flag = session.project_path / ".urika" / "pause_requested"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("stop", encoding="utf-8")

    active = session.active_command
    session.set_agent_inactive()
    click.echo(f"  Stopped {active}.")


@command("pause", requires_project=True, description="Pause experiment after current subagent")
def cmd_pause(session: ReplSession, args: str) -> None:
    """Pause the running experiment after the current subagent finishes."""
    if not session.agent_active:
        click.echo("  No agent is currently running.")
        return

    if session.project_path:
        flag = session.project_path / ".urika" / "pause_requested"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("pause", encoding="utf-8")

    click.echo("  Pausing after current subagent finishes...")
    click.echo("  Type /resume to continue.")


# ── Project-specific commands ───────────────────────────────


@command("status", requires_project=True, description="Show project status")
def cmd_status(session: ReplSession, args: str) -> None:
    from urika.cli import status as cli_status

    # Call the existing status function
    ctx = click.Context(cli_status)
    ctx.invoke(cli_status, name=session.project_name)


@command("run", requires_project=True, description="Run next experiment")
def cmd_run(session: ReplSession, args: str) -> None:
    import click as _click
    from urika.cli_display import print_warning
    from urika.core.experiment import list_experiments

    is_remote = session._is_remote_command

    # Parse remote args: /run, /run 3, /run --multi 5, /run --resume, /run try trees
    remote_parsed = _parse_remote_run_args(args) if is_remote else None

    # Handle --resume via remote
    if remote_parsed and remote_parsed.get("resume"):
        cmd_resume(session, "")
        return

    # Check if any experiment is already running (lockfile exists)
    experiments = list_experiments(session.project_path)
    for exp in experiments:
        lock = session.project_path / "experiments" / exp.experiment_id / ".lock"
        if lock.exists():
            # Check if the owning process is still alive
            import os as _os
            try:
                pid_str = lock.read_text().strip()
                if pid_str:
                    _os.kill(int(pid_str), 0)
                    # Process alive — lock is valid
                else:
                    # Empty lock (legacy) — treat as valid conservatively
                    pass
            except (ValueError, ProcessLookupError):
                # PID dead or invalid — stale lock, clean it up
                click.echo(f"  Cleaned stale lock on {exp.experiment_id}")
                lock.unlink(missing_ok=True)
                continue
            except PermissionError:
                pass  # Process exists, can't signal — treat as valid

            if is_remote:
                click.echo(
                    f"  Experiment '{exp.experiment_id}' locked — stopping stale lock."
                )
                try:
                    from urika.core.session import stop_session

                    stop_session(
                        session.project_path,
                        exp.experiment_id,
                        reason="Stopped by remote run",
                    )
                except Exception:
                    lock.unlink(missing_ok=True)
                break

            print_warning(f"Experiment '{exp.experiment_id}' is currently running.")
            choice = _prompt_numbered(
                "  What would you like to do?",
                [
                    "Wait for it to complete (recommended)",
                    "Stop it and start a new run",
                    "Cancel",
                ],
                default=1,
            )
            if choice.startswith("Wait"):
                click.echo("  Waiting is recommended. Check back after it completes.")
                return
            if choice.startswith("Cancel"):
                return
            # Stop it
            try:
                from urika.core.session import stop_session

                stop_session(
                    session.project_path,
                    exp.experiment_id,
                    reason="Stopped by user from REPL",
                )
                click.echo(f"  Stopped {exp.experiment_id}")
            except Exception:
                lock.unlink(missing_ok=True)
            break

    defaults = _load_run_defaults(session)

    if is_remote:
        # Remote: skip all interactive prompts, use defaults + parsed args
        max_turns = remote_parsed.get("max_turns") or defaults["max_turns"]
        auto_mode = defaults["auto_mode"]
        max_experiments = remote_parsed.get("max_experiments")
        run_instructions = remote_parsed.get("instructions", "")
        review_criteria = False

        # Show summary
        click.echo("\n  Run settings (remote):")
        click.echo(f"    Max turns:    {max_turns}")
        if max_experiments:
            click.echo(f"    Experiments:  up to {max_experiments}")
        if run_instructions:
            instr_preview = (
                run_instructions[:80] + "..."
                if len(run_instructions) > 80
                else run_instructions
            )
            click.echo(f"    Instructions: {instr_preview}")
        click.echo()
    else:
        # Interactive: show defaults, offer custom
        click.echo("\n  Run settings:")
        click.echo(f"    Max turns: {defaults['max_turns']}")
        click.echo(f"    Auto mode: {defaults['auto_mode']}")
        instructions = (
            session.get_conversation_context() if session.conversation else "(none)"
        )
        click.echo(
            f"    Instructions: {instructions[:80]}{'...' if len(instructions) > 80 else ''}"
        )

        choice = _prompt_numbered(
            "\n  Proceed?",
            ["Run with defaults", "Custom settings", "Skip"],
            default=1,
        )

        if choice == "Skip":
            return

        max_turns = defaults["max_turns"]
        auto_mode = defaults["auto_mode"]
        max_experiments = None
        run_instructions = ""
        review_criteria = False

        if choice == "Custom settings":
            try:
                max_turns = int(
                    _click.prompt("  Max turns", default=str(defaults["max_turns"]))
                )
            except ValueError:
                pass  # keep default max_turns
            auto_mode = _prompt_numbered(
                "\n  Auto mode:",
                [
                    "Checkpoint \u2014 pause between experiments for review",
                    "Capped \u2014 run up to max experiments with no pauses",
                    "Unlimited \u2014 run until criteria met or advisor says done",
                ],
                default={"checkpoint": 1, "capped": 2, "unlimited": 3}.get(
                    defaults["auto_mode"], 1
                ),
            )
            # Map back to short name
            auto_mode = {
                "Checkpoint": "checkpoint",
                "Capped": "capped",
                "Unlimited": "unlimited",
            }.get(auto_mode.split("\u2014")[0].strip(), "checkpoint")
            if auto_mode == "capped":
                try:
                    max_experiments = int(_click.prompt("  Max experiments", default="10"))
                except ValueError:
                    max_experiments = 10
            elif auto_mode == "unlimited":
                max_experiments = 50  # safety cap
            run_instructions = _click.prompt(
                "  Instructions (optional, enter to skip)", default=""
            )
            rc_choice = _prompt_numbered(
                "\n  Re-evaluate criteria if met?",
                [
                    "No \u2014 complete when criteria met (default)",
                    "Yes \u2014 advisor reviews criteria, may raise the bar",
                ],
                default=1,
            )
            review_criteria = rc_choice.startswith("Yes")

        # Show settings summary
        click.echo()
        click.echo("  Run settings:")
        click.echo(f"    Max turns:    {max_turns}")
        if max_experiments:
            click.echo(f"    Experiments:  up to {max_experiments}")
            click.echo(f"    Auto mode:    {auto_mode}")
        else:
            click.echo("    Auto mode:    single experiment")
        if run_instructions:
            instr_preview = (
                run_instructions[:80] + "..."
                if len(run_instructions) > 80
                else run_instructions
            )
            click.echo(f"    Instructions: {instr_preview}")
        if review_criteria:
            click.echo("    Review criteria: yes")
        click.echo()

    # Use conversation context as instructions if none provided
    if not run_instructions and session.conversation:
        run_instructions = session.get_conversation_context()

    # If we have pending suggestions from advisor, create the experiment
    # directly instead of having cli_run call the advisor again from scratch
    use_experiment_id = None
    if session.pending_suggestions:
        suggestion = session.pending_suggestions[0]
        exp_name = (
            suggestion.get("name", "advisor-experiment").replace(" ", "-").lower()
        )
        description = suggestion.get("method", suggestion.get("description", ""))
        if run_instructions and description:
            description = f"{run_instructions}\n\n{description}"
        elif run_instructions:
            description = run_instructions

        try:
            from urika.core.experiment import create_experiment

            exp = create_experiment(
                session.project_path,
                name=exp_name,
                hypothesis=description[:500] if description else "",
            )
            use_experiment_id = exp.experiment_id
            click.echo(
                f"  Created experiment from advisor suggestion: {use_experiment_id}"
            )
            # Use description as instructions for the experiment run
            if description:
                run_instructions = description
            # Pop the used suggestion, keep the rest for subsequent runs
            session.pending_suggestions = session.pending_suggestions[1:]
        except Exception as exc:
            click.echo(f"  Could not create experiment: {exc}")
            # Fall through to normal flow

    # Run directly without going through CLI (avoids duplicate header)
    import os

    global _user_input_callback, _repl_session_ref  # noqa: PLW0603

    def _get_user_input() -> str:
        return session.pop_queued_input()

    os.environ["URIKA_REPL"] = "1"
    _user_input_callback = _get_user_input
    _repl_session_ref = session
    session.set_agent_active("run")
    try:
        from urika.cli import run as cli_run

        ctx = click.Context(cli_run)
        ctx.invoke(
            cli_run,
            project=session.project_name,
            experiment_id=use_experiment_id,
            max_turns=max_turns,
            resume=False,
            quiet=False,
            auto=(is_remote or auto_mode != "checkpoint"),
            instructions=run_instructions,
            max_experiments=max_experiments,
            review_criteria=review_criteria,
        )
        session.experiments_run += 1
    finally:
        session.set_agent_idle()
        _user_input_callback = None
        _repl_session_ref = None
        os.environ.pop("URIKA_REPL", None)


def _parse_remote_run_args(args: str) -> dict:
    """Parse remote /run arguments into a settings dict.

    Supported formats:
      /run               -> defaults
      /run 3             -> max_turns=3
      /run --multi 5     -> max_experiments=5
      /run --resume      -> resume=True
      /run try trees     -> instructions="try trees"
      /run --multi 3 focus on features -> max_experiments=3, instructions="focus on features"
    """
    result: dict = {
        "max_turns": None,
        "max_experiments": None,
        "resume": False,
        "instructions": "",
    }

    args_stripped = args.strip()
    if not args_stripped:
        return result

    parts = args_stripped.split()
    if parts[0] == "--resume":
        result["resume"] = True
    elif parts[0] == "--multi" and len(parts) > 1:
        try:
            result["max_experiments"] = int(parts[1])
            if len(parts) > 2:
                result["instructions"] = " ".join(parts[2:])
        except ValueError:
            result["instructions"] = args_stripped
    else:
        try:
            result["max_turns"] = int(parts[0])
            if len(parts) > 1:
                result["instructions"] = " ".join(parts[1:])
        except ValueError:
            result["instructions"] = args_stripped

    return result


@command("experiments", requires_project=True, description="List experiments")
def cmd_experiments(session: ReplSession, args: str) -> None:
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    experiments = list_experiments(session.project_path)
    if not experiments:
        click.echo("  No experiments yet.")
        return
    click.echo()
    for exp in experiments:
        progress = load_progress(session.project_path, exp.experiment_id)
        runs = progress.get("runs", [])
        status = progress.get("status", "pending")
        click.echo(f"    {exp.experiment_id}  [{status}, {len(runs)} runs]")
    click.echo()


@command("methods", requires_project=True, description="Show methods table")
def cmd_methods(session: ReplSession, args: str) -> None:
    from urika.core.method_registry import load_methods

    methods = load_methods(session.project_path)
    if not methods:
        click.echo("  No methods yet.")
        return
    click.echo()
    for m in methods:
        metrics = m.get("metrics", {})
        nums = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
        metric_str = ", ".join(f"{k}={v}" for k, v in list(nums.items())[:2])
        click.echo(f"    {m['name']}  [{m.get('status', '')}]  {metric_str}")
    click.echo()


@command(
    "results", requires_project=True, description="Show project results/leaderboard"
)
def cmd_results(session: ReplSession, args: str) -> None:
    from urika.evaluation.leaderboard import load_leaderboard
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    # Parse optional experiment filter from args
    experiment_filter = args.strip() if args else ""

    leaderboard = load_leaderboard(session.project_path)
    ranking = leaderboard.get("ranking", [])

    if ranking and not experiment_filter:
        click.echo(f"\n  {_C.BOLD}Leaderboard:{_C.RESET}")
        for entry in ranking:
            metrics_str = ", ".join(
                f"{k}={v}" for k, v in entry.get("metrics", {}).items()
            )
            click.echo(f"    #{entry['rank']}  {entry['method']}  {metrics_str}")
        click.echo()
        return

    # No leaderboard or specific experiment requested — show runs
    experiments = list_experiments(session.project_path)
    if not experiments:
        click.echo("  No results yet.")
        return

    if experiment_filter:
        matched = [e for e in experiments if e.experiment_id == experiment_filter]
        if not matched:
            click.echo(f"  Experiment '{experiment_filter}' not found.")
            return
        exp = matched[0]
    else:
        exp = experiments[-1]
    progress = load_progress(session.project_path, exp.experiment_id)
    runs = progress.get("runs", [])
    if not runs:
        click.echo("  No results yet.")
        return

    click.echo(f"\n  {_C.BOLD}Runs for {exp.experiment_id}:{_C.RESET}")
    for run in runs:
        metrics_str = ", ".join(f"{k}={v}" for k, v in run.get("metrics", {}).items())
        click.echo(f"    {run['run_id']}  {run['method']}  {metrics_str}")
    click.echo()


@command(
    "resume",
    requires_project=True,
    description="Resume a paused/stopped/failed experiment",
)
def cmd_resume(session: ReplSession, args: str) -> None:
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    experiments = list_experiments(session.project_path)
    resumable = []
    for exp in experiments:
        progress = load_progress(session.project_path, exp.experiment_id)
        status = progress.get("status", "pending")
        if status in ("paused", "stopped", "failed"):
            resumable.append((exp, status))

    if not resumable:
        click.echo("  No paused, stopped, or failed experiments to resume.")
        return

    # If multiple, let user pick; if one or remote, use most recent directly
    if len(resumable) == 1 or session._is_remote_command:
        exp, status = resumable[-1]  # Most recent resumable
        click.echo(f"  Resuming {exp.experiment_id} [{status}]...")
    else:
        options = [f"{exp.experiment_id} [{status}]" for exp, status in resumable]
        choice = _prompt_numbered(
            "\n  Select experiment to resume:", options, default=1
        )
        exp_id = choice.split(" [")[0]
        click.echo(f"  Resuming {exp_id}...")
        # Find matching exp
        exp = next(e for e, _s in resumable if e.experiment_id == exp_id)

    import os

    is_remote = session._is_remote_command

    global _repl_session_ref  # noqa: PLW0603

    os.environ["URIKA_REPL"] = "1"
    _repl_session_ref = session
    session.set_agent_active("run")
    try:
        from urika.cli import run as cli_run

        ctx = click.Context(cli_run)
        defaults = _load_run_defaults(session)
        ctx.invoke(
            cli_run,
            project=session.project_name,
            experiment_id=exp.experiment_id,
            max_turns=defaults["max_turns"],
            resume=True,
            quiet=False,
            auto=(is_remote or defaults["auto_mode"] != "checkpoint"),
            instructions="",
            max_experiments=None,
        )
    finally:
        session.set_agent_idle()
        _repl_session_ref = None
        os.environ.pop("URIKA_REPL", None)


@command("criteria", requires_project=True, description="Show current criteria")
def cmd_criteria(session: ReplSession, args: str) -> None:
    from urika.core.criteria import load_criteria

    c = load_criteria(session.project_path)
    if c is None:
        click.echo("  No criteria set.")
        return
    click.echo(f"\n  Criteria v{c.version} (set by {c.set_by})")
    click.echo(f"  Type: {c.criteria.get('type', 'unknown')}")
    threshold = c.criteria.get("threshold", {})
    primary = threshold.get("primary", {})
    if primary:
        click.echo(
            f"  Primary: {primary.get('metric')} {primary.get('direction', '>')} {primary.get('target')}"
        )
    click.echo()


@command("resume-session", requires_project=True, description="Resume previous orchestrator session")
def cmd_resume_session(session: ReplSession, args: str) -> None:
    """Resume a previous orchestrator conversation."""
    from urika.core.orchestrator_sessions import list_sessions, load_session

    sessions = list_sessions(session.project_path)
    if not sessions:
        click.echo("  No saved sessions for this project.")
        return

    if not args:
        # Show numbered list
        click.echo()
        click.echo("  Recent sessions:")
        click.echo()
        for i, s in enumerate(sessions[:10]):
            from datetime import datetime

            try:
                dt = datetime.fromisoformat(s["updated"]).strftime("%Y-%m-%d %H:%M")
            except Exception:
                dt = s.get("updated", "?")
            preview = (s.get("preview") or "(empty)")[:60]
            turns = s.get("turn_count", 0)
            click.echo(f"    {i + 1}. {dt} \u00b7 {turns} turns")
            click.echo(f"       {preview}")
        click.echo()
        click.echo("  Type /resume-session <number> to resume.")
        click.echo()
        return

    # Resume by number
    try:
        num = int(args)
    except ValueError:
        click.echo(f"  Invalid number: {args}")
        return

    if num < 1 or num > len(sessions):
        click.echo("  Invalid session number. Use /resume-session to see the list.")
        return

    entry = sessions[num - 1]
    loaded = load_session(session.project_path, entry["session_id"])
    if not loaded:
        click.echo(f"  Session not found: {entry['session_id']}")
        return

    # Restore conversation to the orchestrator
    from urika.repl.main import _get_orchestrator

    orchestrator = _get_orchestrator(session)
    orchestrator.set_messages(loaded.recent_messages)
    session._orch_session = loaded

    turns = len(loaded.recent_messages) // 2
    click.echo(f"  Resumed session ({turns} turns)")


@command("new-session", requires_project=True, description="Start a new orchestrator conversation")
def cmd_new_session(session: ReplSession, args: str) -> None:
    """Clear the orchestrator conversation and start fresh."""
    from urika.repl.main import _get_orchestrator

    orchestrator = _get_orchestrator(session)
    orchestrator.clear()
    session._orch_session = None
    click.echo("  Started a new session. Previous conversation archived.")


# Register imported agent commands
command("advisor", requires_project=True, description="Ask the advisor agent a question")(cmd_advisor)
command("evaluate", requires_project=True, description="Run evaluator on an experiment")(cmd_evaluate)
command("plan", requires_project=True, description="Run planning agent to design a method")(cmd_plan)
command("report", requires_project=True, description="Generate reports")(cmd_report)
command("present", requires_project=True, description="Generate presentation for an experiment")(cmd_present)
command("finalize", requires_project=True, description="Finalize project \u2014 methods, report, presentation")(cmd_finalize)
command("build-tool", requires_project=True, description="Build a custom tool for the project")(cmd_build_tool)


@command("inspect", requires_project=True, description="Inspect dataset")
def cmd_inspect(session: ReplSession, args: str) -> None:
    from urika.cli import inspect as cli_inspect

    ctx = click.Context(cli_inspect)
    ctx.invoke(
        cli_inspect, project=session.project_name, data_file=args.strip() or None
    )


@command("logs", requires_project=True, description="Show experiment logs")
def cmd_logs(session: ReplSession, args: str) -> None:
    from urika.cli import logs as cli_logs

    ctx = click.Context(cli_logs)
    ctx.invoke(
        cli_logs, project=session.project_name, experiment_id=args.strip() or None
    )


@command(
    "knowledge", requires_project=True, description="Search, list, or ingest knowledge"
)
def cmd_knowledge(session: ReplSession, args: str) -> None:
    from urika.knowledge import KnowledgeStore

    arg = args.strip()
    store = KnowledgeStore(session.project_path)

    # /knowledge ingest <path>
    if arg.startswith("ingest "):
        source = arg[7:].strip()
        if not source:
            click.echo("  Usage: /knowledge ingest <path>")
            return
        try:
            entry = store.ingest(source)
            click.echo(f'  Ingested: {entry.id} "{entry.title}" ({entry.source_type})')
        except (FileNotFoundError, ValueError) as exc:
            click.echo(f"  Error: {exc}")
        return

    # /knowledge <query> — search
    if arg:
        results = store.search(arg)
        if not results:
            click.echo("  No results.")
            return
        for entry in results:
            snippet = entry.content[:80].replace("\n", " ")
            click.echo(f"    {entry.id}  {entry.title}  {_C.DIM}{snippet}{_C.RESET}")
    else:
        # /knowledge — list all
        entries = store.list_all()
        if not entries:
            click.echo("  No knowledge entries.")
            return
        for entry in entries:
            click.echo(f"    {entry.id}  {entry.title}  [{entry.source_type}]")


@command(
    "update",
    requires_project=True,
    description="Update project description, question, or mode",
)
def cmd_update(session: ReplSession, args: str) -> None:
    parts = args.strip().split(None, 1) if args.strip() else []

    if parts and parts[0] == "history":
        from urika.core.revisions import load_revisions

        revs = load_revisions(session.project_path)
        if not revs:
            click.echo("  No revisions recorded.")
            return
        click.echo("\n  Revision history:\n")
        for r in revs:
            ts = r["timestamp"][:19].replace("T", " ")
            click.echo(f"  #{r['revision']}  {ts}  [{r['field']}]")
            old = r["old_value"][:60]
            new = r["new_value"][:60]
            click.echo(f"    Old: {old}")
            click.echo(f"    New: {new}")
            if r.get("reason"):
                click.echo(f"    Why: {r['reason']}")
            click.echo()
        return

    import os

    os.environ["URIKA_REPL"] = "1"
    try:
        from urika.cli import update_project

        ctx = click.Context(update_project)
        ctx.invoke(
            update_project,
            project=session.project_name,
        )
    finally:
        os.environ.pop("URIKA_REPL", None)


_dashboard_server = None


@command(
    "dashboard",
    requires_project=True,
    description="Open project dashboard in browser",
)
def cmd_dashboard(session: ReplSession, args: str) -> None:
    import threading

    from urika.dashboard.server import DashboardServer

    global _dashboard_server

    parts = args.strip().split()

    # /dashboard stop — shut down running server
    if parts and parts[0] in ("stop", "--stop"):
        if _dashboard_server is not None:
            _dashboard_server.shutdown()
            _dashboard_server = None
            click.echo("  Dashboard stopped.")
        else:
            click.echo("  No dashboard running.")
        return

    # If already running, stop it first (restart)
    if _dashboard_server is not None:
        _dashboard_server.shutdown()
        _dashboard_server = None

    # Parse --port from args
    port = 8420
    for i, part in enumerate(parts):
        if part == "--port" and i + 1 < len(parts):
            try:
                port = int(parts[i + 1])
            except ValueError:
                click.echo("  Invalid port number.")
                return

    try:
        server = DashboardServer(session.project_path, port=port)
    except OSError as e:
        click.echo(f"  Cannot start dashboard: {e}")
        return

    _dashboard_server = server
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    import webbrowser

    webbrowser.open(url)
    click.echo(f"  Dashboard running at {url}")
    click.echo("  /dashboard stop to shut down, /dashboard to restart")
