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


def get_methods_text(project_path: Path) -> str:
    """Return plain-text methods registry summary."""
    from urika.core.method_registry import load_methods

    methods = load_methods(project_path)
    if not methods:
        return "No methods yet."

    lines = [f"Methods ({len(methods)}):"]
    for m in methods:
        name = m.get("name", "?")
        status = m.get("status", "?")
        metrics = m.get("metrics", {})
        metric_str = ", ".join(f"{k}={v}" for k, v in list(metrics.items())[:3])
        line = f"  {name} [{status}]"
        if metric_str:
            line += f" -- {metric_str}"
        lines.append(line)

    return "\n".join(lines)


def get_criteria_text(project_path: Path) -> str:
    """Return plain-text current criteria summary."""
    from urika.core.criteria import load_criteria

    current = load_criteria(project_path)
    if current is None:
        return "No criteria set."

    lines = [f"Criteria (v{current.version}, set by {current.set_by}):"]
    if current.rationale:
        lines.append(f"  Rationale: {current.rationale[:100]}")
    for key, value in current.criteria.items():
        lines.append(f"  {key}: {value}")

    return "\n".join(lines)


def get_experiments_text(project_path: Path) -> str:
    """Return plain-text experiment list with status and run counts."""
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    experiments = list_experiments(project_path)
    if not experiments:
        return "Experiments: 0"

    lines = [f"Experiments ({len(experiments)}):"]
    for exp in experiments:
        progress = load_progress(project_path, exp.experiment_id)
        status = progress.get("status", "pending")
        runs = len(progress.get("runs", []))
        lines.append(f"  {exp.experiment_id}: {exp.name} [{status}, {runs} runs]")

    return "\n".join(lines)


def get_usage_text(project_path: Path) -> str:
    """Return plain-text usage stats summary."""
    from urika.core.usage import load_usage

    data = load_usage(project_path)
    totals = data.get("totals", {})

    sessions = totals.get("sessions", 0)
    if sessions == 0:
        return "No usage data."

    total_tokens = totals.get("total_tokens_in", 0) + totals.get("total_tokens_out", 0)
    total_cost = totals.get("total_cost_usd", 0.0)
    total_calls = totals.get("total_agent_calls", 0)
    total_exps = totals.get("total_experiments", 0)

    lines = [
        "Usage:",
        f"  Sessions: {sessions}",
        f"  Tokens: {total_tokens}",
        f"  Cost: ~${total_cost:.2f}",
        f"  Agent calls: {total_calls}",
        f"  Experiments: {total_exps}",
    ]
    return "\n".join(lines)


def get_logs_text(project_path: Path, experiment_id: str = "") -> str:
    """Return plain-text run logs for an experiment.

    If no experiment_id is given, uses the most recent experiment.
    Shows the last 5 runs with method, metrics, and observation (truncated).
    """
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    if not experiment_id:
        experiments = list_experiments(project_path)
        if not experiments:
            return "No experiments found."
        experiment_id = experiments[-1].experiment_id

    progress = load_progress(project_path, experiment_id)
    runs = progress.get("runs", [])
    if not runs:
        return "No logs."

    last_runs = runs[-5:]
    lines = [f"Logs for {experiment_id} (last {len(last_runs)} of {len(runs)} runs):"]
    for run in last_runs:
        method = run.get("method", "?")
        metrics = run.get("metrics", {})
        observation = run.get("observation", "")
        metric_str = ", ".join(f"{k}={v}" for k, v in list(metrics.items())[:3])
        line = f"  {method}"
        if metric_str:
            line += f" -- {metric_str}"
        if observation:
            obs = observation[:200]
            if len(observation) > 200:
                obs += "..."
            line += f"\n    {obs}"
        lines.append(line)

    return "\n".join(lines)
