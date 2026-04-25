"""Planning helpers for `urika run`.

Split out of cli/run.py as part of Phase 8 refactoring. Holds the
"choose what to run" logic — both the dry-run preview and the
"determine the next experiment" flow.

These are pure helpers: no @cli.command decorators here. The ``run``
command itself stays in cli/run.py and imports from this module.
"""

from __future__ import annotations

from pathlib import Path

import click

from urika.cli._helpers import _prompt_numbered
from urika.core.experiment import create_experiment, list_experiments
from urika.core.progress import load_progress


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
