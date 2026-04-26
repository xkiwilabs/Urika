"""Project enumeration helper for the dashboard.

Wraps ProjectRegistry + per-project urika.toml + experiments/ scan
into a single ProjectSummary dataclass that templates can render
without touching multiple modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from urika.core.experiment import list_experiments
from urika.core.workspace import load_project_config


@dataclass
class ProjectSummary:
    """One row in the projects-list view."""

    name: str
    path: Path
    question: str = ""
    mode: str = ""
    description: str = ""
    audience: str = "standard"
    experiment_count: int = 0
    missing: bool = False
    # ISO-8601 timestamp of latest activity: max(mtime) over urika.toml
    # plus every experiments/*/progress.json. Empty string if the path
    # is gone or computation fails — kept as a string so templates can
    # safely emit it as a data attribute without further coercion.
    last_activity: str = ""


def _compute_last_activity(project_path: Path) -> str:
    """Return ISO-8601 of the most recently touched config or progress file.

    Considers ``urika.toml`` and every ``experiments/*/progress.json``.
    Falls back to ``urika.toml``'s mtime when no experiments exist;
    returns ``""`` if nothing readable is found or any OS error occurs.
    """
    try:
        mtimes: list[float] = []
        toml_path = project_path / "urika.toml"
        if toml_path.exists():
            mtimes.append(toml_path.stat().st_mtime)
        experiments_dir = project_path / "experiments"
        if experiments_dir.is_dir():
            for progress in experiments_dir.glob("*/progress.json"):
                try:
                    mtimes.append(progress.stat().st_mtime)
                except OSError:
                    continue
        if not mtimes:
            return ""
        latest = max(mtimes)
        return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def list_project_summaries(
    registry: dict[str, Path],
) -> list[ProjectSummary]:
    """Build a summary for every entry in the registry, sorted by name.

    A registry entry whose directory has been deleted is included with
    ``missing=True`` so the UI can show it greyed-out rather than
    silently dropping it.
    """
    summaries: list[ProjectSummary] = []
    for name, path in sorted(registry.items()):
        if not path.exists():
            summaries.append(ProjectSummary(name=name, path=path, missing=True))
            continue
        try:
            cfg = load_project_config(path)
        except FileNotFoundError:
            summaries.append(ProjectSummary(name=name, path=path, missing=True))
            continue
        try:
            n_experiments = len(list_experiments(path))
        except Exception:
            n_experiments = 0
        summaries.append(
            ProjectSummary(
                name=name,
                path=path,
                question=cfg.question,
                mode=cfg.mode,
                description=cfg.description,
                audience=cfg.audience,
                experiment_count=n_experiments,
                last_activity=_compute_last_activity(path),
            )
        )
    return summaries


def load_project_summary(
    name: str,
    registry: dict[str, Path],
) -> ProjectSummary | None:
    path = registry.get(name)
    if path is None:
        return None
    if not path.exists():
        return ProjectSummary(name=name, path=path, missing=True)
    try:
        cfg = load_project_config(path)
    except FileNotFoundError:
        return ProjectSummary(name=name, path=path, missing=True)
    try:
        n_experiments = len(list_experiments(path))
    except Exception:
        n_experiments = 0
    return ProjectSummary(
        name=name,
        path=path,
        question=cfg.question,
        mode=cfg.mode,
        description=cfg.description,
        audience=cfg.audience,
        experiment_count=n_experiments,
        last_activity=_compute_last_activity(path),
    )
