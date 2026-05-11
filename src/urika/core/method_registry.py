"""Project method registry — tracks methods created by agents."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from urika.core.atomic_write import write_json_atomic
from urika.core.filelock import locked_json_update

logger = logging.getLogger(__name__)


def _methods_path(project_dir: Path) -> Path:
    return project_dir / "methods.json"


def load_methods(project_dir: Path) -> list[dict[str, Any]]:
    """Load all registered methods.

    Defensive against external writers (e.g. an agent that edited
    methods.json directly): the file's top level may not be a dict,
    "methods" may not be a list, and individual entries may be missing
    "name". Drop anything that doesn't look like a registered method
    rather than letting downstream readers KeyError.
    """
    path = _methods_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Corrupt JSON in %s: %s", path, exc)
        return []
    if not isinstance(data, dict):
        logger.warning("methods.json top-level is not a dict (%s); ignoring", type(data).__name__)
        return []
    raw = data.get("methods", [])
    if not isinstance(raw, list):
        logger.warning("methods.json 'methods' is not a list (%s); ignoring", type(raw).__name__)
        return []
    clean: list[dict[str, Any]] = []
    for m in raw:
        if isinstance(m, dict) and isinstance(m.get("name"), str):
            clean.append(m)
        else:
            logger.warning("Dropping malformed methods.json entry: %r", m)
    return clean


def _save_methods(project_dir: Path, methods: list[dict[str, Any]]) -> None:
    path = _methods_path(project_dir)
    write_json_atomic(path, {"methods": methods})


def register_method(
    project_dir: Path,
    *,
    name: str,
    description: str,
    script: str,
    experiment: str,
    turn: int,
    metrics: dict[str, Any],
    status: str = "active",
) -> None:
    """Register or update a method in the project registry."""
    path = _methods_path(project_dir)
    with locked_json_update(path):
        methods = load_methods(project_dir)

        # load_methods already filters malformed entries, so plain
        # m["name"] would be safe — but use .get() defensively in case
        # something writes between the load and the iteration.
        for m in methods:
            if m.get("name") == name:
                m["description"] = description
                m["script"] = script
                m["experiment"] = experiment
                m["turn"] = turn
                m["metrics"] = metrics
                _save_methods(project_dir, methods)
                return

        methods.append(
            {
                "name": name,
                "description": description,
                "script": script,
                "created_by": "task_agent",
                "experiment": experiment,
                "turn": turn,
                "metrics": metrics,
                "status": status,
                "superseded_by": None,
            }
        )
        _save_methods(project_dir, methods)


def get_best_method(
    project_dir: Path, *, metric: str, direction: str
) -> dict[str, Any] | None:
    """Return the best method by a given metric."""
    methods = load_methods(project_dir)
    valid = [m for m in methods if metric in m.get("metrics", {})]
    if not valid:
        return None
    if direction == "higher":
        return max(valid, key=lambda m: m["metrics"][metric])
    return min(valid, key=lambda m: m["metrics"][metric])


def update_method_status(
    project_dir: Path,
    name: str,
    status: str,
    *,
    superseded_by: str | None = None,
) -> None:
    """Update a method's status."""
    path = _methods_path(project_dir)
    with locked_json_update(path):
        methods = load_methods(project_dir)
        for m in methods:
            if m.get("name") == name:
                m["status"] = status
                if superseded_by is not None:
                    m["superseded_by"] = superseded_by
                _save_methods(project_dir, methods)
                return
