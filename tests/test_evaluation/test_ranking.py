"""Tests for the canonical best-run selection helper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from urika.evaluation.ranking import (
    LOWER_IS_BETTER,
    metric_direction,
    select_best_run,
)


@dataclass
class _Record:
    """Stand-in for RunRecord-style objects with a ``.metrics`` attribute."""

    run_id: str
    metrics: dict[str, Any] = field(default_factory=dict)


# ── LOWER_IS_BETTER set ────────────────────────────────────────


def test_lower_is_better_contains_classic_error_metrics() -> None:
    for name in ("rmse", "mse", "mae", "mape", "loss", "aic", "bic", "p_value"):
        assert name in LOWER_IS_BETTER


def test_lower_is_better_excludes_score_metrics() -> None:
    for name in ("r2", "accuracy", "f1", "auc", "precision", "recall"):
        assert name not in LOWER_IS_BETTER


# ── metric_direction ───────────────────────────────────────────


def test_metric_direction_lower_for_error_metrics() -> None:
    assert metric_direction("rmse") == "lower"
    assert metric_direction("log_loss") == "lower"


def test_metric_direction_higher_by_default() -> None:
    assert metric_direction("r2") == "higher"
    assert metric_direction("accuracy") == "higher"
    assert metric_direction("some_custom_score") == "higher"


def test_metric_direction_suffix_aware() -> None:
    """``val_rmse`` ranks like ``rmse``; ``test_loss`` like ``loss``."""
    assert metric_direction("val_rmse") == "lower"
    assert metric_direction("test_loss") == "lower"
    assert metric_direction("mean_squared_error") == "lower"
    assert metric_direction("val_r2") == "higher"


# ── select_best_run ────────────────────────────────────────────


def test_select_best_higher_metric_picks_max() -> None:
    runs = [
        {"run_id": "run-001", "metrics": {"r2": 0.5}},
        {"run_id": "run-002", "metrics": {"r2": 0.9}},
        {"run_id": "run-003", "metrics": {"r2": 0.3}},
    ]
    best = select_best_run(runs, "r2")
    assert best is not None
    assert best["run_id"] == "run-002"


def test_select_best_lower_metric_picks_min() -> None:
    runs = [
        {"run_id": "run-001", "metrics": {"rmse": 0.5}},
        {"run_id": "run-002", "metrics": {"rmse": 0.1}},
        {"run_id": "run-003", "metrics": {"rmse": 0.3}},
    ]
    best = select_best_run(runs, "rmse")
    assert best is not None
    assert best["run_id"] == "run-002"


def test_select_best_suffix_val_rmse_treated_as_lower() -> None:
    runs = [
        {"run_id": "run-001", "metrics": {"val_rmse": 0.8}},
        {"run_id": "run-002", "metrics": {"val_rmse": 0.2}},
    ]
    best = select_best_run(runs, "val_rmse")
    assert best is not None
    assert best["run_id"] == "run-002"


def test_select_best_missing_metric_returns_none() -> None:
    runs = [
        {"run_id": "run-001", "metrics": {"r2": 0.5}},
        {"run_id": "run-002", "metrics": {}},
    ]
    assert select_best_run(runs, "rmse") is None
    assert select_best_run([], "r2") is None


def test_select_best_explicit_direction_overrides_inference() -> None:
    runs = [
        {"run_id": "run-001", "metrics": {"r2": 0.5}},
        {"run_id": "run-002", "metrics": {"r2": 0.9}},
    ]
    # r2 infers "higher", but an explicit "lower" must win.
    best = select_best_run(runs, "r2", direction="lower")
    assert best is not None
    assert best["run_id"] == "run-001"


def test_select_best_skips_bool_metric_values() -> None:
    # bool is a subclass of int in Python — must be excluded explicitly.
    runs = [
        {"run_id": "run-001", "metrics": {"r2": True}},
        {"run_id": "run-002", "metrics": {"r2": 0.4}},
    ]
    best = select_best_run(runs, "r2")
    assert best is not None
    assert best["run_id"] == "run-002"


def test_select_best_skips_non_numeric_metric_values() -> None:
    runs = [
        {"run_id": "run-001", "metrics": {"r2": "high"}},
        {"run_id": "run-002", "metrics": {"r2": 0.4}},
    ]
    best = select_best_run(runs, "r2")
    assert best is not None
    assert best["run_id"] == "run-002"


def test_select_best_tie_first_wins() -> None:
    """Ties resolve to the first run so artifacts are deterministic."""
    runs = [
        {"run_id": "run-001", "metrics": {"r2": 0.7}},
        {"run_id": "run-002", "metrics": {"r2": 0.7}},
    ]
    best = select_best_run(runs, "r2")
    assert best is not None
    assert best["run_id"] == "run-001"

    lower_runs = [
        {"run_id": "run-001", "metrics": {"rmse": 0.2}},
        {"run_id": "run-002", "metrics": {"rmse": 0.2}},
    ]
    best_lower = select_best_run(lower_runs, "rmse")
    assert best_lower is not None
    assert best_lower["run_id"] == "run-001"


def test_select_best_accepts_objects_with_metrics_attribute() -> None:
    runs = [
        _Record("run-001", {"r2": 0.2}),
        _Record("run-002", {"r2": 0.6}),
    ]
    best = select_best_run(runs, "r2")
    assert best is not None
    assert best.run_id == "run-002"
