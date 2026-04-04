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
import urika.cli.agents  # noqa: F401,E402
import urika.cli.config  # noqa: F401,E402
