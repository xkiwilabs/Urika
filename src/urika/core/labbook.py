"""Labbook generation: auto-generate .md summaries from progress data."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from urika.core.experiment import list_experiments, load_experiment
from urika.core.method_glossary import explain_method
from urika.core.models import ProjectConfig
from urika.core.progress import load_progress
from urika.evaluation.ranking import LOWER_IS_BETTER, select_best_run


def _project_audience(project_dir: Path, config: ProjectConfig | None = None) -> str:
    """Resolve the project audience: a caller-provided config wins,
    otherwise read urika.toml. Anything unreadable → "standard"."""
    if config is not None:
        return config.audience
    try:
        from urika.core.workspace import load_project_config

        return load_project_config(project_dir).audience
    except Exception:
        return "standard"


def update_experiment_notes(
    project_dir: Path,
    experiment_id: str,
    *,
    config: ProjectConfig | None = None,
) -> None:
    """Regenerate the experiment's notes.md from progress.json runs."""
    exp = load_experiment(project_dir, experiment_id)
    progress = load_progress(project_dir, experiment_id)
    audience = _project_audience(project_dir, config)

    lines = [
        f"# Experiment: {exp.name}",
        "",
        f"**Hypothesis**: {exp.hypothesis}",
        "",
    ]

    # Collect all artifact figures for inline matching
    all_figures = _collect_experiment_figures(project_dir, experiment_id)
    figure_names = {f.stem.lower(): f for f in all_figures}

    for run in progress.get("runs", []):
        run_id = run.get("run_id", "unknown")
        method = run.get("method", "unknown")
        lines.append(f"## {run_id}: {method}")
        lines.append("")

        if audience == "novice":
            explainer = explain_method(method)
            if explainer:
                lines.append(f"*What this method does:* {explainer}")
                lines.append("")

        metrics = run.get("metrics", {})
        if metrics:
            lines.append(f"**Metrics**: {_format_metrics_with_interpretation(run)}")

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

        # Inline figures: run-id-tagged figures (e.g. ``run-002-scatter.png``)
        # attach to that run first; the method-name substring heuristic is
        # only the fallback when no run-id-tagged figure exists for the run.
        run_id_lower = str(run_id).lower()
        _run_id_pat = re.compile(re.escape(run_id_lower) + r"(?!\d)")
        matched = [
            fpath
            for fname, fpath in figure_names.items()
            if run.get("run_id") and _run_id_pat.search(fname)
        ]
        if not matched:
            method_lower = run["method"].lower()
            for fname, fpath in figure_names.items():
                if method_lower in fname or fname in method_lower:
                    matched.append(fpath)
        # Also check run artifacts list
        for art in run.get("artifacts", []):
            art_path = Path(art)
            if art_path.suffix.lower() in (
                ".png",
                ".jpg",
                ".jpeg",
                ".svg",
                ".gif",
            ) and art_path.name.lower() not in [m.name.lower() for m in matched]:
                if (project_dir / "experiments" / experiment_id / art).exists():
                    matched.append(project_dir / "experiments" / experiment_id / art)
        for fig in matched[:3]:  # Max 3 figures per run
            caption = _caption_from_filename(fig.name)
            lines.append("")
            lines.append(f"![{caption}](../artifacts/{fig.name})")

        lines.append("")

    notes_path = project_dir / "experiments" / experiment_id / "labbook" / "notes.md"
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
            lines.append(
                f"**Best metrics**: {_format_metrics_with_interpretation(best)}"
            )
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

    # Embed artifact figures
    figures = _collect_experiment_figures(project_dir, experiment_id)
    if figures:
        lines.append("## Figures")
        lines.append("")
        for fig_path in figures:
            caption = _caption_from_filename(fig_path.name)
            lines.append(f"![{caption}](../artifacts/{fig_path.name})")
            lines.append("")

    summary_path = (
        project_dir / "experiments" / experiment_id / "labbook" / "summary.md"
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    path = project_dir / "projectbook" / "results-summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_key_findings(project_dir: Path) -> None:
    """Generate the project-level key-findings.md."""
    import json

    from urika.core.workspace import load_project_config

    config = load_project_config(project_dir)
    experiments = list_experiments(project_dir)

    lines = [
        f"# Key Findings: {config.name}",
        "",
    ]

    # --- Project Overview ---
    lines.append("## Project Overview")
    lines.append("")
    lines.append(f"**Name**: {config.name}")
    lines.append(f"**Question**: {config.question}")
    if config.description:
        lines.append(f"**Description**: {config.description}")
    lines.append(f"**Mode**: {config.mode}")
    lines.append("")

    # --- Experiments ---
    lines.append("## Experiments")
    lines.append("")
    if not experiments:
        lines.append("No experiments yet.")
        lines.append("")
    else:
        lines.append("| Experiment | Status | Runs |")
        lines.append("|------------|--------|------|")
        for exp in experiments:
            progress = load_progress(project_dir, exp.experiment_id)
            runs = progress.get("runs", [])
            status = progress.get("status", "pending")
            lines.append(f"| {exp.name} | {status} | {len(runs)} |")
        lines.append("")

    # --- Methods Tried ---
    methods_path = project_dir / "methods.json"
    if methods_path.exists():
        try:
            mdata = json.loads(methods_path.read_text(encoding="utf-8"))
            mlist = mdata.get("methods", [])
            if mlist:
                lines.append("## Methods Tried")
                lines.append("")
                lines.append("| Method | Experiment | Metrics |")
                lines.append("|--------|-----------|---------|")
                for m in mlist:
                    metrics_str = ", ".join(
                        f"{k}={v}" for k, v in m.get("metrics", {}).items()
                    )
                    lines.append(
                        f"| {m.get('name', '?')} "
                        f"| {m.get('experiment', '')} "
                        f"| {metrics_str} |"
                    )
                lines.append("")
        except (json.JSONDecodeError, KeyError):
            pass

    # --- Current Criteria ---
    criteria_path = project_dir / "criteria.json"
    if criteria_path.exists():
        try:
            cdata = json.loads(criteria_path.read_text(encoding="utf-8"))
            versions = cdata.get("versions", [])
            if versions:
                latest = versions[-1]
                lines.append("## Current Criteria")
                lines.append("")
                ctype = latest.get("criteria", {}).get("type", "unknown")
                lines.append(f"Type: {ctype} (v{latest.get('version', '?')})")
                threshold = latest.get("criteria", {}).get("threshold", {})
                primary = threshold.get("primary", {})
                if primary:
                    for metric, val in primary.items():
                        lines.append(f"- {metric}: {val}")
                lines.append("")
        except (json.JSONDecodeError, KeyError):
            pass

    # --- Key Findings ---
    lines.append("## Key Findings")
    lines.append("")

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
                picked = select_best_run((run for _, run in all_runs), first_metric)
                if picked is not None:
                    for exp_name, run in all_runs:
                        if run is picked:
                            best_exp_name, best_run = exp_name, run
                            break

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

    # Embed figures from all experiments
    all_figures: list[tuple[str, Path]] = []
    for exp in experiments:
        for fig in _collect_experiment_figures(project_dir, exp.experiment_id):
            all_figures.append((exp.experiment_id, fig))

    if all_figures:
        lines.append("## Figures")
        lines.append("")
        for exp_id, fig_path in all_figures:
            caption = _caption_from_filename(fig_path.name)
            lines.append(
                f"![{caption}](../experiments/{exp_id}/artifacts/{fig_path.name})"
            )
            lines.append("")

    path = project_dir / "projectbook" / "key-findings.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Backwards-compat alias: cli/run_planning.py and tests import this name.
# The canonical set lives in urika.evaluation.ranking.
_LOWER_IS_BETTER = LOWER_IS_BETTER


def _find_best_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the best run by the first metric, respecting metric direction.

    First-metric-only is this function's historical contract (the first
    metric of the first run with metrics drives the comparison); the
    direction inference and comparison itself delegate to
    ``urika.evaluation.ranking``.
    """
    if not runs:
        return None

    valid = [r for r in runs if r.get("metrics")]
    if not valid:
        return None

    first_metric = next(iter(valid[0]["metrics"]))
    return select_best_run(valid, first_metric)


def _format_metrics_with_interpretation(run: dict[str, Any]) -> str:
    """Format a run's metrics as ``k=v`` pairs, appending the run's
    plain-language interpretation where one exists for the metric:
    ``r2=0.74 — Explains 74% of variance...``.

    Runs without ``metric_interpretation`` (every record pre-v0.8)
    render exactly as before: ``k=v, k=v``.
    """
    interpretations = run.get("metric_interpretation") or {}
    parts: list[str] = []
    for k, v in run.get("metrics", {}).items():
        interp = interpretations.get(k, "") if isinstance(interpretations, dict) else ""
        parts.append(f"{k}={v} — {interp}" if interp else f"{k}={v}")
    return ", ".join(parts)


def _all_metric_names(runs: list[dict[str, Any]]) -> list[str]:
    """Collect all unique metric names across runs, preserving order."""
    seen: dict[str, None] = {}
    for run in runs:
        for key in run.get("metrics", {}):
            seen[key] = None
    return list(seen)


_MAX_FIGURES_PER_EXPERIMENT = 10


def _collect_experiment_figures(project_dir: Path, experiment_id: str) -> list[Path]:
    """Return sorted figure files from an experiment's artifacts dir (max 10)."""
    artifacts_dir = project_dir / "experiments" / experiment_id / "artifacts"
    if not artifacts_dir.is_dir():
        return []
    figures: list[Path] = []
    for ext in (".png", ".jpg", ".jpeg", ".svg", ".gif"):
        figures.extend(artifacts_dir.glob(f"*{ext}"))
    figures.sort()
    return figures[:_MAX_FIGURES_PER_EXPERIMENT]


def _caption_from_filename(filename: str) -> str:
    """Derive a human-readable caption from a filename.

    Strips the extension and replaces underscores with spaces.
    The first letter is capitalised; the rest is left as-is.
    """
    stem = Path(filename).stem
    caption = stem.replace("_", " ")
    return caption[0].upper() + caption[1:] if caption else caption
