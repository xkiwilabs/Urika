"""Agent-related CLI commands that stay compact enough for one module.

The larger commands — ``report`` (with ``_run_report_agent``),
``finalize``, and ``present`` — live in their own modules:
``cli/agents_report.py``, ``cli/agents_finalize.py``, and
``cli/agents_present.py``. They are re-exported at the bottom of this
file so ``from urika.cli.agents import report`` / ``finalize`` /
``present`` / ``_run_report_agent`` keep working.
"""

from __future__ import annotations

import asyncio

import click

from urika.cli._base import cli
from urika.core.errors import ConfigError
from urika.core.experiment import list_experiments

from urika.cli._helpers import (
    _agent_run_start,
    _make_on_message,
    _record_agent_usage,
    _resolve_project,
    _ensure_project,
)
from urika.cli.run import _offer_to_run_advisor_suggestions


@cli.command()
@click.argument("project", required=False, default=None)
@click.argument("text", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def advisor(project: str | None, text: str | None, json_output: bool) -> None:
    """Ask the advisor agent a question about the project."""

    from urika.cli_display import Spinner, format_agent_output, print_agent

    from urika.cli_helpers import interactive_prompt

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if text is None:
        text = interactive_prompt("Question or instructions", required=True)

    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
    except ImportError:
        raise ConfigError(
            "Claude Agent SDK not installed.",
            hint="Run: pip install claude-agent-sdk",
        )

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("advisor_agent")
    if role is None:
        raise ConfigError(
            "Advisor agent not found in registry.",
            hint="Reinstall urika to restore the built-in agent registry.",
        )

    if not json_output:
        print_agent("advisor_agent")
    config = role.build_config(project_dir=project_path, experiment_id="")
    config.max_turns = 25  # Standalone chat needs more turns than in-loop advisor

    # Build richer context — inject rolling summary from previous sessions
    import json as _json

    from urika.core.advisor_memory import load_context_summary

    context = f"Project: {project}\n"
    context_summary = load_context_summary(project_path)
    if context_summary:
        context += (
            f"\n## Research Context (from previous sessions)\n\n{context_summary}\n\n"
        )
    context += f"\nUser: {text}\n"
    methods_path = project_path / "methods.json"
    if methods_path.exists():
        try:
            mdata = _json.loads(methods_path.read_text(encoding="utf-8"))
            mlist = mdata.get("methods", [])
            context += f"\n{len(mlist)} methods tried.\n"
        except Exception:
            pass

    _start_ms, _start_iso = _agent_run_start()

    try:
        with Spinner("Thinking"):
            result = asyncio.run(
                runner.run(
                    config,
                    context,
                    on_message=_make_on_message()
                    if not json_output
                    else lambda m: None,
                )
            )
    except KeyboardInterrupt:
        click.echo("\n  Advisor stopped.")
        return

    _record_agent_usage(project_path, result, _start_iso, _start_ms)

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"output": result.text_output.strip() if result.success else result.error}
        )
        return

    if result.success and result.text_output:
        click.echo(format_agent_output(result.text_output))

        # Save to persistent advisor history
        from urika.core.advisor_memory import append_exchange

        advisor_text = result.text_output.strip()
        append_exchange(project_path, role="user", text=text, source="cli")

        from urika.orchestrator.parsing import parse_suggestions as _parse_sug

        _parsed = _parse_sug(advisor_text)
        _parsed_suggestions = (
            _parsed["suggestions"] if _parsed and _parsed.get("suggestions") else None
        )
        append_exchange(
            project_path,
            role="advisor",
            text=advisor_text,
            source="cli",
            suggestions=_parsed_suggestions,
        )

        # Update rolling context summary in a separate thread
        try:
            import concurrent.futures
            from urika.core.advisor_memory import update_context_summary

            def _do_summary():
                return asyncio.run(
                    update_context_summary(project_path, runner, registry)
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
                _pool.submit(_do_summary).result(timeout=120)
        except Exception:
            pass

        _offer_to_run_advisor_suggestions(result.text_output, project, project_path)
    else:
        click.echo(f"Error: {result.error}")


@cli.command()
@click.argument("project", required=False, default=None)
@click.argument("experiment_id", required=False, default=None)
@click.option(
    "--instructions",
    default="",
    help="Guide evaluation (e.g. 'check for overfitting').",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def evaluate(
    project: str | None, experiment_id: str | None, instructions: str, json_output: bool
) -> None:
    """Run the evaluator agent on an experiment."""

    from urika.cli_display import Spinner, format_agent_output, print_agent

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            raise click.ClickException("No experiments.")
        experiment_id = experiments[-1].experiment_id

    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
    except ImportError:
        raise ConfigError(
            "Claude Agent SDK not installed.",
            hint="Run: pip install claude-agent-sdk",
        )

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("evaluator")
    if role is None:
        raise ConfigError(
            "Evaluator agent not found in registry.",
            hint="Reinstall urika to restore the built-in agent registry.",
        )

    if not json_output:
        print_agent("evaluator")
    config = role.build_config(project_dir=project_path, experiment_id=experiment_id)

    prompt = f"Evaluate experiment {experiment_id}."
    if instructions:
        prompt = f"User instructions: {instructions}\n\n{prompt}"

    _start_ms, _start_iso = _agent_run_start()

    if not json_output:
        click.echo(f"  Evaluating {experiment_id}...")
    try:
        with Spinner("Working"):
            result = asyncio.run(
                runner.run(
                    config,
                    prompt,
                    on_message=_make_on_message()
                    if not json_output
                    else lambda m: None,
                )
            )
    except KeyboardInterrupt:
        click.echo("\n  Evaluation stopped.")
        click.echo("  Re-run with: urika evaluate [--instructions '...']")
        return

    _record_agent_usage(project_path, result, _start_iso, _start_ms)

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"output": result.text_output.strip() if result.success else result.error}
        )
        return

    if result.success and result.text_output:
        click.echo(format_agent_output(result.text_output))
    else:
        click.echo(f"Error: {result.error}")


