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
        logger.warning(
            "methods.json top-level is not a dict (%s); ignoring", type(data).__name__
        )
        return []
    raw = data.get("methods", [])
    if not isinstance(raw, list):
        logger.warning(
            "methods.json 'methods' is not a list (%s); ignoring", type(raw).__name__
        )
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
    """Register or update a method in the project registry.

    An entry's ``metrics`` / ``script`` / ``experiment`` / ``turn`` /
    ``description`` always describe the method's **best** run so far
    (by its headline metric, see ``evaluation.ranking``). Re-registering
    after a worse run only bumps ``last_experiment`` / ``last_turn`` /
    ``run_count``; it never erases the better result.
    """
    path = _methods_path(project_dir)
    with locked_json_update(path):
        methods = load_methods(project_dir)

        # load_methods already filters malformed entries, so plain
        # m["name"] would be safe — but use .get() defensively in case
        # something writes between the load and the iteration.
        for m in methods:
            if m.get("name") == name:
                m["last_experiment"] = experiment
                m["last_turn"] = turn
                m["run_count"] = int(m.get("run_count", 1)) + 1
                if _is_better_run(metrics, m.get("metrics")):
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
                "last_experiment": experiment,
                "last_turn": turn,
                "run_count": 1,
            }
        )
        _save_methods(project_dir, methods)


def _is_better_run(new: dict[str, Any] | None, old: dict[str, Any] | None) -> bool:
    """True when *new* metrics should replace *old* as the method's best run.

    Compared on the old entry's headline metric so the yardstick does
    not drift between runs. An entry without a numeric metric is always
    replaced; a new run lacking the yardstick metric never replaces.
    """
    from urika.evaluation.ranking import detect_primary_metric, select_best_run

    old = old if isinstance(old, dict) else {}
    new = new if isinstance(new, dict) else {}
    primary, direction = detect_primary_metric(old)
    if not primary:
        return True
    best = select_best_run(
        [{"metrics": old}, {"metrics": new}], primary, direction=direction
    )
    # Ties resolve to the first candidate (old), so only a strict
    # improvement replaces.
    return best is not None and best["metrics"] is new


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


def mark_final_methods(
    project_dir: Path,
    final_names: list[str],
    *,
    primary: str | None,
) -> int:
    """Record the finalizer's selection in the registry.

    Methods named in *final_names* become ``final``; every other
    registered method becomes ``superseded`` by *primary* (the primary
    final method, or the first final name). Returns the number of
    entries whose status or ``superseded_by`` changed, so a repeat call
    is a no-op returning 0. Unknown names are ignored. If no final name
    matches a registered method nothing is changed.
    """
    wanted = {n for n in final_names if isinstance(n, str) and n}
    path = _methods_path(project_dir)
    with locked_json_update(path):
        methods = load_methods(project_dir)
        if not any(m.get("name") in wanted for m in methods):
            return 0
        by = primary if primary in wanted else next(iter(sorted(wanted)))
        changed = 0
        for m in methods:
            if m.get("name") in wanted:
                new_status, new_by = "final", None
            else:
                new_status, new_by = "superseded", by
            if m.get("status") != new_status or m.get("superseded_by") != new_by:
                m["status"] = new_status
                m["superseded_by"] = new_by
                changed += 1
        if changed:
            _save_methods(project_dir, methods)
        return changed


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
