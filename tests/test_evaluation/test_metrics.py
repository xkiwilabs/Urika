"""Tests for evaluation metrics."""

from __future__ import annotations

import numpy as np
import pytest

from urika.evaluation.metrics.base import IMetric


# ---------------------------------------------------------------------------
# Regression metrics tests
# ---------------------------------------------------------------------------
class TestR2:
    """Tests for R² metric."""

    def test_perfect_prediction(self) -> None:
        from urika.evaluation.metrics.regression import R2

        metric = R2()
        y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert metric.compute(y, y) == pytest.approx(1.0)

    def test_known_values(self) -> None:
        from urika.evaluation.metrics.regression import R2

        metric = R2()
        y_true = np.array([3.0, -0.5, 2.0, 7.0])
        y_pred = np.array([2.5, 0.0, 2.0, 8.0])
        # SS_res = 0.25 + 0.25 + 0.0 + 1.0 = 1.5
        # SS_tot = var * n = mean=2.875, deviations: 0.015625+11.390625+0.765625+17.015625=29.1875
        # Actually: SS_tot = sum((y-mean)^2)
        # mean = (3 - 0.5 + 2 + 7) / 4 = 11.5 / 4 = 2.875
        # SS_tot = (0.125)^2 ... let me just compute
        # (3-2.875)^2 + (-0.5-2.875)^2 + (2-2.875)^2 + (7-2.875)^2
        # = 0.015625 + 11.390625 + 0.765625 + 17.015625 = 29.1875
        # R2 = 1 - 1.5/29.1875 = 1 - 0.05139... = 0.9486...
        assert metric.compute(y_true, y_pred) == pytest.approx(0.9486, abs=1e-3)

    def test_ss_tot_zero(self) -> None:
        """When all y_true values are constant, SS_tot=0, return 0.0."""
        from urika.evaluation.metrics.regression import R2

        metric = R2()
        y_true = np.array([5.0, 5.0, 5.0])
        y_pred = np.array([4.0, 5.0, 6.0])
        assert metric.compute(y_true, y_pred) == 0.0

    def test_name(self) -> None:
        from urika.evaluation.metrics.regression import R2

        assert R2().name() == "r2"

    def test_direction(self) -> None:
        from urika.evaluation.metrics.regression import R2

        assert R2().direction() == "higher_is_better"

    def test_is_imetric(self) -> None:
        from urika.evaluation.metrics.regression import R2

        assert isinstance(R2(), IMetric)


class TestRMSE:
    """Tests for RMSE metric."""

    def test_perfect_prediction(self) -> None:
        from urika.evaluation.metrics.regression import RMSE

        metric = RMSE()
        y = np.array([1.0, 2.0, 3.0])
        assert metric.compute(y, y) == pytest.approx(0.0)

    def test_known_values(self) -> None:
        from urika.evaluation.metrics.regression import RMSE

        metric = RMSE()
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([1.1, 2.1, 3.1])
        # MSE = (0.01 + 0.01 + 0.01) / 3 = 0.01
        # RMSE = sqrt(0.01) = 0.1
        assert metric.compute(y_true, y_pred) == pytest.approx(0.1, abs=1e-6)

    def test_name(self) -> None:
        from urika.evaluation.metrics.regression import RMSE

        assert RMSE().name() == "rmse"

    def test_direction(self) -> None:
        from urika.evaluation.metrics.regression import RMSE

        assert RMSE().direction() == "lower_is_better"


class TestMAE:
    """Tests for MAE metric."""

    def test_perfect_prediction(self) -> None:
        from urika.evaluation.metrics.regression import MAE

        metric = MAE()
        y = np.array([1.0, 2.0, 3.0])
        assert metric.compute(y, y) == pytest.approx(0.0)

    def test_known_values(self) -> None:
        from urika.evaluation.metrics.regression import MAE

        metric = MAE()
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([1.5, 2.5, 3.5])
        # MAE = (0.5 + 0.5 + 0.5) / 3 = 0.5
        assert metric.compute(y_true, y_pred) == pytest.approx(0.5)

    def test_name(self) -> None:
        from urika.evaluation.metrics.regression import MAE

        assert MAE().name() == "mae"

    def test_direction(self) -> None:
        from urika.evaluation.metrics.regression import MAE

        assert MAE().direction() == "lower_is_better"
