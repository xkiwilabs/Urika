"""Best-per-method leaderboard with configurable primary metric."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from urika.core.json_io import load_json_or_preserve
from urika.evaluation.ranking import select_best_run

logger = logging.getLogger(__name__)

# The leaderboard artifact (leaderboard.json) keeps its historical
# "higher_is_better"/"lower_is_better" strings; ranking speaks
# "higher"/"lower".
_DIRECTION_WORDS = {"higher_is_better": "higher", "lower_is_better": "lower"}


def load_leaderboard(project_dir: Path) -> dict[str, Any]:
    """Load leaderboard.json from the project directory.

    Handles legacy format: if "ranking" is not present but "entries" is,
    rename "entries" to "ranking".
    """
    lb_path = project_dir / "leaderboard.json"
    data = load_json_or_preserve(lb_path, None)
    if data is None:
        return {"ranking": []}

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

    if primary_metric not in metrics:
        raise KeyError(primary_metric)

    new_entry: dict[str, Any] = {
        "rank": 0,  # Will be set after sorting
        "method": method,
        "run_id": run_id,
        "metrics": metrics,
        "params": params,
        "experiment_id": experiment_id,
    }

    # Find existing entry for this method
    existing_idx: int | None = None
    for i, entry in enumerate(ranking):
        if entry["method"] == method:
            existing_idx = i
            break

    if existing_idx is not None:
        existing = ranking[existing_idx]
        word = _DIRECTION_WORDS.get(direction)
        # Best-per-method via the canonical comparison; the existing
        # entry comes first so ties keep the incumbent (strict
        # improvement required, as before). Unknown direction strings
        # historically meant "never update".
        best = (
            select_best_run([existing, new_entry], primary_metric, direction=word)
            if word is not None
            else existing
        )
        if best is not new_entry:
            return

        # Remove old entry so we can insert the new one
        ranking.pop(existing_idx)

    ranking.append(new_entry)

    # Sort by primary metric (respecting direction)
    reverse = direction == "higher_is_better"
    missing = float("-inf") if reverse else float("inf")
    ranking.sort(
        key=lambda e: e["metrics"].get(primary_metric, missing), reverse=reverse
    )

    # Renumber ranks 1, 2, 3...
    for i, entry in enumerate(ranking):
        entry["rank"] = i + 1

    data["ranking"] = ranking
    data["updated"] = datetime.now(tz=timezone.utc).isoformat()
    data["primary_metric"] = primary_metric
    data["direction"] = direction

    lb_path = project_dir / "leaderboard.json"
    lb_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