@cli.command()
@click.argument("project", required=False, default=None)
@click.argument("experiment_id", required=False, default=None)
@click.option(
    "--instructions",
    default="",
    help="Guide the plan (e.g. 'consider Bayesian approaches').",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def plan(
    project: str | None, experiment_id: str | None, instructions: str, json_output: bool
) -> None:
    """Run the planning agent to design the next method."""

    from urika.cli_display import Spinner, format_agent_output, print_agent

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            raise click.ClickException("No experiments.")
        experiment_id = experiments[-1].experiment_id

    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
    except ImportError:
        raise ConfigError(
            "Claude Agent SDK not installed.",
            hint="Run: pip install claude-agent-sdk",
        )

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("planning_agent")
    if role is None:
        raise ConfigError(
            "Planning agent not found in registry.",
            hint="Reinstall urika to restore the built-in agent registry.",
        )

    if not json_output:
        print_agent("planning_agent")
    config = role.build_config(project_dir=project_path, experiment_id=experiment_id)

    prompt = "Design the next method based on current results."
    if instructions:
        prompt = f"User instructions: {instructions}\n\n{prompt}"

    _start_ms, _start_iso = _agent_run_start()

    if not json_output:
        click.echo(f"  Planning for {experiment_id}...")
    try:
        with Spinner("Designing method"):
            result = asyncio.run(
                runner.run(
                    config,
                    prompt,
                    on_message=_make_on_message()
                    if not json_output
                    else lambda m: None,
                )
            )
    except KeyboardInterrupt:
        click.echo("\n  Planning stopped.")
        click.echo("  Re-run with: urika plan [--instructions '...']")
        return

    _record_agent_usage(project_path, result, _start_iso, _start_ms)

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"output": result.text_output.strip() if result.success else result.error}
        )
        return

    if result.success and result.text_output:
        click.echo(format_agent_output(result.text_output))
    else:
        click.echo(f"Error: {result.error}")


