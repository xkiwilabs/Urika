"""Labbook generation: auto-generate .md summaries from progress data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from urika.core.experiment import list_experiments, load_experiment
from urika.core.progress import load_progress


def update_experiment_notes(project_dir: Path, experiment_id: str) -> None:
    """Regenerate the experiment's notes.md from progress.json runs."""
    exp = load_experiment(project_dir, experiment_id)
    progress = load_progress(project_dir, experiment_id)

    lines = [
        f"# Experiment: {exp.name}",
        "",
        f"**Hypothesis**: {exp.hypothesis}",
        "",
    ]

    for run in progress.get("runs", []):
        lines.append(f"## {run['run_id']}: {run['method']}")
        lines.append("")

        metrics = run.get("metrics", {})
        if metrics:
            metric_strs = [f"{k}={v}" for k, v in metrics.items()]
            lines.append(f"**Metrics**: {', '.join(metric_strs)}")

        params = run.get("params", {})
        if params:
            param_strs = [f"{k}={v}" for k, v in params.items()]
            lines.append(f"**Params**: {', '.join(param_strs)}")

        if run.get("hypothesis"):
            lines.append(f"- **Hypothesis**: {run['hypothesis']}")
        if run.get("observation"):
            lines.append(f"- **Observation**: {run['observation']}")
        if run.get("next_step"):
            lines.append(f"- **Next step**: {run['next_step']}")

        lines.append("")

    notes_path = project_dir / "experiments" / experiment_id / "labbook" / "notes.md"
    notes_path.write_text("\n".join(lines) + "\n")


def generate_experiment_summary(project_dir: Path, experiment_id: str) -> None:
    """Generate a summary.md for a completed experiment."""
    exp = load_experiment(project_dir, experiment_id)
    progress = load_progress(project_dir, experiment_id)
    runs = progress.get("runs", [])

    lines = [
        f"# Experiment Summary: {exp.name}",
        "",
        f"**Hypothesis**: {exp.hypothesis}",
        f"**Runs**: {len(runs)}",
        "",
    ]

    if runs:
        best = _find_best_run(runs)
        if best:
            lines.append(f"**Best run**: {best['run_id']} ({best['method']})")
            metrics_str = ", ".join(
                f"{k}={v}" for k, v in best.get("metrics", {}).items()
            )
            lines.append(f"**Best metrics**: {metrics_str}")
            lines.append("")

        metric_names = _all_metric_names(runs)
        lines.append("| Run | Method | " + " | ".join(metric_names) + " |")
        lines.append("|-----|--------|" + "|".join("---" for _ in metric_names) + "|")
        for run in runs:
            metrics = run.get("metrics", {})
            row = f"| {run['run_id']} | {run['method']} | "
            row += " | ".join(str(metrics.get(m, "")) for m in metric_names)
            row += " |"
            lines.append(row)
        lines.append("")

    observations = [r["observation"] for r in runs if r.get("observation")]
    if observations:
        lines.append("## Key Observations")
        lines.append("")
        for obs in observations:
            lines.append(f"- {obs}")
        lines.append("")

    summary_path = (
        project_dir / "experiments" / experiment_id / "labbook" / "summary.md"
    )
    summary_path.write_text("\n".join(lines) + "\n")


def generate_results_summary(project_dir: Path) -> None:
    """Generate the project-level results-summary.md."""
    experiments = list_experiments(project_dir)

    lines = [
        "# Results Summary",
        "",
    ]

    if not experiments:
        lines.append("No experiments completed yet.")
    else:
        lines.append("| Experiment | Best Method | Runs | Key Metrics |")
        lines.append("|------------|-------------|------|-------------|")

        for exp in experiments:
            progress = load_progress(project_dir, exp.experiment_id)
            runs = progress.get("runs", [])
            best = _find_best_run(runs)

            method = best["method"] if best else "—"
            metrics_str = ""
            if best:
                metrics_str = ", ".join(
                    f"{k}={v}" for k, v in best.get("metrics", {}).items()
                )

            lines.append(f"| {exp.name} | {method} | {len(runs)} | {metrics_str} |")
        lines.append("")

    path = project_dir / "labbook" / "results-summary.md"
    path.write_text("\n".join(lines) + "\n")


def generate_key_findings(project_dir: Path) -> None:
    """Generate the project-level key-findings.md."""
    from urika.core.workspace import load_project_config

    config = load_project_config(project_dir)
    experiments = list_experiments(project_dir)

    lines = [
        f"# Key Findings: {config.name}",
        "",
        f"**Question**: {config.question}",
        "",
    ]

    if not experiments:
        lines.append("No findings yet.")
    else:
        all_runs: list[tuple[str, dict[str, Any]]] = []
        for exp in experiments:
            progress = load_progress(project_dir, exp.experiment_id)
            for run in progress.get("runs", []):
                all_runs.append((exp.name, run))

        if all_runs:
            best_exp_name, best_run = all_runs[0]
            if best_run.get("metrics"):
                first_metric = next(iter(best_run["metrics"]))
                for exp_name, run in all_runs:
                    run_val = run.get("metrics", {}).get(first_metric, float("-inf"))
                    best_val = best_run["metrics"].get(first_metric, float("-inf"))
                    if run_val > best_val:
                        best_exp_name, best_run = exp_name, run

                metrics_str = ", ".join(
                    f"{k}={v}" for k, v in best_run["metrics"].items()
                )
                lines.append(
                    f"1. **Best result**: {best_run['method']} "
                    f"({metrics_str}) from {best_exp_name}"
                )

            lines.append(
                f"2. **Total runs**: {len(all_runs)} across "
                f"{len(experiments)} experiments"
            )
            lines.append("")

    path = project_dir / "labbook" / "key-findings.md"
    path.write_text("\n".join(lines) + "\n")


def _find_best_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the best run by the first metric (higher is better)."""
    if not runs:
        return None

    valid = [r for r in runs if r.get("metrics")]
    if not valid:
        return None

    first_metric = next(iter(valid[0]["metrics"]))
    return max(valid, key=lambda r: r["metrics"].get(first_metric, float("-inf")))


def _all_metric_names(runs: list[dict[str, Any]]) -> list[str]:
    """Collect all unique metric names across runs, preserving order."""
    seen: dict[str, None] = {}
    for run in runs:
        for key in run.get("metrics", {}):
            seen[key] = None
    return list(seen)
