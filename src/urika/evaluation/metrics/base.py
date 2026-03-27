"""Base metric interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class IMetric(ABC):
    """Abstract base class for all evaluation metrics."""

    @abstractmethod
    def name(self) -> str:
        """Return the unique name of this metric."""
        ...

    @abstractmethod
    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        """Compute the metric value.

        Args:
            y_true: Ground truth values.
            y_pred: Predicted values.
            **kwargs: Additional keyword arguments.

        Returns:
            The computed metric value as a float.
        """
        ...

    @abstractmethod
    def direction(self) -> str:
        """Return the optimization direction.

        Returns:
            Either "higher_is_better" or "lower_is_better".
        """
        ...
