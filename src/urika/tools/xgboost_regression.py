"""Gradient boosting regression tool using scikit-learn."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class XGBoostRegressionMethod(ITool):
    """Gradient boosting regression using scikit-learn."""

    def name(self) -> str:
        return "xgboost_regression"

    def description(self) -> str:
        return "Gradient boosting regression using scikit-learn."

    def category(self) -> str:
        return "regression"

    def default_params(self) -> dict[str, Any]:
        return {
            "target": "",
            "features": None,
            "n_estimators": 100,
            "max_depth": 3,
            "learning_rate": 0.1,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        target = params.get("target", "")
        features = params.get("features")
        n_estimators = params.get("n_estimators", 100)
        max_depth = params.get("max_depth", 3)
        learning_rate = params.get("learning_rate", 0.1)
        df = data.data

        if target not in df.columns:
            return ToolResult(
                outputs={}, metrics={}, valid=False, error=f"Target column '{target}' not found"
            )

        numeric_df = df.select_dtypes(include="number")
        if features is None:
            feature_cols = [c for c in numeric_df.columns if c != target]
        else:
            feature_cols = [c for c in features if c in df.columns]

        if not feature_cols:
            return ToolResult(
                outputs={}, metrics={}, valid=False, error="No feature columns available"
            )

        subset = numeric_df[[target, *feature_cols]].dropna()
        if len(subset) < 2:
            return ToolResult(
                outputs={}, metrics={},
                valid=False,
                error=f"Insufficient data: {len(subset)} rows after dropping NaN",
            )

        X = subset[feature_cols].values  # noqa: N806
        y = subset[target].values

        model = GradientBoostingRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=42,
        )
        model.fit(X, y)
        y_pred = model.predict(X)

        return ToolResult(
            outputs={},
            metrics={
                "r2": float(r2_score(y, y_pred)),
                "rmse": float(np.sqrt(mean_squared_error(y, y_pred))),
                "mae": float(mean_absolute_error(y, y_pred)),
            }
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return XGBoostRegressionMethod()
