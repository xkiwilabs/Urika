"""Agent-related CLI commands: advisor, evaluate, plan, report, present, finalize, build-tool, criteria."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click

from urika.cli._base import cli
from urika.core.experiment import list_experiments
from urika.core.progress import load_progress

from urika.cli._helpers import (
    _make_on_message,
    _record_agent_usage,
    _resolve_project,
    _ensure_project,
    _prompt_numbered,
)
from urika.cli.run import _offer_to_run_advisor_suggestions


def _run_report_agent(
    project_path: Path,
    experiment_id: str,
    prompt: str,
    instructions: str = "",
    audience: str = "expert",
) -> str:
    """Run the report agent and return its text output."""
    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
        from urika.cli_display import Spinner, print_agent

        runner = get_runner()
        registry = AgentRegistry()
        registry.discover()

        role = registry.get("report_agent")
        if role is None:
            return ""

        print_agent("report_agent")
        config = role.build_config(
            project_dir=project_path, experiment_id=experiment_id, audience=audience
        )

        if instructions:
            prompt = f"User instructions: {instructions}\n\n{prompt}"

        with Spinner("Writing narrative"):
            result = asyncio.run(
                runner.run(config, prompt, on_message=_make_on_message())
            )

        if result.success and result.text_output:
            return result.text_output.strip()
        return ""
    except ImportError:
        return ""
    except Exception:
        return ""


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Generate report for a specific experiment.",
)
@click.option(
    "--instructions",
    default="",
    help="Guide the report (e.g. 'focus on feature importance findings').",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option(
    "--audience",
    type=click.Choice(["novice", "expert"]),
    default=None,
    help="Output audience level (default: from project config or expert).",
)
def report(
    project: str,
    experiment_id: str | None,
    instructions: str,
    json_output: bool = False,
    audience: str | None = None,
) -> None:
    """Generate labbook reports."""
    from urika.core.labbook import (
        generate_experiment_summary,
        generate_key_findings,
        generate_results_summary,
        update_experiment_notes,
    )

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    # Resolve audience from project config if not explicitly provided
    if audience is None:
        audience = _config.audience

    # If no experiment specified, offer selection (like REPL's _pick_experiment)
    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            # No experiments — fall through to project-level reports
            experiment_id = "project"
        elif json_output:
            # JSON mode: default to most recent experiment
            experiment_id = experiments[-1].experiment_id
        else:
            # Build numbered options — most recent first
            reversed_exps = list(reversed(experiments))
            options = []
            for exp in reversed_exps:
                progress = load_progress(project_path, exp.experiment_id)
                status = progress.get("status", "pending")
                runs = len(progress.get("runs", []))
                options.append(f"{exp.experiment_id} [{status}, {runs} runs]")
            options.append("All experiments (generate for each)")
            options.append("Project level (one overarching report)")

            choice = _prompt_numbered(
                "\nSelect experiment for report:", options, default=1
            )

            if choice.startswith("All"):
                experiment_id = "all"
            elif choice.startswith("Project"):
                experiment_id = "project"
            else:
                experiment_id = choice.split(" [")[0]

    try:
        if experiment_id == "all":
            # Generate reports for each experiment
            for exp in list_experiments(project_path):
                click.echo(f"Processing {exp.experiment_id}...")
                try:
                    update_experiment_notes(project_path, exp.experiment_id)
                    generate_experiment_summary(project_path, exp.experiment_id)
                except FileNotFoundError:
                    pass
                narrative = _run_report_agent(
                    project_path,
                    exp.experiment_id,
                    f"Write a detailed narrative report for experiment {exp.experiment_id}.",
                    instructions=instructions,
                    audience=audience,
                )
                if narrative:
                    from urika.core.report_writer import write_versioned

                    narrative_path = (
                        project_path
                        / "experiments"
                        / exp.experiment_id
                        / "labbook"
                        / "narrative.md"
                    )
                    narrative_path.parent.mkdir(parents=True, exist_ok=True)
                    write_versioned(narrative_path, narrative + "\n")
                    if not json_output:
                        click.echo(f"Generated: {narrative_path}")
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"output": "All experiment reports generated."})
                return
            click.echo("All experiment reports generated.")
            return

        if experiment_id == "project":
            # Project-level reports
            from urika.core.readme_generator import write_readme

            try:
                generate_results_summary(project_path)
                generate_key_findings(project_path)
                write_readme(project_path)
            except FileNotFoundError as exc:
                raise click.ClickException(str(exc))

            # Also refresh notes for all experiments
            for exp in list_experiments(project_path):
                try:
                    update_experiment_notes(project_path, exp.experiment_id)
                except FileNotFoundError:
                    pass

            results_path = project_path / "projectbook" / "results-summary.md"
            findings_path = project_path / "projectbook" / "key-findings.md"
            readme_path = project_path / "README.md"

            # Call report agent for project-level narrative
            narrative = _run_report_agent(
                project_path,
                "",
                "Write a project-level narrative report covering all experiments "
                "and the research progression.",
                instructions=instructions,
                audience=audience,
            )
            if narrative:
                from urika.core.report_writer import write_versioned

                narrative_path = project_path / "projectbook" / "narrative.md"
                narrative_path.parent.mkdir(parents=True, exist_ok=True)
                write_versioned(narrative_path, narrative + "\n")

            if json_output:
                from urika.cli_helpers import output_json

                output_json(
                    {
                        "output": "Project-level reports generated.",
                        "path": str(results_path),
                    }
                )
                return

            click.echo(f"Generated: {results_path}")
            click.echo(f"Generated: {findings_path}")
            click.echo(f"Generated: {readme_path}")
            if narrative:
                click.echo(f"Generated: {narrative_path}")
            return

        # Single experiment report
        try:
            update_experiment_notes(project_path, experiment_id)
            generate_experiment_summary(project_path, experiment_id)
        except FileNotFoundError:
            raise click.ClickException(f"Experiment '{experiment_id}' not found.")
        notes = project_path / "experiments" / experiment_id / "labbook" / "notes.md"
        summary = (
            project_path / "experiments" / experiment_id / "labbook" / "summary.md"
        )

        # Call report agent to write narrative (like REPL)
        narrative = _run_report_agent(
            project_path,
            experiment_id,
            f"Write a detailed narrative report for experiment {experiment_id}.",
            instructions=instructions,
            audience=audience,
        )
        if narrative:
            from urika.core.report_writer import write_versioned

            narrative_path = (
                project_path
                / "experiments"
                / experiment_id
                / "labbook"
                / "narrative.md"
            )
            narrative_path.parent.mkdir(parents=True, exist_ok=True)
            write_versioned(narrative_path, narrative + "\n")

        if json_output:
            from urika.cli_helpers import output_json

            output_json(
                {
                    "output": f"Report generated for {experiment_id}.",
                    "path": str(summary),
                }
            )
            return

        click.echo(f"Updated: {notes}")
        click.echo(f"Generated: {summary}")
        if narrative:
            click.echo(f"Generated: {narrative_path}")
    except KeyboardInterrupt:
        click.echo("\n  Report generation stopped.")
        click.echo("  Re-run with: urika report [--instructions '...']")


@cli.command()
@click.argument("project", required=False, default=None)
@click.argument("text", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def advisor(project: str | None, text: str | None, json_output: bool) -> None:
    """Ask the advisor agent a question about the project."""
    import asyncio
    import time

    from datetime import datetime, timezone

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
        raise click.ClickException(
            "Claude Agent SDK not installed. Run: pip install claude-agent-sdk"
        )

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("advisor_agent")
    if role is None:
        raise click.ClickException("Advisor agent not found.")

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
            f"\n## Research Context (from previous sessions)\n\n"
            f"{context_summary}\n\n"
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

    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()

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
        append_exchange(
            project_path, role="user", text=text, source="cli"
        )

        from urika.orchestrator.parsing import parse_suggestions as _parse_sug

        _parsed = _parse_sug(advisor_text)
        _parsed_suggestions = (
            _parsed["suggestions"]
            if _parsed and _parsed.get("suggestions")
            else None
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
    import asyncio
    import time

    from datetime import datetime, timezone

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
        raise click.ClickException("Claude Agent SDK not installed.")

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("evaluator")
    if role is None:
        raise click.ClickException("Evaluator agent not found.")

    if not json_output:
        print_agent("evaluator")
    config = role.build_config(project_dir=project_path, experiment_id=experiment_id)

    prompt = f"Evaluate experiment {experiment_id}."
    if instructions:
        prompt = f"User instructions: {instructions}\n\n{prompt}"

    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()

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
    import asyncio
    import time

    from datetime import datetime, timezone

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
        raise click.ClickException("Claude Agent SDK not installed.")

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("planning_agent")
    if role is None:
        raise click.ClickException("Planning agent not found.")

    if not json_output:
        print_agent("planning_agent")
    config = role.build_config(project_dir=project_path, experiment_id=experiment_id)

    prompt = "Design the next method based on current results."
    if instructions:
        prompt = f"User instructions: {instructions}\n\n{prompt}"

    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()

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



@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--instructions",
    default="",
    help="Optional instructions for the finalizer agent.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option(
    "--audience",
    type=click.Choice(["novice", "expert"]),
    default=None,
    help="Output audience level (default: from project config or expert).",
)
@click.option(
    "--draft",
    is_flag=True,
    default=False,
    help="Interim summary — outputs to projectbook/draft/, doesn't overwrite final outputs.",
)
def finalize(
    project: str | None,
    instructions: str,
    json_output: bool,
    audience: str | None = None,
    draft: bool = False,
) -> None:
    """Finalize the project — produce polished methods, report, and presentation."""
    import time

    from datetime import datetime, timezone

    from urika.cli_display import (
        ThinkingPanel,
        print_agent,
        print_error,
        print_success,
        print_tool_use,
    )

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    # Resolve audience from project config if not explicitly provided
    if audience is None:
        audience = _config.audience

    from urika.agents.config import load_runtime_config

    _rc = load_runtime_config(project_path)

    try:
        from urika.agents.runner import get_runner
        from urika.orchestrator.finalize import finalize_project
    except ImportError:
        raise click.ClickException("Claude Agent SDK not installed.")

    runner = get_runner()
    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()

    if json_output:

        def _on_progress(event: str, detail: str = "") -> None:
            from urika.cli.run import _update_repl_activity
            _update_repl_activity(event, detail)

        def _on_message(msg: object) -> None:
            pass

        try:
            result = asyncio.run(
                finalize_project(
                    project_path,
                    runner,
                    _on_progress,
                    _on_message,
                    instructions=instructions,
                    audience=audience,
                    draft=draft,
                )
            )
        except KeyboardInterrupt:
            click.echo("\n  Finalize stopped.")
            if instructions:
                click.echo("  Re-run with: urika finalize --instructions '...'")
            return
    else:
        panel = ThinkingPanel()
        panel.project = f"{project} · {_rc.privacy_mode}"
        panel._project_dir = project_path
        panel.activity = "Draft summary..." if draft else "Finalizing..."
        panel.activate()
        panel.start_spinner()

        def _on_progress(event: str, detail: str = "") -> None:
            from urika.cli.run import _update_repl_activity
            _update_repl_activity(event, detail)
            if event == "agent":
                agent_key = detail.split("\u2014")[0].strip().lower().replace(" ", "_")
                print_agent(agent_key)
                panel.update(agent=agent_key, activity=detail)
            elif event == "result":
                print_success(detail)

        def _on_message(msg: object) -> None:
            try:
                model = getattr(msg, "model", None)
                if model:
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
                            panel.set_thinking(tool_name)
                        else:
                            panel.set_thinking("Thinking\u2026")
            except Exception:
                pass

        try:
            result = asyncio.run(
                finalize_project(
                    project_path,
                    runner,
                    _on_progress,
                    _on_message,
                    instructions=instructions,
                    audience=audience,
                    draft=draft,
                )
            )
        except KeyboardInterrupt:
            panel.cleanup()
            click.echo("\n  Finalize stopped.")
            click.echo("  Re-run with: urika finalize [--instructions '...']")
            return
        finally:
            panel.cleanup()

    # Record finalize usage
    try:
        from urika.core.usage import record_session

        _elapsed_ms = int(time.monotonic() * 1000) - _start_ms
        record_session(
            project_path,
            started=_start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=_elapsed_ms,
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
            cost_usd=result.get("cost_usd", 0.0),
            agent_calls=result.get("agent_calls", 0),
            experiments_run=0,
        )
    except Exception:
        pass

    if json_output:
        from urika.cli_helpers import output_json

        output_json(result)
        return

    if result.get("success"):
        if draft:
            draft_dir = project_path / "projectbook" / "draft"
            print_success("Draft summary saved to projectbook/draft/")
            click.echo(f"  Findings:      {draft_dir / 'findings.json'}")
            click.echo(f"  Report:        {draft_dir / 'report.md'}")
            click.echo(
                f"  Presentation:  {draft_dir / 'presentation' / 'index.html'}"
            )
        else:
            print_success("Project finalized!")
            click.echo(f"  Methods:       {project_path / 'methods/'}")
            click.echo(
                f"  Final report:  {project_path / 'projectbook' / 'final-report.md'}"
            )
            click.echo(
                f"  Presentation:  "
                f"{project_path / 'projectbook' / 'final-presentation' / 'index.html'}"
            )
            click.echo(f"  Reproduce:     {project_path / 'reproduce.sh'}")
    else:
        print_error(f"Finalization failed: {result.get('error', 'unknown')}")



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
    import asyncio
    import time

    from datetime import datetime, timezone

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
        raise click.ClickException("Claude Agent SDK not installed.")

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("tool_builder")
    if role is None:
        raise click.ClickException("Tool builder agent not found.")

    if not json_output:
        print_agent("tool_builder")
    config = role.build_config(project_dir=project_path)

    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()

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
    default="",
    help="Guide the presentation (e.g. 'emphasize ensemble results').",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option(
    "--audience",
    type=click.Choice(["novice", "expert"]),
    default=None,
    help="Output audience level (default: from project config or expert).",
)
def present(
    project: str | None, instructions: str, json_output: bool, audience: str | None = None
) -> None:
    """Generate a presentation for an experiment."""
    import asyncio
    import time

    from datetime import datetime, timezone

    from urika.cli_display import Spinner, print_agent, print_success

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    # Resolve audience from project config if not explicitly provided
    if audience is None:
        audience = _config.audience

    experiments = list_experiments(project_path)
    if not experiments:
        raise click.ClickException("No experiments.")

    try:
        from urika.agents.runner import get_runner
        from urika.orchestrator.loop import _generate_presentation, _noop_callback
    except ImportError:
        raise click.ClickException("Claude Agent SDK not installed.")

    runner = get_runner()
    on_msg = (lambda m: None) if json_output else _make_on_message()

    if json_output:
        # JSON mode: default to most recent experiment, no interactive prompt
        choice = f"{experiments[-1].experiment_id} [auto]"
    else:
        # Build options — most recent first, plus all/project choices
        reversed_exps = list(reversed(experiments))
        options = []
        for exp in reversed_exps:
            progress = load_progress(project_path, exp.experiment_id)
            exp_status = progress.get("status", "pending")
            runs = len(progress.get("runs", []))
            options.append(f"{exp.experiment_id} [{exp_status}, {runs} runs]")
        options.append("All experiments (generate for each)")
        options.append("Project level (one overarching presentation)")

        choice = _prompt_numbered("\n  Select:", options, default=1)

    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()
    _pres_tokens_in = 0
    _pres_tokens_out = 0
    _pres_cost = 0.0
    _pres_calls = 0

    try:
        if choice.startswith("All"):
            # Generate presentation for each experiment
            for exp in experiments:
                if not json_output:
                    print_agent("presentation_agent")
                with Spinner("Creating slides"):
                    _pu = asyncio.run(
                        _generate_presentation(
                            project_path,
                            exp.experiment_id,
                            runner,
                            _noop_callback,
                            on_message=on_msg,
                            instructions=instructions,
                            audience=audience,
                        )
                    )
                    _pres_tokens_in += _pu.get("tokens_in", 0)
                    _pres_tokens_out += _pu.get("tokens_out", 0)
                    _pres_cost += _pu.get("cost_usd", 0.0)
                    _pres_calls += _pu.get("agent_calls", 0)
                if not json_output:
                    print_success(
                        f"Saved to experiments/{exp.experiment_id}/presentation/index.html"
                    )
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"path": str(project_path / "experiments")})
                return
            print_success("All presentations generated")
        elif choice.startswith("Project"):
            # Project-level presentation
            if not json_output:
                print_agent("presentation_agent")
            with Spinner("Creating slides"):
                _pu = asyncio.run(
                    _generate_presentation(
                        project_path,
                        "",
                        runner,
                        _noop_callback,
                        on_message=on_msg,
                        instructions=instructions,
                        audience=audience,
                    )
                )
                _pres_tokens_in += _pu.get("tokens_in", 0)
                _pres_tokens_out += _pu.get("tokens_out", 0)
                _pres_cost += _pu.get("cost_usd", 0.0)
                _pres_calls += _pu.get("agent_calls", 0)
            pres_path = project_path / "projectbook" / "presentation" / "index.html"
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"path": str(pres_path)})
                return
            print_success("Saved to projectbook/presentation/index.html")
        else:
            # Single experiment
            exp_id = choice.split(" [")[0]
            if not json_output:
                print_agent("presentation_agent")
            with Spinner("Creating slides"):
                _pu = asyncio.run(
                    _generate_presentation(
                        project_path,
                        exp_id,
                        runner,
                        _noop_callback,
                        on_message=on_msg,
                        instructions=instructions,
                        audience=audience,
                    )
                )
                _pres_tokens_in += _pu.get("tokens_in", 0)
                _pres_tokens_out += _pu.get("tokens_out", 0)
                _pres_cost += _pu.get("cost_usd", 0.0)
                _pres_calls += _pu.get("agent_calls", 0)
            pres_path = (
                project_path / "experiments" / exp_id / "presentation" / "index.html"
            )
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"path": str(pres_path)})
                return
            print_success(f"Saved to experiments/{exp_id}/presentation/index.html")
    except KeyboardInterrupt:
        click.echo("\n  Presentation stopped.")
        click.echo("  Re-run with: urika present [--instructions '...']")

    # Record presentation usage
    try:
        from urika.core.usage import record_session

        _elapsed_ms = int(time.monotonic() * 1000) - _start_ms
        record_session(
            project_path,
            started=_start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=_elapsed_ms,
            tokens_in=_pres_tokens_in,
            tokens_out=_pres_tokens_out,
            cost_usd=_pres_cost,
            agent_calls=_pres_calls,
            experiments_run=0,
        )
    except Exception:
        pass



@cli.command()
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def summarize(project: str | None, json_output: bool) -> None:
    """Summarize the current state of a project."""
    import asyncio
    import time

    from datetime import datetime, timezone

    from urika.cli_display import Spinner, format_agent_output, print_agent

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
    except ImportError:
        raise click.ClickException(
            "Claude Agent SDK not installed. Run: pip install claude-agent-sdk"
        )

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("project_summarizer")
    if role is None:
        raise click.ClickException("Project summarizer agent not found.")

    if not json_output:
        print_agent("project_summarizer")
    config = role.build_config(project_dir=project_path)

    prompt = "Summarize the current state of this project."

    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()

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


