"""Linear regression method using scikit-learn."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from urika.data.models import DatasetView
from urika.methods.base import IAnalysisMethod, MethodResult


class LinearRegressionMethod(IAnalysisMethod):
    """Ordinary least-squares linear regression."""

    def name(self) -> str:
        return "linear_regression"

    def description(self) -> str:
        return "Ordinary least-squares linear regression using scikit-learn."

    def category(self) -> str:
        return "regression"

    def default_params(self) -> dict[str, Any]:
        return {"target": "", "features": None}

    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult:
        target = params.get("target", "")
        features = params.get("features")
        df = data.data

        if target not in df.columns:
            return MethodResult(
                metrics={}, valid=False, error=f"Target column '{target}' not found"
            )

        numeric_df = df.select_dtypes(include="number")
        if features is None:
            feature_cols = [c for c in numeric_df.columns if c != target]
        else:
            feature_cols = [c for c in features if c in df.columns]

        if not feature_cols:
            return MethodResult(
                metrics={}, valid=False, error="No feature columns available"
            )

        subset = numeric_df[[target, *feature_cols]].dropna()
        if len(subset) < 2:
            return MethodResult(
                metrics={},
                valid=False,
                error=f"Insufficient data: {len(subset)} rows after dropping NaN",
            )

        X = subset[feature_cols].values
        y = subset[target].values

        model = LinearRegression()
        model.fit(X, y)
        y_pred = model.predict(X)

        return MethodResult(
            metrics={
                "r2": float(r2_score(y, y_pred)),
                "rmse": float(np.sqrt(mean_squared_error(y, y_pred))),
                "mae": float(mean_absolute_error(y, y_pred)),
            }
        )


def get_method() -> IAnalysisMethod:
    """Factory function for registry auto-discovery."""
    return LinearRegressionMethod()
