"""Best-per-method leaderboard with configurable primary metric."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_leaderboard(project_dir: Path) -> dict[str, Any]:
    """Load leaderboard.json from the project directory.

    Handles legacy format: if "ranking" is not present but "entries" is,
    rename "entries" to "ranking".
    """
    lb_path = project_dir / "leaderboard.json"
    if not lb_path.exists():
        return {"ranking": []}

    data = json.loads(lb_path.read_text(encoding="utf-8"))

    # Legacy format migration: rename "entries" -> "ranking"
    if "ranking" not in data and "entries" in data:
        data["ranking"] = data.pop("entries")

    if "ranking" not in data:
        data["ranking"] = []

    return data


def update_leaderboard(
    project_dir: Path,
    method: str,
    metrics: dict[str, float],
    run_id: str,
    params: dict[str, Any],
    *,
    primary_metric: str,
    direction: str,
    experiment_id: str = "",
) -> None:
    """Update the leaderboard with a new run result.

    Best-per-method: only updates if the new run beats the current best
    for that method on the primary metric. Sorts ranking by primary metric
    (respecting direction) and renumbers ranks.
    """
    data = load_leaderboard(project_dir)
    ranking: list[dict[str, Any]] = data["ranking"]

    new_value = metrics[primary_metric]

    # Find existing entry for this method
    existing_idx: int | None = None
    for i, entry in enumerate(ranking):
        if entry["method"] == method:
            existing_idx = i
            break

    if existing_idx is not None:
        old_value = ranking[existing_idx]["metrics"][primary_metric]
        should_update = False
        if direction == "higher_is_better" and new_value > old_value:
            should_update = True
        elif direction == "lower_is_better" and new_value < old_value:
            should_update = True

        if not should_update:
            return

        # Remove old entry so we can insert the new one
        ranking.pop(existing_idx)

    new_entry: dict[str, Any] = {
        "rank": 0,  # Will be set after sorting
        "method": method,
        "run_id": run_id,
        "metrics": metrics,
        "params": params,
        "experiment_id": experiment_id,
    }
    ranking.append(new_entry)

    # Sort by primary metric (respecting direction)
    reverse = direction == "higher_is_better"
    missing = float("-inf") if reverse else float("inf")
    ranking.sort(key=lambda e: e["metrics"].get(primary_metric, missing), reverse=reverse)

    # Renumber ranks 1, 2, 3...
    for i, entry in enumerate(ranking):
        entry["rank"] = i + 1

    data["ranking"] = ranking
    data["updated"] = datetime.now(tz=timezone.utc).isoformat()
    data["primary_metric"] = primary_metric
    data["direction"] = direction

    lb_path = project_dir / "leaderboard.json"
    lb_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
