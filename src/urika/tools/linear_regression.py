"""Linear regression tool using scikit-learn."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class LinearRegressionMethod(ITool):
    """Ordinary least-squares linear regression."""

    def name(self) -> str:
        return "linear_regression"

    def description(self) -> str:
        return (
            "Ordinary least-squares linear regression using scikit-learn. "
            "Supports pre-split train/test indices for unbiased evaluation."
        )

    def category(self) -> str:
        return "regression"

    def default_params(self) -> dict[str, Any]:
        return {
            "target": "",
            "features": None,
            "train_indices": None,
            "test_indices": None,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        target = params.get("target", "")
        features = params.get("features")
        df = data.data

        if target not in df.columns:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Target column '{target}' not found",
            )

        numeric_df = df.select_dtypes(include="number")
        if features is None:
            feature_cols = [c for c in numeric_df.columns if c != target]
        else:
            feature_cols = [c for c in features if c in df.columns]

        if not feature_cols:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error="No feature columns available",
            )

        subset = numeric_df[[target, *feature_cols]].dropna().reset_index(drop=True)
        if len(subset) < 2:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Insufficient data: {len(subset)} rows after dropping NaN",
            )

        X = subset[feature_cols].values
        y = subset[target].values

        train_idx = params.get("train_indices")
        test_idx = params.get("test_indices")

        if train_idx is not None and test_idx is not None:
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
        else:
            # Fallback: train and evaluate on full data (training metrics only)
            X_train, X_test = X, X
            y_train, y_test = y, y

        model = LinearRegression()
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        if train_idx is not None:
            note = "Metrics computed on held-out test set."
        else:
            note = "Metrics are training-set only; use train_val_test_split for unbiased estimates."

        return ToolResult(
            outputs={"note": note},
            metrics={
                "r2": float(r2_score(y_test, y_pred)),
                "rmse": float(np.sqrt(mean_squared_error(y_test, y_pred))),
                "mae": float(mean_absolute_error(y_test, y_pred)),
            },
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return LinearRegressionMethod()
