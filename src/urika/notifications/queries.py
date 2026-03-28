"""Read-only project queries for notification channels."""

from __future__ import annotations

from pathlib import Path


def get_status_text(project_path: Path) -> str:
    """Return a plain-text project status summary."""
    import tomllib

    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    toml_path = project_path / "urika.toml"
    if not toml_path.exists():
        return "Project not found."

    with open(toml_path, "rb") as f:
        config = tomllib.load(f)

    name = config.get("project", {}).get("name", project_path.name)
    question = config.get("project", {}).get("question", "")
    mode = config.get("project", {}).get("mode", "")

    lines = [f"Project: {name}", f"Mode: {mode}"]
    if question:
        lines.append(f"Question: {question[:100]}")

    experiments = list_experiments(project_path)
    lines.append(f"Experiments: {len(experiments)}")
    for exp in experiments:
        progress = load_progress(project_path, exp.experiment_id)
        status = progress.get("status", "pending")
        runs = len(progress.get("runs", []))
        lines.append(f"  {exp.experiment_id} [{status}, {runs} runs]")

    return "\n".join(lines)


def get_results_text(project_path: Path) -> str:
    """Return a plain-text results/leaderboard summary."""
    import json

    leaderboard_path = project_path / "leaderboard.json"
    if not leaderboard_path.exists():
        return "No results yet."

    try:
        data = json.loads(leaderboard_path.read_text(encoding="utf-8"))
    except Exception:
        return "Error reading results."

    entries = data.get("ranking", data.get("entries", []))
    if not entries:
        return "No results yet."

    primary = data.get("primary_metric", "")
    lines = [f"Leaderboard ({primary}):" if primary else "Leaderboard:"]
    for entry in entries[:10]:
        rank = entry.get("rank", "")
        method = entry.get("method", "?")
        metrics = entry.get("metrics", {})
        metric_str = ", ".join(f"{k}={v}" for k, v in list(metrics.items())[:3])
        lines.append(f"  {rank}. {method} -- {metric_str}")

    return "\n".join(lines)
