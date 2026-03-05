"""Regression metrics: R², RMSE, MAE."""

from __future__ import annotations

import numpy as np

from urika.evaluation.metrics.base import IMetric


class R2(IMetric):
    """Coefficient of determination (R²)."""

    def name(self) -> str:
        return "r2"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        ss_res = float(np.sum((y_true - y_pred) ** 2))
        ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
        if ss_tot == 0.0:
            return 0.0
        return 1.0 - ss_res / ss_tot

    def direction(self) -> str:
        return "higher_is_better"


class RMSE(IMetric):
    """Root Mean Squared Error."""

    def name(self) -> str:
        return "rmse"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

    def direction(self) -> str:
        return "lower_is_better"


class MAE(IMetric):
    """Mean Absolute Error."""

    def name(self) -> str:
        return "mae"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        return float(np.mean(np.abs(y_true - y_pred)))

    def direction(self) -> str:
        return "lower_is_better"
