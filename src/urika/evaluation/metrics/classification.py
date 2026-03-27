"""Classification metrics: Accuracy, Precision, Recall, F1, AUC."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score

from urika.evaluation.metrics.base import IMetric


class Accuracy(IMetric):
    """Classification accuracy."""

    def name(self) -> str:
        return "accuracy"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        return float(np.mean(y_true == y_pred))

    def direction(self) -> str:
        return "higher_is_better"


class Precision(IMetric):
    """Binary precision: TP / (TP + FP)."""

    def name(self) -> str:
        return "precision"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        tp = float(np.sum((y_true == 1) & (y_pred == 1)))
        fp = float(np.sum((y_true == 0) & (y_pred == 1)))
        denom = tp + fp
        if denom == 0.0:
            return 0.0
        return tp / denom

    def direction(self) -> str:
        return "higher_is_better"


class Recall(IMetric):
    """Binary recall: TP / (TP + FN)."""

    def name(self) -> str:
        return "recall"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        tp = float(np.sum((y_true == 1) & (y_pred == 1)))
        fn = float(np.sum((y_true == 1) & (y_pred == 0)))
        denom = tp + fn
        if denom == 0.0:
            return 0.0
        return tp / denom

    def direction(self) -> str:
        return "higher_is_better"


class F1(IMetric):
    """F1 score: harmonic mean of precision and recall."""

    def name(self) -> str:
        return "f1"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        precision_metric = Precision()
        recall_metric = Recall()
        p = precision_metric.compute(y_true, y_pred)
        r = recall_metric.compute(y_true, y_pred)
        denom = p + r
        if denom == 0.0:
            return 0.0
        return 2.0 * p * r / denom

    def direction(self) -> str:
        return "higher_is_better"


class AUC(IMetric):
    """Area Under the ROC Curve. y_pred should be probability scores."""

    def name(self) -> str:
        return "auc"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        return float(roc_auc_score(y_true, y_pred))

    def direction(self) -> str:
        return "higher_is_better"
