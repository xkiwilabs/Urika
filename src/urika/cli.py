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
def run(project: str, experiment_id: str | None, max_turns: int) -> None:
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

    click.echo(f"Running experiment {experiment_id} (max {max_turns} turns)...")

    runner = ClaudeSDKRunner()
    result = asyncio.run(
        run_experiment(project_path, experiment_id, runner, max_turns=max_turns)
    )

    status = result.get("status", "unknown")
    turns = result.get("turns", 0)
    error = result.get("error")

    if status == "completed":
        click.echo(f"Experiment completed after {turns} turns.")
    elif status == "failed":
        click.echo(f"Experiment failed after {turns} turns: {error}")
    else:
        click.echo(f"Experiment finished with status: {status} ({turns} turns)")
