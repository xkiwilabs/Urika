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

    def compute_with_ci(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        *,
        confidence: float = 0.95,
        n_boot: int = 2000,
        seed: int | None = 0,
    ) -> dict:
        """Compute the metric with a bootstrap-percentile confidence interval.

        Pairwise bootstrap resample of ``(y_true, y_pred)``: draw ``n_boot``
        resamples with replacement, recompute :meth:`compute` on each, and
        take the percentile interval of the resampled values. Deterministic
        for a given ``seed``.

        Percentile intervals can undercover for skewed statistics near a
        boundary (e.g. R² or AUC near 1.0); BCa would be more accurate there
        but is not implemented.

        Concrete on the ABC so every metric inherits it — subclasses only
        implement :meth:`compute`.

        Args:
            y_true: Ground truth values.
            y_pred: Predicted values (same length as ``y_true``).
            confidence: Interval coverage (default 0.95 → 95% CI).
            n_boot: Number of bootstrap resamples.
            seed: RNG seed for reproducibility (``None`` → nondeterministic).

        Returns:
            ``{"value": float, "ci_lower": float, "ci_upper": float,
            "confidence": float, "method": "bootstrap-percentile",
            "n_boot": int}``

        Raises:
            ValueError: If inputs have fewer than 3 elements or mismatched
                lengths, if ``n_boot`` is less than 1, or if more than 20%
                of resamples fail inside :meth:`compute` (data too degenerate
                for a bootstrap CI).
        """
        if n_boot < 1:
            raise ValueError("n_boot must be >= 1")
        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred)
        if len(y_true) != len(y_pred):
            raise ValueError(
                f"y_true and y_pred must have the same length "
                f"(got {len(y_true)} and {len(y_pred)})"
            )
        n = len(y_true)
        if n < 3:
            raise ValueError(f"Bootstrap CI needs at least 3 observations (got {n})")

        value = float(self.compute(y_true, y_pred))

        rng = np.random.default_rng(seed)
        boot_values: list[float] = []
        failures = 0
        for _ in range(n_boot):
            idx = rng.integers(0, n, size=n)
            try:
                boot_values.append(float(self.compute(y_true[idx], y_pred[idx])))
            except Exception:
                # Degenerate resamples (e.g. a single-class y_true for
                # AUC, zero variance for R²) are skipped — but if they
                # dominate, the interval would be meaningless.  Even when
                # failures are a minority, skipping them can bias the
                # interval if failures are non-random: e.g. single-class
                # resamples for AUC cluster at one end of the distribution,
                # so the surviving resamples systematically misrepresent
                # the tail that matters most.
                failures += 1
        if failures > 0.2 * n_boot:
            raise ValueError(
                f"{failures} of {n_boot} bootstrap resamples failed inside "
                f"{self.name()}.compute(); the data is too degenerate for "
                f"a bootstrap confidence interval"
            )

        alpha = 1.0 - confidence
        lower, upper = np.percentile(
            boot_values, [100.0 * alpha / 2.0, 100.0 * (1.0 - alpha / 2.0)]
        )
        return {
            "value": value,
            "ci_lower": float(lower),
            "ci_upper": float(upper),
            "confidence": confidence,
            "method": "bootstrap-percentile",
            "n_boot": n_boot,
        }
