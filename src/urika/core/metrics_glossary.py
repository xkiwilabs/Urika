"""Per-project metrics glossary — ``projectbook/METRICS.md``.

``urika finalize`` calls :func:`write_metrics_glossary` (pure code, no
agent) to document every metric name that appears in progress.json run
records across the project's experiments. Known metrics get a
plain-language definition, range, and how-to-read guidance from the
static :data:`METRIC_GLOSSARY` (written for a behavioral-science
audience); direction comes from :func:`urika.evaluation.ranking.
metric_direction` and the best observed value from
:func:`urika.evaluation.ranking.select_best_run` — the same single
source of truth the labbook, leaderboard, and README use. Unknown
metrics get an observed-range-only section: the glossary never invents
a definition or a direction for a metric it doesn't recognize.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from urika.core.labbook import _format_ci
from urika.core.progress import load_progress
from urika.core.report_writer import write_versioned
from urika.evaluation.ranking import metric_direction, select_best_run

logger = logging.getLogger(__name__)

# Static seed glossary. Each entry: a plain-language definition, the
# metric's range, and how to read it (including when to worry) —
# written for researchers in behavioral / cognitive science.
METRIC_GLOSSARY: dict[str, dict[str, str]] = {
    "r2": {
        "definition": (
            "R² (coefficient of determination) — the proportion of "
            "variance in the outcome that the model accounts for. An R² "
            "of 0.4 means the model explains 40% of the variability in "
            "the outcome; the remaining 60% is unexplained (individual "
            "differences, measurement noise, missing predictors)."
        ),
        "range": (
            "0 to 1 in ordinary use. On held-out data a model can score "
            "below 0 — that means it predicts worse than simply guessing "
            "the mean outcome for everyone."
        ),
        "how_to_read": (
            "Higher is better. Behavioral data are noisy, so an R² above "
            "~0.3 is often already respectable. Be suspicious of values "
            "approaching 1.0: they usually signal leakage (a predictor "
            "that encodes the outcome) or evaluation on the training data "
            "rather than a genuinely strong effect. Always check whether "
            "the value comes from training or held-out data."
        ),
    },
    "rmse": {
        "definition": (
            "Root mean squared error — the typical size of the model's "
            "prediction errors, expressed in the same units as the "
            "outcome. Errors are squared before averaging, so RMSE is "
            "pulled upward by occasional large misses."
        ),
        "range": (
            "0 upward, in outcome units. 0 means perfect prediction; "
            "there is no universal 'good' value — judge it against the "
            "outcome's spread."
        ),
        "how_to_read": (
            "Lower is better. Compare it to the outcome's standard "
            "deviation: an RMSE close to the SD means the model barely "
            "beats predicting the mean. A near-zero training RMSE with a "
            "much larger held-out RMSE means overfitting. If RMSE is much "
            "larger than MAE on the same runs, a few large errors "
            "dominate — inspect the worst-predicted cases."
        ),
    },
    "mse": {
        "definition": (
            "Mean squared error — the average of squared prediction "
            "errors. It carries the same information as RMSE but in "
            "squared outcome units, which makes it awkward to interpret "
            "directly; it mostly appears as an optimization target."
        ),
        "range": "0 upward, in squared outcome units. 0 means perfect prediction.",
        "how_to_read": (
            "Lower is better. For judging practical accuracy, read RMSE "
            "(its square root) instead — that is in the outcome's own "
            "units. The same overfitting and outlier caveats as RMSE "
            "apply."
        ),
    },
    "mae": {
        "definition": (
            "Mean absolute error — the average absolute size of the "
            "prediction errors, in outcome units. Unlike RMSE it treats "
            "all errors proportionally, so it is not dominated by "
            "occasional large misses."
        ),
        "range": "0 upward, in outcome units. 0 means perfect prediction.",
        "how_to_read": (
            "Lower is better. Read it as 'on average, predictions are "
            "off by this much'. A large gap between MAE and RMSE flags a "
            "heavy-tailed error distribution — a handful of cases the "
            "model predicts badly."
        ),
    },
    "accuracy": {
        "definition": (
            "The proportion of cases the classifier labels correctly, "
            "across all classes."
        ),
        "range": "0 to 1 (often reported as 0–100%).",
        "how_to_read": (
            "Higher is better — but always read it against the base "
            "rate. If 90% of cases belong to one class, an accuracy of "
            "0.90 is achievable by always predicting that class. With "
            "imbalanced groups (e.g., rare clinical cases), prefer "
            "precision, recall, F1, or AUC."
        ),
    },
    "precision": {
        "definition": (
            "Of the cases the model flagged as positive, the proportion "
            "that truly are positive — how trustworthy a positive call "
            "is."
        ),
        "range": "0 to 1.",
        "how_to_read": (
            "Higher is better. Low precision means many false alarms. "
            "Read it together with recall: pushing one up usually drags "
            "the other down, so decide which error costs more in your "
            "design before preferring one model over another."
        ),
    },
    "recall": {
        "definition": (
            "Of the truly positive cases, the proportion the model "
            "found — also called sensitivity or hit rate."
        ),
        "range": "0 to 1.",
        "how_to_read": (
            "Higher is better. Low recall means many misses. A recall of "
            "1.0 on its own is trivial (flag everything as positive), so "
            "always check precision alongside it."
        ),
    },
    "f1": {
        "definition": (
            "The harmonic mean of precision and recall — a single score "
            "that balances false alarms against misses."
        ),
        "range": "0 to 1.",
        "how_to_read": (
            "Higher is better. Useful when classes are imbalanced and "
            "plain accuracy misleads. Because the harmonic mean punishes "
            "imbalance, a high F1 requires BOTH precision and recall to "
            "be high. Note it ignores true negatives entirely."
        ),
    },
    "auc": {
        "definition": (
            "Area under the ROC curve — the probability that the model "
            "ranks a randomly chosen positive case above a randomly "
            "chosen negative one. A threshold-free measure of how well "
            "the model separates the classes."
        ),
        "range": (
            "0.5 (chance-level ranking) to 1 (perfect separation). "
            "Below 0.5 means worse than chance — often a sign that "
            "labels or predictions are inverted."
        ),
        "how_to_read": (
            "Higher is better. Rough guide for behavioral data: ~0.7 "
            "modest, ~0.8 good, 0.9+ strong — and values very close to "
            "1.0 warrant a leakage check. AUC says nothing about whether "
            "the predicted probabilities themselves are calibrated."
        ),
    },
    "p_value": {
        "definition": (
            "The probability of observing data at least this extreme if "
            "the null hypothesis (no effect) were true. It is NOT the "
            "probability that the effect is real, large, or important."
        ),
        "range": "0 to 1.",
        "how_to_read": (
            "Lower means stronger evidence against the null — but with a "
            "large sample, a tiny p-value can accompany a trivially "
            "small effect. Interpret effect sizes (e.g., Cohen's d) with "
            "confidence intervals alongside any p-value, and be wary of "
            "p-values that only clear 0.05 after many model variants "
            "were tried (multiple-comparisons inflation)."
        ),
    },
    "cohens_d": {
        "definition": (
            "Cohen's d — the standardized mean difference between two "
            "groups or conditions: the difference in means divided by "
            "the pooled standard deviation. An effect size in SD units, "
            "comparable across studies and measures."
        ),
        "range": (
            "Unbounded; the sign gives the direction. Conventional "
            "magnitude labels: ~0.2 small, ~0.5 medium, ~0.8 large — "
            "context-dependent rules of thumb, not laws."
        ),
        "how_to_read": (
            "Larger magnitude means a bigger effect. Always read d with "
            "its confidence interval: d = 0.5 with a CI spanning 0 is "
            "weak evidence. Small-sample estimates of d are noisy and "
            "systematically inflated among 'significant' results."
        ),
    },
    "log_loss": {
        "definition": (
            "Log loss (cross-entropy) — scores a probabilistic "
            "classifier by how much probability it assigned to the true "
            "class, punishing confident wrong predictions heavily."
        ),
        "range": (
            "0 upward. 0 is perfect; a two-class model that always says "
            "50/50 scores about 0.693, so anything above that is worse "
            "than expressing no opinion."
        ),
        "how_to_read": (
            "Lower is better. Log loss rewards calibrated probabilities, "
            "not just correct labels — a model can have good accuracy "
            "and poor log loss if it is overconfident. Spikes usually "
            "trace to a few cases where the model was confidently wrong."
        ),
    },
    "silhouette": {
        "definition": (
            "Silhouette score — how well each observation fits its "
            "assigned cluster compared to the nearest other cluster, "
            "averaged over all observations."
        ),
        "range": (
            "-1 to +1. Near 0 means overlapping clusters; negative "
            "values mean points are closer to another cluster than to "
            "their own."
        ),
        "how_to_read": (
            "Higher is better. Above ~0.5 suggests reasonably separated "
            "clusters; below ~0.25 the 'clusters' may be an artifact of "
            "the algorithm rather than real subgroups in the data. "
            "Compare the score across different cluster counts before "
            "trusting any single solution."
        ),
    },
    "aic": {
        "definition": (
            "Akaike information criterion — model fit penalized by the "
            "number of parameters. Used to compare candidate models "
            "fitted to the SAME data; it balances explanatory power "
            "against complexity."
        ),
        "range": (
            "Unbounded and scale-dependent: the absolute value is "
            "meaningless on its own — only differences between models "
            "on the same data matter."
        ),
        "how_to_read": (
            "Lower is better. A difference below ~2 means the models are "
            "essentially equivalent; above ~10 is strong preference for "
            "the lower-AIC model. Never compare AIC across different "
            "datasets or differently transformed outcomes."
        ),
    },
    "bic": {
        "definition": (
            "Bayesian information criterion — like AIC, but with a "
            "stronger complexity penalty that grows with sample size, so "
            "it favors simpler models."
        ),
        "range": (
            "Unbounded and scale-dependent; only differences between "
            "models fitted to the same data are interpretable."
        ),
        "how_to_read": (
            "Lower is better. BIC choosing a simpler model than AIC does "
            "is common and expected. The same caveats as AIC apply: "
            "compare only across models of the same data and outcome."
        ),
    },
}

# Common spelling variants → canonical glossary keys.
_ALIASES: dict[str, str] = {
    "roc_auc": "auc",
    "auroc": "auc",
    "auc_roc": "auc",
    "r_squared": "r2",
    "rsquared": "r2",
    "r_square": "r2",
    "pvalue": "p_value",
    "p_val": "p_value",
    "cohen_d": "cohens_d",
    "cohen_s_d": "cohens_d",
    "f1_score": "f1",
    "logloss": "log_loss",
    "silhouette_score": "silhouette",
    "mean_absolute_error": "mae",
    "mean_squared_error": "mse",
    "root_mean_squared_error": "rmse",
}

_NO_NUMERIC = "No numeric values were recorded for this metric."


def lookup_metric(name: str) -> dict[str, str] | None:
    """The :data:`METRIC_GLOSSARY` entry for a metric name, or None.

    Case/separator-insensitive; alias-aware (``roc_auc`` → ``auc``);
    suffix-aware like :func:`metric_direction` (``val_rmse`` → ``rmse``).
    """
    if not name:
        return None
    key = re.sub(r"[\s\-]+", "_", name.strip().lower())
    if key in METRIC_GLOSSARY:
        return METRIC_GLOSSARY[key]
    if key in _ALIASES:
        return METRIC_GLOSSARY[_ALIASES[key]]
    for base in METRIC_GLOSSARY:
        if key.endswith(f"_{base}"):
            return METRIC_GLOSSARY[base]
    for alias, base in _ALIASES.items():
        if key.endswith(f"_{alias}"):
            return METRIC_GLOSSARY[base]
    return None


def write_metrics_glossary(project_dir: Path) -> Path | None:
    """Render ``projectbook/METRICS.md`` from observed runs (versioned).

    Returns the written path, or None (writing nothing) when no run
    across any experiment carries a metric.
    """
    runs = _collect_runs(project_dir)
    metric_names = _observed_metric_names(runs)
    if not metric_names:
        return None

    lines: list[str] = [
        "# Metrics Glossary",
        "",
        "Auto-generated by `urika finalize` from this project's recorded "
        "runs. Definitions are general; observed ranges and best values "
        "are computed from the run records in each experiment's "
        "progress.json.",
        "",
    ]
    for name in metric_names:
        lines.extend(_render_section(name, runs))

    path = project_dir / "projectbook" / "METRICS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_versioned(path, "\n".join(lines))
    return path


def _collect_runs(project_dir: Path) -> list[dict[str, Any]]:
    """All run dicts across experiments, annotated with their
    experiment id under ``_experiment_id`` (for best-run provenance)."""
    experiments_dir = project_dir / "experiments"
    if not experiments_dir.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for exp_dir in sorted(experiments_dir.iterdir()):
        if not exp_dir.is_dir():
            continue
        for run in load_progress(project_dir, exp_dir.name).get("runs", []):
            if isinstance(run, dict):
                runs.append({**run, "_experiment_id": exp_dir.name})
    return runs


def _observed_metric_names(runs: list[dict[str, Any]]) -> list[str]:
    """Unique metric names across runs, in first-seen order."""
    seen: dict[str, None] = {}
    for run in runs:
        metrics = run.get("metrics")
        if isinstance(metrics, dict):
            for key in metrics:
                seen[str(key)] = None
    return list(seen)


def _numeric_values(runs: list[dict[str, Any]], name: str) -> list[float]:
    values: list[float] = []
    for run in runs:
        metrics = run.get("metrics")
        if not isinstance(metrics, dict):
            continue
        value = metrics.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        values.append(float(value))
    return values


def _fmt(value: float) -> str:
    return f"{value:g}"


def _render_section(name: str, runs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = [f"## {name}", ""]
    entry = lookup_metric(name)
    values = _numeric_values(runs, name)

    if entry is None:
        # Unknown metric: observed range only — never invent a
        # definition or a direction.
        lines.append(
            "Project-specific metric — not in Urika's built-in glossary. "
            "Interpret it using the run records and labbook notes that "
            "produced it."
        )
        lines.append("")
        if values:
            lines.append(
                f"**Observed in this project.** {_fmt(min(values))} to "
                f"{_fmt(max(values))} across {len(values)} run(s)."
            )
        else:
            lines.append(f"**Observed in this project.** {_NO_NUMERIC}")
        lines.append("")
        return lines

    direction = metric_direction(name)
    lines.append(f"**Definition.** {entry['definition']}")
    lines.append("")
    lines.append(f"**Range.** {entry['range']}")
    lines.append("")
    lines.append(f"**How to read.** {entry['how_to_read']}")
    lines.append("")
    lines.append(
        f"**Direction.** {'Higher' if direction == 'higher' else 'Lower'} is better."
    )
    lines.append("")
    if values:
        observed = (
            f"**Observed in this project.** {_fmt(min(values))} to "
            f"{_fmt(max(values))} across {len(values)} run(s)."
        )
        best = select_best_run(runs, name, direction=direction)
        if best is not None:
            best_value = best.get("metrics", {}).get(name)
            provenance = ", ".join(
                str(part)
                for part in (
                    best.get("run_id"),
                    f"experiment {best.get('_experiment_id')}",
                    f"method {best.get('method')}",
                )
                if part
            )
            ci = ""
            uncertainty = best.get("metrics_with_uncertainty")
            if isinstance(uncertainty, dict) and isinstance(
                uncertainty.get(name), dict
            ):
                ci = _format_ci(uncertainty[name])
            best_line = f" Best: {_fmt(best_value)}"
            if ci:
                best_line += f" {ci}"
            best_line += f" ({provenance})."
            observed += best_line
        lines.append(observed)
    else:
        lines.append(f"**Observed in this project.** {_NO_NUMERIC}")
    lines.append("")
    return lines
