"""``urika upgrade`` — idempotent v0.x project migration (v0.10.0 Phase 1).

The v1.0 promise: any project created by an older Urika release upgrades
in place via ``urika upgrade`` (auto-migrate, idempotent). Almost every
on-disk reader already defaults missing keys at load time, so an upgrade
is mostly a **version stamp** plus a couple of canonical on-disk rewrites:

* **Stamp** ``[project].schema_version`` to ``current_schema_version()``.
* **Leaderboard rewrite**: a legacy ``leaderboard.json`` with the
  pre-canonical ``"entries"`` key is rewritten to ``{"ranking": [...]}``.
* **Labbook regen** (best-effort): regenerate each experiment's notes so
  pre-v0.8 labbooks gain metric-interpretation rendering.

Every migration is idempotent and atomic. A project already at the
current schema version short-circuits to a no-op, and the
``entries``-key check means a second run never touches the leaderboard
either — so ``upgrade`` run twice is a byte-for-byte no-op.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from urika.cli._base import cli
from urika.core.atomic_write import write_text_atomic
from urika.core.models import ProjectConfig, current_schema_version
from urika.core.registry import ProjectRegistry
from urika.core.workspace import load_project_config, render_toml


def _stamp_schema_version(project_dir: Path, config: ProjectConfig) -> str | None:
    """Stamp the current schema version into urika.toml.

    Re-serialises the config (preserving every field) with the version
    set, written atomically (P5 made related writes atomic). Returns a
    human-readable summary of what changed, or ``None`` if nothing changed.
    """
    target = current_schema_version()
    if config.schema_version == target:
        return None
    previous = config.schema_version or "(unset)"
    config.schema_version = target
    body = render_toml(config.to_toml_dict())
    write_text_atomic(project_dir / "urika.toml", body)
    return f"stamped schema_version {previous} -> {target}"


def _rewrite_leaderboard(project_dir: Path) -> str | None:
    """Rewrite a legacy ``entries`` leaderboard to canonical ``ranking``.

    Returns a summary string if a rewrite happened, else ``None``. The
    ``entries``-key check makes this idempotent: a leaderboard that's
    already canonical (or absent) is left byte-for-byte untouched.
    """
    lb_path = project_dir / "leaderboard.json"
    if not lb_path.exists():
        return None
    try:
        raw = json.loads(lb_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict) or "entries" not in raw or "ranking" in raw:
        return None

    # load_leaderboard already migrates entries -> ranking in memory.
    from urika.evaluation.leaderboard import load_leaderboard

    data = load_leaderboard(project_dir)
    # Match the canonical byte format used by update_leaderboard.
    write_text_atomic(lb_path, json.dumps(data, indent=2) + "\n")
    return "rewrote leaderboard.json entries -> ranking"


def _regen_labbooks(project_dir: Path, config: ProjectConfig) -> list[str]:
    """Best-effort regen of each experiment's labbook notes.

    Pre-v0.8 labbooks predate metric-interpretation rendering; regenerating
    them from progress.json is safe and lossless. Never aborts the upgrade —
    a single bad experiment is skipped.
    """
    summaries: list[str] = []
    try:
        from urika.core.experiment import list_experiments
        from urika.core.labbook import update_experiment_notes
    except Exception:
        return summaries

    for exp in list_experiments(project_dir):
        try:
            update_experiment_notes(project_dir, exp.experiment_id, config=config)
            summaries.append(f"regenerated labbook notes for {exp.experiment_id}")
        except Exception:
            continue
    return summaries


def _upgrade_one(name: str, *, regen: bool) -> dict:
    """Upgrade a single project. Returns a per-project result dict."""
    project_dir = ProjectRegistry().get(name)
    if project_dir is None:
        return {
            "project": name,
            "error": "not found in registry",
            "already_current": False,
            "migrations": [],
        }
    try:
        config = load_project_config(project_dir)
    except FileNotFoundError:
        return {
            "project": name,
            "error": f"no urika.toml at {project_dir}",
            "already_current": False,
            "migrations": [],
        }

    detected = config.schema_version or "(unset)"
    target = current_schema_version()

    if config.schema_version == target:
        return {
            "project": name,
            "detected_version": detected,
            "final_version": target,
            "already_current": True,
            "migrations": [],
        }

    migrations: list[str] = []

    lb = _rewrite_leaderboard(project_dir)
    if lb:
        migrations.append(lb)

    if regen:
        migrations.extend(_regen_labbooks(project_dir, config))

    # Stamp last so a failure mid-migration doesn't mark the project current.
    stamp = _stamp_schema_version(project_dir, config)
    if stamp:
        migrations.append(stamp)

    return {
        "project": name,
        "detected_version": detected,
        "final_version": target,
        "already_current": False,
        "migrations": migrations,
    }


def _print_result(result: dict) -> None:
    name = result["project"]
    if result.get("error"):
        click.secho(f"  ✗ {name}: {result['error']}", fg="red", err=True)
        return
    detected = result.get("detected_version", "(unset)")
    final = result.get("final_version", "")
    if result["already_current"]:
        click.echo(f"  {name}: already current (v{final})")
        return
    click.echo(f"  {name}: v{detected} -> v{final}")
    if result["migrations"]:
        for m in result["migrations"]:
            click.echo(f"      • {m}")
    else:
        click.echo("      • no migrations needed")


@cli.command("upgrade")
@click.argument("project", required=False, default=None)
@click.option(
    "--all", "all_projects", is_flag=True, help="Upgrade every registered project."
)
@click.option(
    "--no-regen",
    is_flag=True,
    help="Skip labbook notes regeneration (faster; version stamp only).",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def upgrade(
    project: str | None,
    all_projects: bool,
    no_regen: bool,
    json_output: bool,
) -> None:
    """Migrate a v0.x project to the current schema (idempotent).

    Stamps the schema version, rewrites a legacy ``entries`` leaderboard
    to the canonical ``ranking`` key, and regenerates labbook notes.
    Running twice on the same project is a no-op.

    Examples:

        urika upgrade my-study

        urika upgrade --all

        urika upgrade my-study --json
    """
    registry = ProjectRegistry()

    if all_projects:
        names = sorted(registry.list_all().keys())
        if not names:
            raise click.ClickException(
                "No projects registered. Create one with: urika new <name>"
            )
    elif project:
        names = [project]
    else:
        raise click.ClickException(
            "Specify a project name or use --all.\n"
            "  urika upgrade <project>\n"
            "  urika upgrade --all"
        )

    results = [_upgrade_one(n, regen=not no_regen) for n in names]

    if json_output:
        click.echo(json.dumps(results, indent=2))
        return

    for result in results:
        _print_result(result)
