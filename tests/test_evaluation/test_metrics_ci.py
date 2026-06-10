"""Tests for IMetric.compute_with_ci bootstrap confidence intervals."""

from __future__ import annotations

import numpy as np
import pytest

from urika.evaluation.metrics.base import IMetric
from urika.evaluation.metrics.regression import MAE, R2, RMSE


@pytest.fixture
def regression_data() -> tuple[np.ndarray, np.ndarray]:
    """A known noisy linear dataset: y_pred = y_true + small noise."""
    rng = np.random.default_rng(42)
    y_true = np.linspace(0.0, 10.0, 50)
    y_pred = y_true + rng.normal(0.0, 0.5, size=50)
    return y_true, y_pred


class TestComputeWithCi:
    def test_result_shape(self, regression_data) -> None:
        y_true, y_pred = regression_data
        result = R2().compute_with_ci(y_true, y_pred, n_boot=200)
        assert set(result) == {
            "value",
            "ci_lower",
            "ci_upper",
            "confidence",
            "method",
            "n_boot",
        }
        assert result["method"] == "bootstrap-percentile"
        assert result["n_boot"] == 200
        assert result["confidence"] == 0.95
        assert isinstance(result["value"], float)
        assert isinstance(result["ci_lower"], float)
        assert isinstance(result["ci_upper"], float)

    def test_deterministic_for_fixed_seed(self, regression_data) -> None:
        y_true, y_pred = regression_data
        a = RMSE().compute_with_ci(y_true, y_pred, n_boot=200, seed=7)
        b = RMSE().compute_with_ci(y_true, y_pred, n_boot=200, seed=7)
        assert a == b

    def test_different_seeds_differ(self, regression_data) -> None:
        y_true, y_pred = regression_data
        a = RMSE().compute_with_ci(y_true, y_pred, n_boot=200, seed=1)
        b = RMSE().compute_with_ci(y_true, y_pred, n_boot=200, seed=2)
        assert (a["ci_lower"], a["ci_upper"]) != (b["ci_lower"], b["ci_upper"])

    def test_interval_contains_point_value_r2(self, regression_data) -> None:
        y_true, y_pred = regression_data
        result = R2().compute_with_ci(y_true, y_pred, n_boot=500)
        assert result["ci_lower"] <= result["value"] <= result["ci_upper"]
        assert result["value"] == pytest.approx(R2().compute(y_true, y_pred))

    def test_interval_contains_point_value_rmse(self, regression_data) -> None:
        y_true, y_pred = regression_data
        result = RMSE().compute_with_ci(y_true, y_pred, n_boot=500)
        assert result["ci_lower"] <= result["value"] <= result["ci_upper"]
        assert result["ci_lower"] < result["ci_upper"]

    def test_tighter_interval_with_larger_sample(self) -> None:
        """More data → narrower bootstrap interval (same noise model)."""
        rng = np.random.default_rng(0)

        def make(n: int) -> tuple[np.ndarray, np.ndarray]:
            y_true = np.linspace(0.0, 10.0, n)
            return y_true, y_true + rng.normal(0.0, 0.5, size=n)

        small = MAE().compute_with_ci(*make(20), n_boot=500)
        large = MAE().compute_with_ci(*make(500), n_boot=500)
        width_small = small["ci_upper"] - small["ci_lower"]
        width_large = large["ci_upper"] - large["ci_lower"]
        assert width_large < width_small

    def test_custom_confidence_level(self, regression_data) -> None:
        """A 99% interval is at least as wide as an 80% interval."""
        y_true, y_pred = regression_data
        narrow = R2().compute_with_ci(y_true, y_pred, confidence=0.80, n_boot=500)
        wide = R2().compute_with_ci(y_true, y_pred, confidence=0.99, n_boot=500)
        assert narrow["confidence"] == 0.80
        assert wide["confidence"] == 0.99
        assert (wide["ci_upper"] - wide["ci_lower"]) >= (
            narrow["ci_upper"] - narrow["ci_lower"]
        )

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="length"):
            R2().compute_with_ci(np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0]))

    def test_short_input_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 3"):
            R2().compute_with_ci(np.array([1.0, 2.0]), np.array([1.0, 2.0]))

    def test_n_boot_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="n_boot must be >= 1"):
            R2().compute_with_ci(
                np.array([1.0, 2.0, 3.0, 4.0]),
                np.array([1.1, 2.1, 3.1, 4.1]),
                n_boot=0,
            )

    def test_inherited_by_all_metrics(self) -> None:
        """compute_with_ci is concrete on the ABC — every metric has it."""
        from urika.evaluation.metrics.registry import MetricRegistry

        registry = MetricRegistry()
        registry.discover()
        names = registry.list_all()
        assert names  # discovery found something
        for name in names:
            metric = registry.get(name)
            assert callable(metric.compute_with_ci)


class _FlakyMetric(IMetric):
    """Test double: compute() raises on a configurable fraction of calls.

    The first call (the point estimate) always succeeds; every
    subsequent call raises while ``self.failures_left > 0``.
    """

    def __init__(self, n_failures: int) -> None:
        self._calls = 0
        self._n_failures = n_failures

    def name(self) -> str:
        return "flaky"

    def compute(self, y_true, y_pred, **kwargs: object) -> float:
        self._calls += 1
        # Call 1 is the point estimate; fail the next n_failures calls.
        if 1 < self._calls <= 1 + self._n_failures:
            raise ValueError("degenerate resample")
        return float(np.mean(y_pred - y_true))

    def direction(self) -> str:
        return "higher_is_better"


class TestDegenerateResamples:
    def test_minority_failures_are_skipped(self, regression_data) -> None:
        """<=20% failing resamples are skipped; the CI still computes."""
        y_true, y_pred = regression_data
        metric = _FlakyMetric(n_failures=20)  # 20 of 200 = 10%
        result = metric.compute_with_ci(y_true, y_pred, n_boot=200)
        assert result["ci_lower"] <= result["ci_upper"]
        assert result["n_boot"] == 200

    def test_majority_failures_raise(self, regression_data) -> None:
        """>20% failing resamples raise a clear ValueError."""
        y_true, y_pred = regression_data
        metric = _FlakyMetric(n_failures=200)  # all 200 resamples fail
        with pytest.raises(ValueError, match="resamples failed"):
            metric.compute_with_ci(y_true, y_pred, n_boot=200)
