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
import urika.cli.data  # noqa: F401,E402
