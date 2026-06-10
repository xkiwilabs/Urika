"""Canonical best-run selection — single source of truth.

Pre-v0.7.1, four call sites implemented their own "best run" logic
(labbook, progress, leaderboard, readme_generator) and could disagree
in user-visible artifacts — the README naming one best method while
the labbook named another. All four now delegate here.
"""

from __future__ import annotations

from typing import Any

# Union of the direction knowledge previously split across
# labbook._LOWER_IS_BETTER and leaderboard's direction strings.
# (labbook's set and orchestrator.loop_criteria's set were identical
# 15-name copies; the other call sites took explicit direction params.)
LOWER_IS_BETTER: frozenset[str] = frozenset(
    {
        "rmse",
        "mse",
        "mae",
        "mape",
        "loss",
        "error",
        "brier_score",
        "log_loss",
        "sse",
        "residual",
        "p_value",
        "aic",
        "bic",
        "deviance",
        "perplexity",
    }
)


def metric_direction(metric: str) -> str:
    """Return "lower" or "higher" for a metric name (suffix-aware:
    ``val_rmse`` ranks like ``rmse``)."""
    name = metric.lower()
    if name in LOWER_IS_BETTER:
        return "lower"
    # Suffix-aware: prefixed variants (val_rmse, test_loss,
    # mean_squared_error) rank like their base metric.
    for base in LOWER_IS_BETTER:
        if name.endswith(f"_{base}"):
            return "lower"
    return "higher"


def _metrics_of(run: Any) -> dict[str, Any]:
    """Return the metrics mapping of a run record (dict or object)."""
    if isinstance(run, dict):
        metrics = run.get("metrics")
    else:
        metrics = getattr(run, "metrics", None)
    return metrics if isinstance(metrics, dict) else {}


def select_best_run(
    runs: Any,
    primary_metric: str,
    direction: str | None = None,
) -> Any | None:
    """Best run by *primary_metric*; None if no run carries the metric.

    *direction* overrides inference ("higher" | "lower"). Runs whose
    metric value is not a real number (bools excluded — ``isinstance(True,
    int)`` is True in Python) are skipped. Ties resolve to the first run
    so generated artifacts are deterministic.
    """
    if direction is None:
        direction = metric_direction(primary_metric)
    if direction not in ("higher", "lower"):
        raise ValueError(f"direction must be 'higher' or 'lower', got {direction!r}")

    best: Any | None = None
    best_value: float | None = None
    for run in runs:
        value = _metrics_of(run).get(primary_metric)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if (
            best_value is None
            or (direction == "higher" and value > best_value)
            or (direction == "lower" and value < best_value)
        ):
            best = run
            best_value = value
    return best
