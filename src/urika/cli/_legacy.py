"""Urika CLI."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import re

import click

from urika.core.experiment import create_experiment, list_experiments
from urika.core.models import ProjectConfig
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry
from urika.core.workspace import load_project_config
from urika.evaluation.leaderboard import load_leaderboard
from urika.tools import ToolRegistry


from urika.cli._helpers import (
    _make_on_message,
    _record_agent_usage,
    _sanitize_project_name,
    _projects_dir,
    _resolve_project,
    _ensure_project,
    _test_endpoint,
    _prompt_numbered,
    _prompt_path,
)

class _UrikaCLI(click.Group):
    """Custom CLI group that catches UserCancelled globally."""

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except SystemExit:
            raise  # Let clean exits through
        except Exception as exc:
            # Catch UserCancelled from any command — exit cleanly
            if type(exc).__name__ == "UserCancelled":
                raise SystemExit(0)
            raise


@click.group(cls=_UrikaCLI, invoke_without_command=True)
@click.version_option(package_name="urika")
@click.pass_context
def cli(ctx) -> None:
    """Urika: Agentic scientific analysis platform."""
    # Load credentials from ~/.urika/secrets.env
    from urika.core.secrets import load_secrets

    load_secrets()

    # Check for updates on every CLI invocation (cached, non-blocking)
    try:
        from urika.core.updates import (
            check_for_updates,
            format_update_message,
        )

        update_info = check_for_updates()
        if update_info:
            from urika.cli_display import _C

            msg = format_update_message(update_info)
            click.echo(f"{_C.DIM}  ↑ {msg}{_C.RESET}")
    except Exception:
        pass

    if ctx.invoked_subcommand is None:
        from urika.repl import run_repl

        run_repl()


@cli.group()
def experiment() -> None:
    """Manage experiments within a project."""


@experiment.command("create")
@click.argument("project", required=False, default=None)
@click.argument("name")
@click.option("--hypothesis", default="", help="Experiment hypothesis.")
def experiment_create(project: str, name: str, hypothesis: str) -> None:
    """Create a new experiment in a project."""
    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    exp = create_experiment(project_path, name=name, hypothesis=hypothesis)
    click.echo(f"{exp.experiment_id}")


@experiment.command("list")
@click.argument("project", required=False, default=None)
def experiment_list(project: str) -> None:
    """List experiments in a project."""
    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    experiments = list_experiments(project_path)

    if not experiments:
        click.echo("No experiments yet.")
        return

    for exp in experiments:
        progress = load_progress(project_path, exp.experiment_id)
        n_runs = len(progress.get("runs", []))
        exp_status = progress.get("status", "unknown")
        click.echo(f"  {exp.experiment_id}  {exp.name}  [{exp_status}, {n_runs} runs]")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Show runs for a specific experiment.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def results(project: str, experiment_id: str | None, json_output: bool) -> None:
    """Show project results (leaderboard or experiment runs)."""
    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if experiment_id is not None:
        progress = load_progress(project_path, experiment_id)
        runs = progress.get("runs", [])
        if json_output:
            from urika.cli_helpers import output_json

            output_json({"runs": runs})
            return
        if not runs:
            click.echo("No results yet.")
            return
        for run in runs:
            metrics_str = ", ".join(
                f"{k}={v}" for k, v in run.get("metrics", {}).items()
            )
            click.echo(f"  {run['run_id']}  {run['method']}  {metrics_str}")
        return

    leaderboard = load_leaderboard(project_path)
    ranking = leaderboard.get("ranking", [])

    if json_output:
        from urika.cli_helpers import output_json

        output_json({"ranking": ranking})
        return

    if not ranking:
        click.echo("No results yet.")
        return

    for entry in ranking:
        metrics_str = ", ".join(f"{k}={v}" for k, v in entry.get("metrics", {}).items())
        click.echo(f"  #{entry['rank']}  {entry['method']}  {metrics_str}")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def methods(project: str, json_output: bool) -> None:
    """List agent-created methods in a project."""
    from urika.core.method_registry import load_methods

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    method_list = load_methods(project_path)

    if json_output:
        from urika.cli_helpers import output_json

        output_json({"methods": method_list})
        return

    if not method_list:
        click.echo("No methods created yet.")
        return

    for m in method_list:
        metrics = m.get("metrics", {})
        nums = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
        metric_str = ", ".join(f"{k}={v}" for k, v in list(nums.items())[:2])
        click.echo(f"  {m['name']}  [{m.get('status', '')}]  {metric_str}")


@cli.command()
@click.option("--category", default=None, help="Filter by category.")
@click.option("--project", default=None, help="Include project-specific tools.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def tools(category: str | None, project: str | None, json_output: bool) -> None:
    """List available analysis tools."""
    registry = ToolRegistry()
    registry.discover()

    if project is not None:
        project_path, _config = _resolve_project(project)
        registry.discover_project(project_path / "tools")

    if category is not None:
        names = registry.list_by_category(category)
    else:
        names = registry.list_all()

    if json_output:
        from urika.cli_helpers import output_json

        tools_data = []
        for name in names:
            tool = registry.get(name)
            if tool is not None:
                tools_data.append(
                    {
                        "name": tool.name(),
                        "category": tool.category(),
                        "description": tool.description(),
                    }
                )
        output_json({"tools": tools_data})
        return

    if not names:
        click.echo("No tools found.")
        return

    for name in names:
        tool = registry.get(name)
        if tool is not None:
            click.echo(f"  {tool.name()}  [{tool.category()}]  {tool.description()}")


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
@click.option(
    "--experiment", "experiment_id", default=None, help="Specific experiment."
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def logs(project: str, experiment_id: str | None, json_output: bool) -> None:
    """Show experiment run log."""
    from urika.core.session import load_session

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            raise click.ClickException("No experiments in this project.")
        if len(experiments) == 1:
            experiment_id = experiments[0].experiment_id
        else:
            if json_output:
                # Default to most recent experiment for JSON mode
                experiment_id = experiments[-1].experiment_id
            else:
                # Offer selection when multiple experiments exist
                reversed_exps = list(reversed(experiments))
                options = []
                for exp in reversed_exps:
                    progress_data = load_progress(project_path, exp.experiment_id)
                    status = progress_data.get("status", "pending")
                    runs = len(progress_data.get("runs", []))
                    options.append(f"{exp.experiment_id} [{status}, {runs} runs]")
                choice = _prompt_numbered(
                    "\nSelect experiment to view logs:", options, default=1
                )
                experiment_id = choice.split(" [")[0]

    progress = load_progress(project_path, experiment_id)
    session = load_session(project_path, experiment_id)

    if json_output:
        from urika.cli_helpers import output_json

        runs = progress.get("runs", [])
        data = {
            "experiment_id": experiment_id,
            "runs": runs,
        }
        if session is not None:
            data["status"] = session.status
            data["turns"] = session.current_turn
        output_json(data)
        return

    click.echo(f"Experiment: {experiment_id}")
    if session is not None:
        click.echo(f"Status: {session.status}")
        click.echo(f"Turns: {session.current_turn}")
    click.echo("")

    runs = progress.get("runs", [])
    if not runs:
        click.echo("No runs recorded yet.")
        return

    for run in runs:
        metrics_str = ", ".join(f"{k}={v}" for k, v in run.get("metrics", {}).items())
        click.echo(f"  {run['run_id']}  {run['method']}  {metrics_str}")
        if run.get("hypothesis"):
            click.echo(f"    Hypothesis: {run['hypothesis']}")
        if run.get("observation"):
            click.echo(f"    Observation: {run['observation']}")
        if run.get("next_step"):
            click.echo(f"    Next step: {run['next_step']}")
        click.echo("")


@cli.group()
def knowledge() -> None:
    """Manage project knowledge base."""


@knowledge.command("ingest")
@click.argument("project", required=False, default=None)
@click.argument("source")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def knowledge_ingest(project: str, source: str, json_output: bool) -> None:
    """Ingest a file or URL into the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    try:
        entry = store.ingest(source)
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc))

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"id": entry.id, "title": entry.title, "source_type": entry.source_type}
        )
        return

    click.echo(f'Ingested: {entry.id} "{entry.title}" ({entry.source_type})')


