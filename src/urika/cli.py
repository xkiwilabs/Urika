"""Urika CLI."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click

from urika.core.experiment import create_experiment, list_experiments
from urika.core.models import ProjectConfig
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace, load_project_config
from urika.evaluation.leaderboard import load_leaderboard
from urika.methods import MethodRegistry
from urika.tools import ToolRegistry


def _projects_dir() -> Path:
    """Default directory for new projects."""
    env = os.environ.get("URIKA_PROJECTS_DIR")
    if env:
        return Path(env)
    return Path.home() / "urika-projects"


def _resolve_project(name: str) -> tuple[Path, ProjectConfig]:
    """Look up project by name. Raises ClickException on error."""
    registry = ProjectRegistry()
    project_path = registry.get(name)
    if project_path is None:
        raise click.ClickException(f"Project '{name}' not found in registry.")
    try:
        config = load_project_config(project_path)
    except FileNotFoundError:
        raise click.ClickException(f"Project directory missing at {project_path}")
    return project_path, config


@click.group()
@click.version_option(package_name="urika")
def cli() -> None:
    """Urika: Agentic scientific analysis platform."""


@cli.command()
@click.argument("name")
@click.option("-q", "--question", required=True, help="Research question.")
@click.option(
    "-m",
    "--mode",
    required=True,
    type=click.Choice(["exploratory", "confirmatory", "pipeline"]),
    help="Investigation mode.",
)
@click.option("--data", multiple=True, help="Path(s) to data files.")
def new(name: str, question: str, mode: str, data: tuple[str, ...]) -> None:
    """Create a new project."""
    config = ProjectConfig(
        name=name,
        question=question,
        mode=mode,
        data_paths=list(data),
    )

    project_dir = _projects_dir() / name
    try:
        create_project_workspace(project_dir, config)
    except FileExistsError:
        raise click.ClickException(f"Project already exists at {project_dir}")

    registry = ProjectRegistry()
    registry.register(name, project_dir)

    click.echo(f"Created project '{name}' at {project_dir}")


@cli.command("list")
def list_cmd() -> None:
    """List all registered projects."""
    registry = ProjectRegistry()
    projects = registry.list_all()

    if not projects:
        click.echo("No projects registered.")
        return

    for name, path in projects.items():
        exists = "  " if path.exists() else "? "
        click.echo(f"{exists}{name}  {path}")


@cli.command()
@click.argument("name")
def status(name: str) -> None:
    """Show project status."""
    project_path, config = _resolve_project(name)

    experiments = list_experiments(project_path)

    click.echo(f"Project: {config.name}")
    click.echo(f"Question: {config.question}")
    click.echo(f"Mode: {config.mode}")
    click.echo(f"Path: {project_path}")
    click.echo(f"Experiments: {len(experiments)}")

    if experiments:
        click.echo("")
        for exp in experiments:
            progress = load_progress(project_path, exp.experiment_id)
            n_runs = len(progress.get("runs", []))
            exp_status = progress.get("status", "unknown")
            click.echo(
                f"  {exp.experiment_id}: {exp.name} [{exp_status}, {n_runs} runs]"
            )


@cli.group()
def experiment() -> None:
    """Manage experiments within a project."""


@experiment.command("create")
@click.argument("project")
@click.argument("name")
@click.option("--hypothesis", default="", help="Experiment hypothesis.")
def experiment_create(project: str, name: str, hypothesis: str) -> None:
    """Create a new experiment in a project."""
    project_path, _config = _resolve_project(project)
    exp = create_experiment(project_path, name=name, hypothesis=hypothesis)
    click.echo(f"{exp.experiment_id}")


@experiment.command("list")
@click.argument("project")
def experiment_list(project: str) -> None:
    """List experiments in a project."""
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
@click.argument("project")
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Show runs for a specific experiment.",
)
def results(project: str, experiment_id: str | None) -> None:
    """Show project results (leaderboard or experiment runs)."""
    project_path, _config = _resolve_project(project)

    if experiment_id is not None:
        progress = load_progress(project_path, experiment_id)
        runs = progress.get("runs", [])
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

    if not ranking:
        click.echo("No results yet.")
        return

    for entry in ranking:
        metrics_str = ", ".join(f"{k}={v}" for k, v in entry.get("metrics", {}).items())
        click.echo(f"  #{entry['rank']}  {entry['method']}  {metrics_str}")


@cli.command()
@click.option("--category", default=None, help="Filter by category.")
@click.option("--project", default=None, help="Include project-specific methods.")
def methods(category: str | None, project: str | None) -> None:
    """List available analysis methods."""
    registry = MethodRegistry()
    registry.discover()

    if project is not None:
        project_path, _config = _resolve_project(project)
        registry.discover_project(project_path / "methods")

    if category is not None:
        names = registry.list_by_category(category)
    else:
        names = registry.list_all()

    if not names:
        click.echo("No methods found.")
        return

    for name in names:
        method = registry.get(name)
        if method is not None:
            click.echo(
                f"  {method.name()}  [{method.category()}]  {method.description()}"
            )


@cli.command()
@click.option("--category", default=None, help="Filter by category.")
@click.option("--project", default=None, help="Include project-specific tools.")
def tools(category: str | None, project: str | None) -> None:
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

    if not names:
        click.echo("No tools found.")
        return

    for name in names:
        tool = registry.get(name)
        if tool is not None:
            click.echo(f"  {tool.name()}  [{tool.category()}]  {tool.description()}")


@cli.command()
@click.argument("project")
@click.option(
    "--experiment", "experiment_id", default=None, help="Experiment ID to run."
)
@click.option("--max-turns", default=50, help="Maximum orchestrator turns.")
@click.option(
    "--continue",
    "resume",
    is_flag=True,
    default=False,
    help="Resume a paused or failed experiment.",
)
def run(project: str, experiment_id: str | None, max_turns: int, resume: bool) -> None:
    """Run an experiment using the orchestrator."""
    from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
    from urika.orchestrator import run_experiment

    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            raise click.ClickException(
                "No experiments in this project. Create one first."
            )
        experiment_id = experiments[-1].experiment_id
        click.echo(f"Using latest experiment: {experiment_id}")

    if resume:
        click.echo(f"Resuming experiment {experiment_id}...")
    else:
        click.echo(f"Running experiment {experiment_id} (max {max_turns} turns)...")

    sdk_runner = ClaudeSDKRunner()
    result = asyncio.run(
        run_experiment(
            project_path,
            experiment_id,
            sdk_runner,
            max_turns=max_turns,
            resume=resume,
        )
    )

    run_status = result.get("status", "unknown")
    turns = result.get("turns", 0)
    error = result.get("error")

    if run_status == "completed":
        click.echo(f"Experiment completed after {turns} turns.")
    elif run_status == "failed":
        click.echo(f"Experiment failed after {turns} turns: {error}")
    else:
        click.echo(f"Experiment finished with status: {run_status} ({turns} turns)")


@cli.command()
@click.argument("project")
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Generate report for a specific experiment.",
)
def report(project: str, experiment_id: str | None) -> None:
    """Generate labbook reports."""
    from urika.core.labbook import (
        generate_experiment_summary,
        generate_key_findings,
        generate_results_summary,
        update_experiment_notes,
    )

    project_path, _config = _resolve_project(project)

    if experiment_id is not None:
        try:
            update_experiment_notes(project_path, experiment_id)
            generate_experiment_summary(project_path, experiment_id)
        except FileNotFoundError:
            raise click.ClickException(f"Experiment '{experiment_id}' not found.")
        notes = project_path / "experiments" / experiment_id / "labbook" / "notes.md"
        summary = (
            project_path / "experiments" / experiment_id / "labbook" / "summary.md"
        )
        click.echo(f"Updated: {notes}")
        click.echo(f"Generated: {summary}")
        return

    # Project-level reports
    try:
        generate_results_summary(project_path)
        generate_key_findings(project_path)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))

    # Also refresh notes for all experiments
    for exp in list_experiments(project_path):
        try:
            update_experiment_notes(project_path, exp.experiment_id)
        except FileNotFoundError:
            pass

    results_path = project_path / "labbook" / "results-summary.md"
    findings_path = project_path / "labbook" / "key-findings.md"
    click.echo(f"Generated: {results_path}")
    click.echo(f"Generated: {findings_path}")


@cli.command()
@click.argument("project")
@click.option(
    "--data", "data_file", default=None, help="Specific data file to inspect."
)
def inspect(project: str, data_file: str | None) -> None:
    """Inspect project data: schema, dtypes, missing values, preview."""
    from urika.data.loader import load_dataset

    project_path, config = _resolve_project(project)

    # Find data file
    if data_file is not None:
        path = (
            Path(data_file)
            if Path(data_file).is_absolute()
            else project_path / data_file
        )
    else:
        # Look for data files in project's data/ directory
        data_dir = project_path / "data"
        if not data_dir.exists():
            raise click.ClickException("No data/ directory found.")
        csv_files = list(data_dir.glob("*.csv"))
        if not csv_files:
            raise click.ClickException("No CSV files found in data/ directory.")
        path = csv_files[0]
        if len(csv_files) > 1:
            click.echo(f"Multiple data files found. Using: {path.name}")

    try:
        view = load_dataset(path)
    except Exception as exc:
        raise click.ClickException(f"Failed to load data: {exc}")

    click.echo(f"Dataset: {path.name}")
    click.echo(f"Rows: {view.summary.n_rows}")
    click.echo(f"Columns: {view.summary.n_columns}")
    click.echo("")

    # Schema table
    click.echo("Schema:")
    for col in view.summary.columns:
        dtype = view.summary.dtypes.get(col, "unknown")
        missing = view.summary.missing_counts.get(col, 0)
        missing_pct = (
            f" ({100 * missing / view.summary.n_rows:.1f}% missing)"
            if missing > 0
            else ""
        )
        click.echo(f"  {col:<30s} {dtype:<15s}{missing_pct}")
    click.echo("")

    # Preview (first 5 rows)
    click.echo("Preview (first 5 rows):")
    click.echo(view.data.head().to_string(index=False))


@cli.command()
@click.argument("project")
@click.option(
    "--experiment", "experiment_id", default=None, help="Specific experiment."
)
def logs(project: str, experiment_id: str | None) -> None:
    """Show experiment run log."""
    from urika.core.session import load_session

    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            raise click.ClickException("No experiments in this project.")
        experiment_id = experiments[-1].experiment_id

    progress = load_progress(project_path, experiment_id)
    session = load_session(project_path, experiment_id)

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
@click.argument("project")
@click.argument("source")
def knowledge_ingest(project: str, source: str) -> None:
    """Ingest a file or URL into the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    try:
        entry = store.ingest(source)
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc))
    click.echo(f'Ingested: {entry.id} "{entry.title}" ({entry.source_type})')


@knowledge.command("search")
@click.argument("project")
@click.argument("query")
def knowledge_search(project: str, query: str) -> None:
    """Search the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    results = store.search(query)

    if not results:
        click.echo("No results found.")
        return

    for entry in results:
        snippet = entry.content[:100].replace("\n", " ")
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]  {snippet}")


@knowledge.command("list")
@click.argument("project")
def knowledge_list(project: str) -> None:
    """List all knowledge entries."""
    from urika.knowledge import KnowledgeStore

    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    entries = store.list_all()

    if not entries:
        click.echo("No knowledge entries yet.")
        return

    for entry in entries:
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]")
