"""Project-related CLI commands that stay compact: list, status, delete.

Larger commands live in their own modules and are re-exported below:

  cli/project_new.py      → new + _run_builder_agent_loop + _ingest_knowledge
  cli/project_inspect.py  → update_project + inspect

The re-exports at the bottom of this file keep
``from urika.cli.project import new`` etc. working.
"""

from __future__ import annotations

import click

from urika.cli._base import cli
from urika.cli._helpers import _ensure_project, _resolve_project
from urika.core.experiment import list_experiments
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry


@cli.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def list_cmd(json_output: bool) -> None:
    """List all registered projects."""
    registry = ProjectRegistry()
    projects = registry.list_all()

    if json_output:
        from urika.cli_helpers import output_json

        projects_data = [
            {"name": name, "path": str(path)} for name, path in projects.items()
        ]
        output_json({"projects": projects_data})
        return

    if not projects:
        click.echo("No projects registered.")
        return

    for name, path in projects.items():
        exists = "  " if path.exists() else "? "
        click.echo(f"{exists}{name}  {path}")


@cli.command()
@click.argument("name", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def status(name: str | None, json_output: bool) -> None:
    """Show project status."""
    name = _ensure_project(name)
    project_path, config = _resolve_project(name)

    experiments = list_experiments(project_path)

    if json_output:
        from urika.cli_helpers import output_json

        exps_data = []
        for exp in experiments:
            progress = load_progress(project_path, exp.experiment_id)
            exps_data.append(
                {
                    "experiment_id": exp.experiment_id,
                    "name": exp.name,
                    "status": progress.get("status", "unknown"),
                    "runs": len(progress.get("runs", [])),
                }
            )
        output_json(
            {
                "project": config.name,
                "question": config.question,
                "mode": config.mode,
                "path": str(project_path),
                "experiments": exps_data,
            }
        )
        return

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


@cli.command()
@click.argument("name")
@click.option("-f", "--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON result.")
def delete(name: str, force: bool, json_output: bool) -> None:
    """Move a project to ~/.urika/trash/ and unregister it.

    The project directory is moved (not deleted) so artifacts are
    preserved. Empty the trash manually when you're sure.
    """
    from urika.core.project_delete import (
        ActiveRunError,
        ProjectNotFoundError,
        trash_project,
    )

    if not force:
        try:
            click.confirm(
                f"Move project '{name}' to ~/.urika/trash/? "
                "(files preserved, registry entry removed)",
                abort=True,
            )
        except click.Abort:
            click.echo("Aborted.")
            return

    try:
        result = trash_project(name)
    except ProjectNotFoundError:
        raise click.ClickException(f"Project '{name}' is not registered.")
    except ActiveRunError as e:
        raise click.ClickException(str(e))

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {
                "name": result.name,
                "original_path": str(result.original_path),
                "trash_path": (str(result.trash_path) if result.trash_path else None),
                "registry_only": result.registry_only,
            }
        )
        return

    if result.registry_only:
        click.echo(
            f"Unregistered '{name}' "
            f"(folder at {result.original_path} was already missing)."
        )
    else:
        click.echo(f"Moved '{name}' to {result.trash_path}")


# ── Re-exports from sibling modules (Phase 8 split) ───────────────
# Importing these registers their @cli.command decorators and keeps
# the old import path working for callers that do
# ``from urika.cli.project import new`` / ``inspect`` etc.
from urika.cli.project_new import (  # noqa: E402, F401
    new,
    _run_builder_agent_loop,
    _ingest_knowledge,
)
from urika.cli.project_inspect import (  # noqa: E402, F401
    inspect,
    update_project,
)
