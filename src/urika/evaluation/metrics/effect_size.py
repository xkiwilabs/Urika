"""Effect size metrics: Cohen's d."""

from __future__ import annotations

import numpy as np

from urika.evaluation.metrics.base import IMetric


class CohensD(IMetric):
    """Cohen's d effect size.

    Compares two groups (y_true and y_pred treated as separate groups).
    Uses pooled standard deviation.
    """

    def name(self) -> str:
        return "cohens_d"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        n1 = len(y_true)
        n2 = len(y_pred)
        mean1 = float(np.mean(y_true))
        mean2 = float(np.mean(y_pred))
        var1 = float(np.var(y_true, ddof=1))
        var2 = float(np.var(y_pred, ddof=1))

        pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))

        if pooled_std == 0.0:
            return 0.0

        return float(abs(mean2 - mean1) / pooled_std)

    def direction(self) -> str:
        return "higher_is_better"