@cli.command("build-tool")
@click.argument("project", required=False, default=None)
@click.argument("instructions", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def build_tool(
    project: str | None, instructions: str | None, json_output: bool
) -> None:
    """Build a custom tool for the project.

    Give the tool builder agent instructions to create a specific tool,
    install a package, or build a data reader. Examples:

    \b
      urika build-tool my-project "create an EEG epoch extractor using MNE"
      urika build-tool my-project "build a tool that computes ICC using pingouin"
      urika build-tool my-project "install librosa and create an audio feature extractor"
    """

    from urika.cli_display import Spinner, format_agent_output, print_agent
    from urika.cli_helpers import interactive_prompt

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if instructions is None:
        instructions = interactive_prompt(
            "Describe the tool to build (e.g., 'create a correlation heatmap tool using seaborn')",
            required=True,
        )

    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
    except ImportError:
        raise ConfigError(
            "Claude Agent SDK not installed.",
            hint="Run: pip install claude-agent-sdk",
        )

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("tool_builder")
    if role is None:
        raise ConfigError(
            "Tool builder agent not found in registry.",
            hint="Reinstall urika to restore the built-in agent registry.",
        )

    if not json_output:
        print_agent("tool_builder")
    config = role.build_config(project_dir=project_path)

    _start_ms, _start_iso = _agent_run_start()

    try:
        with Spinner("Building tool"):
            result = asyncio.run(
                runner.run(
                    config,
                    instructions,
                    on_message=_make_on_message()
                    if not json_output
                    else lambda m: None,
                )
            )
    except KeyboardInterrupt:
        click.echo("\n  Tool build stopped.")
        return

    _record_agent_usage(project_path, result, _start_iso, _start_ms)

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"output": result.text_output.strip() if result.success else result.error}
        )
        return

    if result.success and result.text_output:
        click.echo(format_agent_output(result.text_output))
    else:
        click.echo(f"Error: {result.error}")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--instructions",
    default=None,
    help="Optional guidance to steer the summarizer (e.g. 'focus on open questions').",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def summarize(project: str | None, instructions: str | None, json_output: bool) -> None:
    """Summarize the current state of a project."""

    from urika.cli_display import Spinner, format_agent_output, print_agent

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
    except ImportError:
        raise ConfigError(
            "Claude Agent SDK not installed.",
            hint="Run: pip install claude-agent-sdk",
        )

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("project_summarizer")
    if role is None:
        raise ConfigError(
            "Project summarizer agent not found in registry.",
            hint="Reinstall urika to restore the built-in agent registry.",
        )

    if not json_output:
        print_agent("project_summarizer")
    config = role.build_config(project_dir=project_path)

    prompt = "Summarize the current state of this project."
    if instructions:
        prompt = prompt + "\n\nAdditional guidance:\n" + instructions

    _start_ms, _start_iso = _agent_run_start()

    try:
        with Spinner("Summarizing"):
            result = asyncio.run(
                runner.run(
                    config,
                    prompt,
                    on_message=_make_on_message()
                    if not json_output
                    else lambda m: None,
                )
            )
    except KeyboardInterrupt:
        click.echo("\n  Summarize stopped.")
        click.echo("  Re-run with: urika summarize")
        return

    _record_agent_usage(project_path, result, _start_iso, _start_ms)

    # Best-effort persistence of the summary to projectbook/summary.md so the
    # dashboard can detect prior state and flip the "Summarize" button label
    # to "Re-summarize". Failures (disk full, locked path) are swallowed so
    # they never break the CLI flow.
    if result.success and result.text_output:
        try:
            book_dir = project_path / "projectbook"
            book_dir.mkdir(parents=True, exist_ok=True)
            (book_dir / "summary.md").write_text(
                result.text_output.strip() + "\n", encoding="utf-8"
            )
        except OSError:
            pass

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"output": result.text_output.strip() if result.success else result.error}
        )
        return

    if result.success and result.text_output:
        click.echo(format_agent_output(result.text_output))
    else:
        click.echo(f"Error: {result.error}")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def criteria(project: str | None, json_output: bool) -> None:
    """Show current project criteria."""
    from urika.core.criteria import load_criteria

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    c = load_criteria(project_path)

    if json_output:
        from urika.cli_helpers import output_json

        if c is None:
            output_json({"criteria": None})
        else:
            output_json(
                {
                    "criteria": {
                        "version": c.version,
                        "set_by": c.set_by,
                        **c.criteria,
                    }
                }
            )
        return

    if c is None:
        click.echo("  No criteria set.")
        return
    click.echo(f"\n  Criteria v{c.version} (set by {c.set_by})")
    click.echo(f"  Type: {c.criteria.get('type', 'unknown')}")
    threshold = c.criteria.get("threshold", {})
    primary = threshold.get("primary", {})
    if primary:
        click.echo(
            f"  Primary: {primary.get('metric')} "
            f"{primary.get('direction', '>')} {primary.get('target')}"
        )
    click.echo()


# ── Re-exports from sibling modules (Phase 8 split) ───────────────
# Importing these registers their @cli.command decorators and keeps
# the old import path working for callers that do
# ``from urika.cli.agents import report`` etc.
from urika.cli.agents_report import report, _run_report_agent  # noqa: E402, F401
from urika.cli.agents_finalize import finalize  # noqa: E402, F401
from urika.cli.agents_present import present  # noqa: E402, F401
