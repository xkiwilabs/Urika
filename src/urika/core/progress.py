"""Append-only progress tracking for experiments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from urika.core.models import RunRecord


def _progress_path(project_dir: Path, experiment_id: str) -> Path:
    return project_dir / "experiments" / experiment_id / "progress.json"


def load_progress(project_dir: Path, experiment_id: str) -> dict[str, Any]:
    """Load progress.json for an experiment."""
    path = _progress_path(project_dir, experiment_id)
    return json.loads(path.read_text())


def _save_progress(project_dir: Path, experiment_id: str, data: dict[str, Any]) -> None:
    path = _progress_path(project_dir, experiment_id)
    path.write_text(json.dumps(data, indent=2) + "\n")


def append_run(project_dir: Path, experiment_id: str, run: RunRecord) -> None:
    """Append a run record to an experiment's progress.json."""
    data = load_progress(project_dir, experiment_id)
    data["runs"].append(run.to_dict())
    _save_progress(project_dir, experiment_id, data)


def get_best_run(
    project_dir: Path,
    experiment_id: str,
    *,
    metric: str,
    direction: str,
) -> dict[str, Any] | None:
    """Return the best run by a given metric.

    Args:
        metric: The metric name to compare.
        direction: 'higher' or 'lower'.

    Returns:
        The best run dict, or None if no runs exist.
    """
    data = load_progress(project_dir, experiment_id)
    runs = data.get("runs", [])
    if not runs:
        return None

    valid = [r for r in runs if metric in r.get("metrics", {})]
    if not valid:
        return None

    if direction == "higher":
        return max(valid, key=lambda r: r["metrics"][metric])
    return min(valid, key=lambda r: r["metrics"][metric])


def update_experiment_status(
    project_dir: Path, experiment_id: str, status: str
) -> None:
    """Update the status field in progress.json."""
    data = load_progress(project_dir, experiment_id)
    data["status"] = status
    _save_progress(project_dir, experiment_id, data)