@knowledge.command("search")
@click.argument("project", required=False, default=None)
@click.argument("query")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def knowledge_search(project: str, query: str, json_output: bool) -> None:
    """Search the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    results_list = store.search(query)

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {
                "results": [
                    {
                        "id": e.id,
                        "title": e.title,
                        "source_type": e.source_type,
                        "snippet": e.content[:200],
                    }
                    for e in results_list
                ]
            }
        )
        return

    if not results_list:
        click.echo("No results found.")
        return

    for entry in results_list:
        snippet = entry.content[:100].replace("\n", " ")
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]  {snippet}")


@knowledge.command("list")
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def knowledge_list(project: str, json_output: bool) -> None:
    """List all knowledge entries."""
    from urika.knowledge import KnowledgeStore

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    entries = store.list_all()

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {
                "entries": [
                    {"id": e.id, "title": e.title, "source_type": e.source_type}
                    for e in entries
                ]
            }
        )
        return

    if not entries:
        click.echo("No knowledge entries yet.")
        return

    for entry in entries:
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]")


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
            pass

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


@cli.command()
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def usage(project: str | None, json_output: bool) -> None:
    """Show usage stats for a project."""
    from urika.core.usage import format_usage, get_last_session, get_totals

    if project:
        project = _ensure_project(project)
        project_path, _config = _resolve_project(project)
        last = get_last_session(project_path)
        totals = get_totals(project_path)

        if json_output:
            from urika.cli_helpers import output_json

            output_json({"session": last or {}, "total": totals})
            return

        click.echo(f"\n  Usage: {project}")
        click.echo(format_usage(last, totals))
    else:
        # All projects
        registry_obj = ProjectRegistry()
        projects = registry_obj.list_all()

        if json_output:
            from urika.cli_helpers import output_json

            all_usage = {}
            for name, path in projects.items():
                all_usage[name] = get_totals(path)
            output_json({"projects": all_usage})
            return

        if not projects:
            click.echo("  No projects.")
            return
        click.echo("\n  Usage across all projects:")
        for name, path in projects.items():
            totals = get_totals(path)
            if totals.get("sessions", 0) > 0:
                tokens = totals.get("total_tokens_in", 0) + totals.get(
                    "total_tokens_out", 0
                )
                tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
                click.echo(
                    f"  {name}: {totals['sessions']} sessions · "
                    f"{tok_str} tokens · ~${totals['total_cost_usd']:.2f}"
                )
    click.echo()


@cli.command("dashboard")
@click.argument("project", required=False, default=None)
@click.option("--port", default=8420, type=int, help="Server port (default: 8420)")
def dashboard(project: str | None, port: int) -> None:
    """Open the project dashboard in your browser."""
    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    click.echo(f"\n  Starting dashboard for {_config.name}...")

    from urika.dashboard.server import start_dashboard

    try:
        start_dashboard(project_path, port=port)
    except KeyboardInterrupt:
        pass

    click.echo("  Dashboard stopped.")


@cli.command("config")
@click.argument("project", required=False, default=None)
@click.option("--show", is_flag=True, help="Show current settings.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def config_command(
    project: str | None,
    show: bool,
    json_output: bool,
) -> None:
    """View or configure privacy mode and models.

    Without PROJECT, configures global defaults (~/.urika/settings.toml).
    With PROJECT, configures that project's urika.toml.

    Examples:

        urika config --show              # show global defaults
        urika config                     # interactive setup (global)
        urika config my-project --show   # show project settings
        urika config my-project          # interactive setup (project)
    """
    from urika.cli_display import print_step
    from urika.cli_helpers import UserCancelled

    # ── Determine target: global or project ──
    is_project = False
    project_path = None
    if project is not None:
        is_project = True
        try:
            project_path, _config = _resolve_project(project)
        except click.ClickException:
            raise

    # ── Load current settings ──
    if is_project:
        import tomllib

        toml_path = project_path / "urika.toml"
        with open(toml_path, "rb") as f:
            settings = tomllib.load(f)
    else:
        from urika.core.settings import load_settings

        settings = load_settings()

    # ── Show mode ──
    if show:
        if json_output:
            from urika.cli_helpers import output_json

            output_json(settings)
            return

        label = f"Project: {project}" if is_project else "Global defaults"
        click.echo(f"\n  {label}\n")
        p = settings.get("privacy", {})
        r = settings.get("runtime", {})
        mode = p.get("mode", "open")
        print_step(f"Privacy mode: {mode}")
        eps = p.get("endpoints", {})
        for ep_name, ep in eps.items():
            if isinstance(ep, dict):
                url = ep.get("base_url", "")
                key = ep.get("api_key_env", "")
                label_ep = f"  {ep_name}: {url}"
                if key:
                    label_ep += f" (key: ${key})"
                print_step(label_ep)
        if r.get("model"):
            print_step(f"Default model: {r['model']}")
        models = r.get("models", {})
        for agent_name, agent_cfg in models.items():
            if isinstance(agent_cfg, dict):
                m = agent_cfg.get("model", "")
                ep = agent_cfg.get("endpoint", "open")
                print_step(f"  {agent_name}: {m} (endpoint: {ep})")
            elif isinstance(agent_cfg, str):
                print_step(f"  {agent_name}: {agent_cfg}")
        click.echo()
        return

    # ── Interactive setup ──
    current_mode = settings.get("privacy", {}).get("mode", "open")
    click.echo(f"\n  Current privacy mode: {current_mode}\n")

    try:
        _config_interactive(
            session=settings,
            current_mode=current_mode,
            is_project=is_project,
            project_path=project_path,
        )
    except UserCancelled:
        click.echo("\n  Cancelled.")
        return


def _config_interactive(*, session, current_mode, is_project, project_path):
    """Interactive config setup. Raises UserCancelled on cancel/ESC."""
    import click
    from urika.cli_display import print_step, print_success, print_warning
    from urika.cli_helpers import (
        interactive_confirm,
        interactive_numbered,
        interactive_prompt,
    )

    _CLOUD_MODELS = [
        ("claude-sonnet-4-5", "Best balance of speed and quality (recommended)"),
        ("claude-opus-4-6", "Most capable, slower, higher cost"),
        ("claude-haiku-4-5", "Fastest, lowest cost, less capable"),
    ]

    settings = session

    mode = interactive_numbered(
        "  Privacy mode:",
        [
            "open — all agents use Claude API (cloud models only)",
            "private — all agents use local/server models (nothing leaves your network)",
            "hybrid — most agents use Claude API, data agents use local models",
        ],
        default={"open": 1, "private": 2, "hybrid": 3}.get(current_mode, 1),
    )
    mode = mode.split(" —")[0].strip()

    # Warn if changing from private/hybrid to less private
    if current_mode == "private" and mode in ("open", "hybrid"):
        print_warning(
            f"Changing from private to {mode} — agents will send data to cloud APIs."
        )
        if not interactive_confirm("  Continue?", default=False):
            click.echo("  Cancelled.")
            return
    elif current_mode == "hybrid" and mode == "open":
        print_warning(
            "Changing from hybrid to open — "
            "ALL agents (including data agent) will use cloud APIs."
        )
        if not interactive_confirm("  Continue?", default=False):
            click.echo("  Cancelled.")
            return

    settings.setdefault("privacy", {})["mode"] = mode

    # ── Open mode: pick cloud model ──
    if mode == "open":
        click.echo()
        options = [f"{m} — {desc}" for m, desc in _CLOUD_MODELS]
        choice = interactive_numbered(
            "  Default model for all agents:",
            options,
            default=1,
        )
        model_name = choice.split(" —")[0].strip()
        settings.setdefault("runtime", {})["model"] = model_name
        # Clear any private endpoints
        settings.get("privacy", {}).pop("endpoints", None)
        print_success(f"Mode: open · Model: {model_name}")

    # ── Private mode: configure endpoint + model ──
    elif mode == "private":
        click.echo()
        ep_type = interactive_numbered(
            "  Private endpoint type:",
            [
                "Ollama (localhost:11434)",
                "LM Studio (localhost:1234)",
                "vLLM / LiteLLM server (network)",
                "Custom server URL",
            ],
            default=1,
        )
        if ep_type.startswith("Ollama"):
            ep_url = "http://localhost:11434"
        elif ep_type.startswith("LM Studio"):
            ep_url = "http://localhost:1234"
        elif ep_type.startswith("vLLM"):
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt(
                "  Server URL without /v1 (e.g. http://192.168.1.100:4200)"
            )
        else:
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt("  Server URL")

        p = settings.setdefault("privacy", {})
        ep = p.setdefault("endpoints", {}).setdefault("private", {})
        ep["base_url"] = ep_url

        # API key only for remote servers (not needed for Ollama/LM Studio)
        if "localhost" not in ep_url and "127.0.0.1" not in ep_url:
            from urika.cli_helpers import interactive_prompt

            key_env = interactive_prompt(
                "  API key env var NAME, not the key itself (e.g. INFERENCE_HUB_KEY)",
                default="",
            )
            if key_env:
                ep["api_key_env"] = key_env

        from urika.cli_helpers import interactive_prompt
        from urika.core.settings import load_settings

        global_settings = load_settings()
        global_model = global_settings.get("runtime", {}).get("model", "")

        model_name = interactive_prompt(
            "  Model name" + (f" [{global_model}]" if global_model else " (e.g. qwen3:14b)"),
            default=global_model if global_model else "",
            required=True,
        )
        settings.setdefault("runtime", {})["model"] = model_name
        print_success(f"Mode: private · Endpoint: {ep_url} · Model: {model_name}")

    # ── Hybrid mode: cloud model + private endpoint for data agents ──
    elif mode == "hybrid":
        # Cloud model for most agents
        click.echo()
        options = [f"{m} — {desc}" for m, desc in _CLOUD_MODELS]
        choice = interactive_numbered(
            "  Cloud model for most agents:",
            options,
            default=1,
        )
        cloud_model = choice.split(" —")[0].strip()
        settings.setdefault("runtime", {})["model"] = cloud_model

        # Private endpoint for data agents
        click.echo()
        click.echo("  Data Agent and Tool Builder must use a private model.")
        ep_type = interactive_numbered(
            "  Private endpoint type:",
            [
                "Ollama (localhost:11434)",
                "LM Studio (localhost:1234)",
                "vLLM / LiteLLM server (network)",
                "Custom server URL",
            ],
            default=1,
        )
        if ep_type.startswith("Ollama"):
            ep_url = "http://localhost:11434"
        elif ep_type.startswith("LM Studio"):
            ep_url = "http://localhost:1234"
        elif ep_type.startswith("vLLM"):
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt(
                "  Server URL without /v1 (e.g. http://192.168.1.100:4200)"
            )
        else:
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt("  Server URL")

        p = settings.setdefault("privacy", {})
        ep = p.setdefault("endpoints", {}).setdefault("private", {})
        ep["base_url"] = ep_url

        if "localhost" not in ep_url and "127.0.0.1" not in ep_url:
            from urika.cli_helpers import interactive_prompt

            key_env = interactive_prompt(
                "  API key environment variable name",
                default="",
            )
            if key_env:
                ep["api_key_env"] = key_env

        from urika.cli_helpers import interactive_prompt
        from urika.core.settings import load_settings

        # Default from global settings if configured
        global_settings = load_settings()
        global_data_model = (
            global_settings.get("runtime", {})
            .get("models", {})
            .get("data_agent", {})
            .get("model", "")
        )

        private_model = interactive_prompt(
            "  Private model for data agents"
            + (f" [{global_data_model}]" if global_data_model else " (e.g. qwen3:14b)"),
            default=global_data_model if global_data_model else "",
            required=True,
        )

        # Set per-agent overrides
        models = settings.setdefault("runtime", {}).setdefault("models", {})
        models["data_agent"] = {"model": private_model, "endpoint": "private"}
        # tool_builder uses cloud by default in hybrid (doesn't touch raw data)

        print_success(
            f"Mode: hybrid · Cloud: {cloud_model} · "
            f"Data agents: {private_model} via {ep_url}"
        )

    # ── Save ──
    if is_project:
        from urika.core.workspace import _write_toml

        _write_toml(project_path / "urika.toml", settings)
        print_step(f"Saved to {project_path / 'urika.toml'}")
    else:
        from urika.core.settings import save_settings

        save_settings(settings)
        from urika.core.settings import _settings_path

        print_step(f"Saved to {_settings_path()}")

    click.echo()
    click.echo(
        "  Tip: for per-agent model overrides, edit the [runtime.models] "
        "section in urika.toml directly."
    )
    click.echo()


@cli.command("notifications")
@click.option("--show", is_flag=True, help="Show current notification config.")
@click.option("--test", "send_test", is_flag=True, help="Send a test notification.")
@click.option("--disable", is_flag=True, help="Disable all notifications.")
@click.option("--project", default=None, help="Configure for a specific project.")
def notifications_command(
    show: bool,
    send_test: bool,
    disable: bool,
    project: str | None,
) -> None:
    """Configure notification channels (email, Slack, Telegram).

    Examples:

        urika notifications              # interactive setup (global)
        urika notifications --show       # show current config
        urika notifications --test       # send test notification
        urika notifications --disable    # disable notifications
        urika notifications --project X  # configure for project X
    """
    from urika.cli_display import print_success
    from urika.cli_helpers import UserCancelled

    # ── Determine target: global or project ──
    is_project = False
    project_path = None
    if project is not None:
        is_project = True
        try:
            project_path, _config = _resolve_project(project)
        except click.ClickException:
            raise

    # ── Load current settings ──
    if is_project:
        import tomllib

        toml_path = project_path / "urika.toml"
        with open(toml_path, "rb") as f:
            settings = tomllib.load(f)
    else:
        from urika.core.settings import load_settings

        settings = load_settings()

    notif = settings.get("notifications", {})

    # ── Disable mode (project-level only) ──
    if disable:
        if not is_project:
            click.echo("  Disable is a project-level setting. Use: urika notifications --disable --project <name>")
            return
        settings.setdefault("notifications", {})["channels"] = []
        _save_notification_settings(settings, is_project, project_path)
        print_success("Notifications disabled for this project.")
        return

    # ── Show mode ──
    if show:
        if is_project:
            # Show merged config (global defaults + project overrides)
            from urika.notifications import _load_notification_config

            merged = _load_notification_config(project_path)
            channels_list = settings.get("notifications", {}).get("channels", [])
            click.echo(f"\n  Project: {project}")
            if channels_list:
                click.echo(f"  Enabled channels: {', '.join(channels_list)}")
            else:
                click.echo("  No channels enabled for this project.")
            # Show the merged channel details from global + project config
            _show_notification_config(merged)
        else:
            _show_notification_config(notif)
        return

    # ── Test mode ──
    if send_test:
        _send_test_notification(notif, project_path=project_path)
        return

    # ── Interactive setup ──
    try:
        _notifications_interactive(
            settings=settings,
            is_project=is_project,
            project_path=project_path,
        )
    except UserCancelled:
        click.echo("\n  Cancelled.")


def _show_notification_config(notif: dict) -> None:
    """Display current notification config with masked credentials."""
    from urika.cli_display import print_step
    from urika.core.secrets import list_secrets

    # "enabled" is a project-level setting; global config just stores channel details
    has_channels = any(
        notif.get(ch, {}).get(key)
        for ch, key in [("email", "to"), ("slack", "channel"), ("telegram", "chat_id")]
    )
    status = "configured" if has_channels else "not configured"
    click.echo(f"\n  Notifications: {status}\n")

    # Email
    email = notif.get("email", {})
    if email.get("to"):
        to_addrs = email["to"] if isinstance(email["to"], list) else [email["to"]]
        from_addr = email.get("from_addr", "")
        server = email.get("smtp_server", "smtp.gmail.com")
        port = email.get("smtp_port", 587)
        print_step(f"Email: {from_addr} -> {', '.join(to_addrs)} (via {server}:{port})")
    else:
        print_step("Email: not configured")

    # Slack
    slack = notif.get("slack", {})
    if slack.get("channel"):
        print_step(f"Slack: {slack['channel']} (configured)")
    else:
        print_step("Slack: not configured")

    # Telegram
    telegram = notif.get("telegram", {})
    if telegram.get("chat_id"):
        print_step(f"Telegram: chat {telegram['chat_id']} (configured)")
    else:
        print_step("Telegram: not configured")

    # Show stored secrets (masked)
    secrets = list_secrets()
    notif_keys = [
        k
        for k in secrets
        if k
        in (
            "URIKA_EMAIL_PASSWORD",
            "SLACK_BOT_TOKEN",
            "SLACK_APP_TOKEN",
            "TELEGRAM_BOT_TOKEN",
        )
    ]
    if notif_keys:
        click.echo()
        print_step("Stored credentials:")
        for k in notif_keys:
            print_step(f"  {k}: ****")

    click.echo()


def _send_test_notification(notif: dict, project_path: Path | None = None) -> None:
    """Send a test notification through all configured channels."""
    from urika.cli_display import print_error, print_success, print_warning
    from urika.notifications.events import NotificationEvent

    # Use build_bus for proper global+project config resolution
    if project_path is not None:
        from urika.notifications import build_bus

        bus = build_bus(project_path)
        if bus is None:
            print_warning("No notification channels enabled for this project.")
            return

        event = NotificationEvent(
            event_type="test",
            project_name=project_path.name,
            summary="Test notification from Urika",
            priority="medium",
        )
        for ch in bus.channels:
            try:
                ch.send(event)
                print_success(f"Test sent via {type(ch).__name__}")
            except Exception as exc:
                print_error(f"{type(ch).__name__} failed: {exc}")
        return

    # Global test (no project) — test each channel from raw config
    event = NotificationEvent(
        event_type="test",
        project_name="test",
        summary="Test notification from Urika",
        priority="medium",
    )

    sent = False

    # Test email
    email_cfg = notif.get("email", {})
    if email_cfg.get("to"):
        try:
            from urika.notifications.email_channel import EmailChannel

            ch = EmailChannel(email_cfg)
            ch.send(event)
            to_addrs = email_cfg["to"]
            if isinstance(to_addrs, list):
                to_addrs = ", ".join(to_addrs)
            print_success(f"Test email sent to {to_addrs}")
            sent = True
        except Exception as exc:
            print_error(f"Email failed: {exc}")

    # Test Slack
    slack_cfg = notif.get("slack", {})
    if slack_cfg.get("channel"):
        try:
            from urika.notifications.slack_channel import SlackChannel

            ch = SlackChannel(slack_cfg)
            ch.send(event)
            print_success(f"Test Slack message sent to {slack_cfg['channel']}")
            sent = True
        except ImportError:
            print_warning("slack-sdk not installed: pip install slack-sdk")
        except Exception as exc:
            print_error(f"Slack failed: {exc}")

    # Test Telegram
    telegram_cfg = notif.get("telegram", {})
    if telegram_cfg.get("chat_id"):
        try:
            from urika.notifications.telegram_channel import TelegramChannel

            ch = TelegramChannel(telegram_cfg)
            ch.send(event)
            print_success(
                f"Test Telegram message sent to chat {telegram_cfg['chat_id']}"
            )
            sent = True
        except ImportError:
            print_warning(
                "python-telegram-bot not installed: pip install python-telegram-bot"
            )
        except Exception as exc:
            print_error(f"Telegram failed: {exc}")

    if not sent:
        print_warning("No channels configured. Run: urika notifications")


def _notifications_interactive(*, settings, is_project, project_path):
    """Interactive notification setup. Raises UserCancelled on cancel/ESC."""
    if is_project:
        _notifications_project_setup(settings=settings, project_path=project_path)
        return

    _notifications_global_setup(settings=settings, project_path=project_path)


def _notifications_project_setup(*, settings, project_path):
    """Project-level notification setup — select channels + extra recipients."""
    import click
    import tomllib
    from urika.cli_display import print_step, print_success, print_warning
    from urika.cli_helpers import interactive_confirm, interactive_prompt

    # Load global config to show what's available
    global_notif: dict = {}
    global_path = Path.home() / ".urika" / "settings.toml"
    if global_path.exists():
        try:
            with open(global_path, "rb") as f:
                data = tomllib.load(f)
            global_notif = data.get("notifications", {})
        except Exception:
            pass

    # Check what's configured globally
    has_email = bool(global_notif.get("email", {}).get("to"))
    has_slack = bool(global_notif.get("slack", {}).get("channel"))
    has_telegram = bool(global_notif.get("telegram", {}).get("chat_id"))

    if not has_email and not has_slack and not has_telegram:
        print_warning(
            "No notification channels configured globally.\n"
            "  Run 'urika notifications' (without --project) to set up channels first."
        )
        return

    click.echo("\n  Project notification setup\n")

    # Show available global channels
    click.echo("  Available channels (from global settings):")
    if has_email:
        to = global_notif["email"]["to"]
        if isinstance(to, list):
            to = ", ".join(to)
        click.echo(
            f"    Email:    {global_notif['email'].get('from_addr', '?')} -> {to}"
        )
    if has_slack:
        click.echo(f"    Slack:    {global_notif['slack']['channel']}")
    if has_telegram:
        click.echo(f"    Telegram: chat {global_notif['telegram']['chat_id']}")
    click.echo()

    # Ask which channels to enable
    channels = []
    if has_email and interactive_confirm("Enable email notifications?", default=True):
        channels.append("email")
    if has_slack and interactive_confirm("Enable Slack notifications?", default=True):
        channels.append("slack")
    if has_telegram and interactive_confirm(
        "Enable Telegram notifications?", default=True
    ):
        channels.append("telegram")

    if not channels:
        print_step("No channels enabled.")
        return

    # Ask for per-project overrides
    extra_to: list[str] = []
    if "email" in channels:
        extra_raw = interactive_prompt(
            "Extra email recipients for this project (comma-separated, or blank)",
            default="",
        )
        if extra_raw.strip():
            extra_to = [a.strip() for a in extra_raw.split(",") if a.strip()]

    override_chat_id = ""
    if "telegram" in channels:
        global_chat = global_notif.get("telegram", {}).get("chat_id", "")
        override_raw = interactive_prompt(
            f"Telegram chat ID for this project (blank to use global: {global_chat})",
            default="",
        )
        if override_raw.strip():
            override_chat_id = override_raw.strip()

    # Save to project urika.toml
    notif: dict = {"channels": channels}
    if extra_to:
        notif["email"] = {"to": extra_to}
    if override_chat_id:
        notif["telegram"] = {"chat_id": override_chat_id}
    settings["notifications"] = notif
    _save_notification_settings(settings, is_project=True, project_path=project_path)

    print_success(f"Notifications enabled: {', '.join(channels)}")
    if extra_to:
        click.echo(f"  Extra recipients: {', '.join(extra_to)}")
    if override_chat_id:
        click.echo(f"  Telegram chat: {override_chat_id} (project-specific)")
    click.echo()


def _notifications_global_setup(*, settings, project_path):
    """Global notification setup — configure channel settings."""

    import click
    from urika.cli_display import print_success
    from urika.cli_helpers import (
        interactive_confirm,
        interactive_numbered,
        interactive_prompt,
    )
    from urika.core.secrets import save_secret

    notif = settings.get("notifications", {})

    click.echo("\n  Notification setup\n")

    # Show current state
    email_cfg = notif.get("email", {})
    slack_cfg = notif.get("slack", {})
    telegram_cfg = notif.get("telegram", {})

    click.echo("  Current channels:")
    if email_cfg.get("to"):
        to_list = email_cfg["to"]
        if isinstance(to_list, list):
            to_list = ", ".join(to_list)
        click.echo(
            f"    Email:    {email_cfg.get('from_addr', '?')} -> {to_list} (configured)"
        )
    else:
        click.echo("    Email:    not configured")

    if slack_cfg.get("channel"):
        click.echo(f"    Slack:    {slack_cfg['channel']} (configured)")
    else:
        click.echo("    Slack:    not configured")

    if telegram_cfg.get("chat_id"):
        click.echo(f"    Telegram: chat {telegram_cfg['chat_id']} (configured)")
    else:
        click.echo("    Telegram: not configured")

    click.echo()

    while True:
        choice = interactive_numbered(
            "  Configure:",
            [
                "Email",
                "Slack",
                "Telegram",
                "Send test notification",
                "Done",
            ],
            default=5,
            allow_cancel=False,
        )

        if choice == "Done":
            break

        if choice == "Send test notification":
            _send_test_notification(settings.get("notifications", {}))
            continue

        if choice == "Email":
            click.echo("\n  Email setup\n")

            smtp_server = interactive_prompt(
                "SMTP server",
                default=email_cfg.get("smtp_server", "smtp.gmail.com"),
            )
            smtp_port = interactive_prompt(
                "SMTP port",
                default=str(email_cfg.get("smtp_port", 587)),
            )
            from_addr = interactive_prompt(
                "From address",
                default=email_cfg.get("from_addr", ""),
            )
            to_raw = interactive_prompt(
                "To addresses (comma-separated)",
                default=", ".join(email_cfg.get("to", [])),
            )
            to_addrs = [a.strip() for a in to_raw.split(",") if a.strip()]

            # App password / SMTP password (shown — these are generated tokens, not personal passwords)
            password = interactive_prompt(
                "App password (e.g. Gmail app password)",
                default="",
            )

            if password:
                save_secret("URIKA_EMAIL_PASSWORD", password)
                click.echo("  Saved! Password stored in ~/.urika/secrets.env")

            notif.setdefault("email", {}).update(
                {
                    "smtp_server": smtp_server,
                    "smtp_port": int(smtp_port),
                    "from_addr": from_addr,
                    "username": from_addr,
                    "to": to_addrs,
                    "password_env": "URIKA_EMAIL_PASSWORD",
                }
            )
            settings["notifications"] = notif
            _save_notification_settings(settings, False, project_path)
            print_success("Email configured.")

            if interactive_confirm("Send test email?", default=True):
                _send_test_notification(settings.get("notifications", {}))

            click.echo()
            continue

        if choice == "Slack":
            click.echo("\n  Slack setup\n")

            channel = interactive_prompt(
                "Channel (e.g. #urika-results)",
                default=slack_cfg.get("channel", ""),
            )

            bot_token = interactive_prompt(
                "Bot token (from Slack app settings)",
                default="",
            )

            if bot_token:
                save_secret("SLACK_BOT_TOKEN", bot_token)

            app_token = interactive_prompt(
                "App token (for interactive buttons, optional)",
                default="",
            )

            if app_token:
                save_secret("SLACK_APP_TOKEN", app_token)

            notif.setdefault("slack", {}).update(
                {
                    "channel": channel,
                    "bot_token_env": "SLACK_BOT_TOKEN",
                    "app_token_env": "SLACK_APP_TOKEN" if app_token else "",
                }
            )
            settings["notifications"] = notif
            _save_notification_settings(settings, False, project_path)

            tokens_saved = []
            if bot_token:
                tokens_saved.append("bot token")
            if app_token:
                tokens_saved.append("app token")
            if tokens_saved:
                click.echo(
                    f"  Saved! {', '.join(tokens_saved).capitalize()}"
                    " stored in ~/.urika/secrets.env"
                )
            print_success("Slack configured.")
            click.echo()
            continue

        if choice == "Telegram":
            click.echo("\n  Telegram setup\n")

            chat_id = interactive_prompt(
                "Chat ID (e.g. -100123456789)",
                default=str(telegram_cfg.get("chat_id", "")),
            )

            bot_token = interactive_prompt(
                "Bot token (from @BotFather)",
                default="",
            )

            if bot_token:
                save_secret("TELEGRAM_BOT_TOKEN", bot_token)
                click.echo("  Saved! Token stored in ~/.urika/secrets.env")

            notif.setdefault("telegram", {}).update(
                {
                    "chat_id": chat_id,
                    "bot_token_env": "TELEGRAM_BOT_TOKEN",
                }
            )
            settings["notifications"] = notif
            _save_notification_settings(settings, False, project_path)
            print_success("Telegram configured.")
            click.echo()
            continue


def _save_notification_settings(settings, is_project, project_path):
    """Save settings back to the appropriate TOML file."""
    if is_project:
        from urika.core.workspace import _write_toml

        _write_toml(project_path / "urika.toml", settings)
    else:
        from urika.core.settings import save_settings

        save_settings(settings)


@cli.command("setup")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def setup_command(json_output: bool) -> None:
    """Check installation and install optional packages."""
    from urika.cli_display import (
        print_error,
        print_step,
        print_success,
        print_warning,
    )

    if json_output:
        # Collect package status and hardware info as JSON
        _all_packages = {
            "numpy": "numpy",
            "pandas": "pandas",
            "scipy": "scipy",
            "scikit-learn": "sklearn",
            "statsmodels": "statsmodels",
            "pingouin": "pingouin",
            "click": "click",
            "claude-agent-sdk": "claude_agent_sdk",
            "matplotlib": "matplotlib",
            "seaborn": "seaborn",
            "xgboost": "xgboost",
            "lightgbm": "lightgbm",
            "optuna": "optuna",
            "shap": "shap",
            "imbalanced-learn": "imblearn",
            "pypdf": "pypdf",
            "torch": "torch",
            "transformers": "transformers",
            "torchvision": "torchvision",
            "torchaudio": "torchaudio",
        }
        pkg_status = {}
        for name, imp in _all_packages.items():
            try:
                __import__(imp)
                pkg_status[name] = True
            except Exception:
                pkg_status[name] = False

        hw_data: dict = {}
        try:
            from urika.core.hardware import detect_hardware as _dh

            hw_data = dict(_dh())
        except Exception:
            pass

        from urika.cli_helpers import output_json

        output_json(
            {
                "packages": pkg_status,
                "hardware": hw_data,
                "anthropic_api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            }
        )
        return

    click.echo()
    click.echo("  Urika Setup")
    click.echo("  " + "─" * 40)
    click.echo()

    # Check core packages
    core_packages = {
        "numpy": "numpy",
        "pandas": "pandas",
        "scipy": "scipy",
        "scikit-learn": "sklearn",
        "statsmodels": "statsmodels",
        "pingouin": "pingouin",
        "click": "click",
        "claude-agent-sdk": "claude_agent_sdk",
    }
    print_step("Core packages:")
    all_core = True
    for name, imp in core_packages.items():
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")
            all_core = False
    if not all_core:
        print_warning("Some core packages missing. Run: pip install -e .")
        click.echo()

    # Check viz
    print_step("Visualization:")
    for name, imp in [
        ("matplotlib", "matplotlib"),
        ("seaborn", "seaborn"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")

    # Check ML
    print_step("Machine Learning:")
    for name, imp in [
        ("xgboost", "xgboost"),
        ("lightgbm", "lightgbm"),
        ("optuna", "optuna"),
        ("shap", "shap"),
        ("imbalanced-learn", "imblearn"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")

    # Check knowledge
    print_step("Knowledge pipeline:")
    try:
        __import__("pypdf")
        print_success("  pypdf")
    except ImportError:
        print_error("  pypdf — NOT INSTALLED")

    # Check DL
    print_step("Deep Learning:")
    dl_installed = True
    for name, imp in [
        ("torch", "torch"),
        ("transformers", "transformers"),
        ("torchvision", "torchvision"),
        ("torchaudio", "torchaudio"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — not installed")
            dl_installed = False
        except Exception as exc:
            # RuntimeError from CUDA version mismatches, etc.
            short = str(exc).split(".")[0]
            print_error(f"  {name} — {short}")
            dl_installed = False

    # Check hardware
    click.echo()
    print_step("Hardware:")
    try:
        from urika.core.hardware import detect_hardware

        hw = detect_hardware()
        cpu = hw["cpu_count"]
        ram = hw["ram_gb"]
        print_success(f"  CPU: {cpu} cores")
        if ram:
            print_success(f"  RAM: {ram} GB")
        if hw["gpu"]:
            gpu = hw["gpu_name"]
            vram = hw.get("gpu_vram", "")
            label = f"  GPU: {gpu}"
            if vram:
                label += f" ({vram})"
            print_success(label)
        else:
            print_step("  GPU: none detected")
    except Exception:
        print_step("  Could not detect hardware")

    # Offer DL install
    if not dl_installed:
        click.echo()
        click.echo("  " + "─" * 40)
        click.echo()
        print_step("Deep learning packages are not installed.")
        print_step(
            "These are large (~2 GB) and only needed for neural network experiments."
        )
        click.echo()
        choice = click.prompt(
            "  Install deep learning packages?",
            type=click.Choice(
                ["yes", "no", "gpu", "cpu"],
                case_sensitive=False,
            ),
            default="no",
        )
        if choice == "no":
            click.echo("  Skipped.")
        else:
            import subprocess
            import sys

            def _torch_install_args(*, want_gpu: bool = True) -> tuple[list[str], str]:
                """Build pip install args for PyTorch based on platform.

                Returns (args_list, description_string).

                - macOS: default PyPI (includes MPS for Apple Silicon)
                - ARM (any OS without NVIDIA): default PyPI
                - x86 + NVIDIA: detect CUDA version, use matching wheel
                - No GPU / want_gpu=False: CPU-only wheels (x86) or default (ARM)
                """
                import platform

                # Use --force-reinstall if torchaudio has a CUDA mismatch
                force = False
                try:
                    r = subprocess.run(
                        [sys.executable, "-c", "import torchaudio"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if r.returncode != 0 and "CUDA version" in r.stderr:
                        force = True
                except Exception:
                    pass

                base = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    *(["--force-reinstall"] if force else []),
                    "torch",
                    "torchvision",
                    "torchaudio",
                ]
                arch = platform.machine().lower()
                is_arm = arch in ("arm64", "aarch64", "armv8l")

                # macOS — default PyPI includes MPS for Apple Silicon
                if sys.platform == "darwin":
                    desc = "MPS" if is_arm else "CPU"
                    return base, desc

                # ARM Linux/Windows — no CUDA index, default PyPI
                if is_arm:
                    cuda_tag = _detect_cuda_tag() if want_gpu else None
                    if cuda_tag:
                        # ARM + NVIDIA (Jetson) — use default pip, torch auto-detects
                        return base, f"ARM + CUDA ({cuda_tag})"
                    return base, "ARM CPU"

                # x86 Linux/Windows
                if want_gpu:
                    cuda_tag = _detect_cuda_tag()
                    if cuda_tag:
                        return (
                            base
                            + [
                                "--index-url",
                                f"https://download.pytorch.org/whl/{cuda_tag}",
                            ],
                            f"CUDA {cuda_tag}",
                        )
                return (
                    base + ["--index-url", "https://download.pytorch.org/whl/cpu"],
                    "CPU",
                )

            def _detect_cuda_tag() -> str | None:
                """Detect CUDA version, return wheel tag (e.g. 'cu124') or None."""
                # 1. Check existing torch installation
                try:
                    import torch

                    cv = torch.version.cuda
                    if cv:
                        parts = cv.split(".")
                        return f"cu{parts[0]}{parts[1]}"
                except Exception:
                    pass
                # 2. Check nvcc
                try:
                    import re

                    r = subprocess.run(
                        ["nvcc", "--version"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if r.returncode == 0:
                        m = re.search(r"release (\d+)\.(\d+)", r.stdout)
                        if m:
                            return f"cu{m.group(1)}{m.group(2)}"
                except Exception:
                    pass
                # 3. Check nvidia-smi exists (GPU present but no toolkit)
                try:
                    r = subprocess.run(
                        ["nvidia-smi"],
                        capture_output=True,
                        timeout=5,
                    )
                    if r.returncode == 0:
                        return "cu124"  # Default to latest stable
                except Exception:
                    pass
                return None

            if choice == "gpu":
                args, desc = _torch_install_args(want_gpu=True)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                # Then the rest
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            elif choice == "cpu":
                args, desc = _torch_install_args(want_gpu=False)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            else:
                # "yes" — auto-detect
                try:
                    from urika.core.hardware import (
                        detect_hardware,
                    )

                    hw_info = detect_hardware()
                    has_gpu = hw_info.get("gpu", False)
                except Exception:
                    has_gpu = False

                args, desc = _torch_install_args(want_gpu=has_gpu)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            print_success("Deep learning packages installed.")
    else:
        # Check GPU availability with torch
        click.echo()
        try:
            import torch

            if torch.cuda.is_available():
                dev = torch.cuda.get_device_name(0)
                print_success(f"  PyTorch CUDA: {dev}")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                print_success("  PyTorch MPS: available")
            else:
                print_step("  PyTorch: CPU only")
        except Exception:
            pass

    click.echo()
    print_step("Claude access:")
    if os.environ.get("ANTHROPIC_API_KEY"):
        print_success("  ANTHROPIC_API_KEY is set")
    else:
        print_warning(
            "  ANTHROPIC_API_KEY not set — needed unless using Claude Max/Pro"
        )

    click.echo()
    # Check for updates
    print_step("Updates:")
    try:
        from urika.core.updates import (
            check_for_updates,
            format_update_message,
        )

        update_info = check_for_updates(force=True)
        if update_info:
            msg = format_update_message(update_info)
            print_warning(f"  {msg}")
        else:
            print_success("  You are on the latest version")
    except Exception:
        print_step("  Could not check for updates")

    click.echo()
    print_success("Setup check complete.")
    click.echo()


@cli.group("venv")
def venv_group() -> None:
    """Manage project virtual environments."""


@venv_group.command("create")
@click.argument("project", required=False, default=None)
def venv_create(project: str | None) -> None:
    """Create a venv for a project."""
    import tomllib

    from urika.core.venv import create_project_venv

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    venv_path = create_project_venv(project_path)

    # Update urika.toml to enable venv
    toml_path = project_path / "urika.toml"
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    data.setdefault("environment", {})["venv"] = True
    from urika.core.workspace import _write_toml

    _write_toml(toml_path, data)

    click.echo(f"Created .venv at {venv_path}")


@venv_group.command("status")
@click.argument("project", required=False, default=None)
def venv_status(project: str | None) -> None:
    """Show venv status for a project."""
    from urika.core.venv import is_venv_enabled

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if is_venv_enabled(project_path):
        venv_path = project_path / ".venv"
        exists = venv_path.exists()
        click.echo(f"Venv: enabled ({'exists' if exists else 'NOT FOUND'})")
        click.echo(f"Path: {venv_path}")
    else:
        click.echo("Venv: not enabled (using global environment)")


# ── Submodule imports: trigger command registration ──
import urika.cli.project  # noqa: F401,E402
import urika.cli.run  # noqa: F401,E402
