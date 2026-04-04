"""Data/results-related CLI commands: results, methods, tools, logs, usage, knowledge."""

from __future__ import annotations

from pathlib import Path

import click

from urika.cli._legacy import cli
from urika.core.experiment import list_experiments
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry
from urika.evaluation.leaderboard import load_leaderboard
from urika.tools import ToolRegistry

from urika.cli._helpers import (
    _resolve_project,
    _ensure_project,
    _prompt_numbered,
)


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


