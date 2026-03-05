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


# ---------------------------------------------------------------------------
# Classification metrics tests
# ---------------------------------------------------------------------------
class TestAccuracy:
    """Tests for Accuracy metric."""

    def test_perfect_prediction(self) -> None:
        from urika.evaluation.metrics.classification import Accuracy

        metric = Accuracy()
        y = np.array([0, 1, 1, 0, 1])
        assert metric.compute(y, y) == pytest.approx(1.0)

    def test_known_values(self) -> None:
        from urika.evaluation.metrics.classification import Accuracy

        metric = Accuracy()
        y_true = np.array([0, 1, 1, 0, 1])
        y_pred = np.array([0, 1, 0, 0, 1])
        # 4 correct out of 5
        assert metric.compute(y_true, y_pred) == pytest.approx(0.8)

    def test_name(self) -> None:
        from urika.evaluation.metrics.classification import Accuracy

        assert Accuracy().name() == "accuracy"

    def test_direction(self) -> None:
        from urika.evaluation.metrics.classification import Accuracy

        assert Accuracy().direction() == "higher_is_better"


class TestPrecision:
    """Tests for Precision metric."""

    def test_perfect_prediction(self) -> None:
        from urika.evaluation.metrics.classification import Precision

        metric = Precision()
        y_true = np.array([1, 1, 0, 0])
        y_pred = np.array([1, 1, 0, 0])
        assert metric.compute(y_true, y_pred) == pytest.approx(1.0)

    def test_known_values(self) -> None:
        from urika.evaluation.metrics.classification import Precision

        metric = Precision()
        y_true = np.array([1, 1, 0, 0, 1])
        y_pred = np.array([1, 0, 1, 0, 1])
        # TP=2, FP=1 -> P = 2/3
        assert metric.compute(y_true, y_pred) == pytest.approx(2.0 / 3.0)

    def test_no_positive_predictions(self) -> None:
        from urika.evaluation.metrics.classification import Precision

        metric = Precision()
        y_true = np.array([1, 1, 0])
        y_pred = np.array([0, 0, 0])
        # TP=0, FP=0 -> denominator 0 -> return 0.0
        assert metric.compute(y_true, y_pred) == 0.0

    def test_name(self) -> None:
        from urika.evaluation.metrics.classification import Precision

        assert Precision().name() == "precision"

    def test_direction(self) -> None:
        from urika.evaluation.metrics.classification import Precision

        assert Precision().direction() == "higher_is_better"


class TestRecall:
    """Tests for Recall metric."""

    def test_perfect_prediction(self) -> None:
        from urika.evaluation.metrics.classification import Recall

        metric = Recall()
        y_true = np.array([1, 1, 0, 0])
        y_pred = np.array([1, 1, 0, 0])
        assert metric.compute(y_true, y_pred) == pytest.approx(1.0)

    def test_known_values(self) -> None:
        from urika.evaluation.metrics.classification import Recall

        metric = Recall()
        y_true = np.array([1, 1, 0, 0, 1])
        y_pred = np.array([1, 0, 1, 0, 1])
        # TP=2, FN=1 -> R = 2/3
        assert metric.compute(y_true, y_pred) == pytest.approx(2.0 / 3.0)

    def test_no_actual_positives(self) -> None:
        from urika.evaluation.metrics.classification import Recall

        metric = Recall()
        y_true = np.array([0, 0, 0])
        y_pred = np.array([1, 0, 1])
        # TP=0, FN=0 -> denominator 0 -> return 0.0
        assert metric.compute(y_true, y_pred) == 0.0

    def test_name(self) -> None:
        from urika.evaluation.metrics.classification import Recall

        assert Recall().name() == "recall"

    def test_direction(self) -> None:
        from urika.evaluation.metrics.classification import Recall

        assert Recall().direction() == "higher_is_better"


class TestF1:
    """Tests for F1 metric."""

    def test_perfect_prediction(self) -> None:
        from urika.evaluation.metrics.classification import F1

        metric = F1()
        y_true = np.array([1, 1, 0, 0])
        y_pred = np.array([1, 1, 0, 0])
        assert metric.compute(y_true, y_pred) == pytest.approx(1.0)

    def test_known_values(self) -> None:
        from urika.evaluation.metrics.classification import F1

        metric = F1()
        y_true = np.array([1, 1, 0, 0, 1])
        y_pred = np.array([1, 0, 1, 0, 1])
        # P=2/3, R=2/3 -> F1 = 2*(2/3)*(2/3)/((2/3)+(2/3)) = 2/3
        assert metric.compute(y_true, y_pred) == pytest.approx(2.0 / 3.0)

    def test_zero_precision_and_recall(self) -> None:
        from urika.evaluation.metrics.classification import F1

        metric = F1()
        y_true = np.array([0, 0, 0])
        y_pred = np.array([0, 0, 0])
        # P=0, R=0 -> F1 = 0.0
        assert metric.compute(y_true, y_pred) == 0.0

    def test_name(self) -> None:
        from urika.evaluation.metrics.classification import F1

        assert F1().name() == "f1"

    def test_direction(self) -> None:
        from urika.evaluation.metrics.classification import F1

        assert F1().direction() == "higher_is_better"


class TestAUC:
    """Tests for AUC metric."""

    def test_perfect_prediction(self) -> None:
        from urika.evaluation.metrics.classification import AUC

        metric = AUC()
        y_true = np.array([0, 0, 1, 1])
        y_pred = np.array([0.0, 0.1, 0.9, 1.0])
        assert metric.compute(y_true, y_pred) == pytest.approx(1.0)

    def test_known_values(self) -> None:
        from urika.evaluation.metrics.classification import AUC

        metric = AUC()
        y_true = np.array([0, 0, 1, 1])
        y_pred = np.array([0.1, 0.4, 0.35, 0.8])
        # sklearn roc_auc_score for these values = 0.75
        assert metric.compute(y_true, y_pred) == pytest.approx(0.75)

    def test_random_prediction(self) -> None:
        from urika.evaluation.metrics.classification import AUC

        metric = AUC()
        y_true = np.array([0, 1, 0, 1])
        y_pred = np.array([0.5, 0.5, 0.5, 0.5])
        # All same scores -> AUC = 0.5
        assert metric.compute(y_true, y_pred) == pytest.approx(0.5)

    def test_name(self) -> None:
        from urika.evaluation.metrics.classification import AUC

        assert AUC().name() == "auc"

    def test_direction(self) -> None:
        from urika.evaluation.metrics.classification import AUC

        assert AUC().direction() == "higher_is_better"
