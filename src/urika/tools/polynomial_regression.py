"""Polynomial and interaction regression tool using scikit-learn."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import PolynomialFeatures

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class PolynomialRegressionMethod(ITool):
    """Polynomial and interaction term regression for nonlinear relationships."""

    def name(self) -> str:
        return "polynomial_regression"

    def description(self) -> str:
        return (
            "Polynomial and interaction term regression for nonlinear relationships. "
            "Uses sklearn PolynomialFeatures + LinearRegression pipeline. "
            "Supports configurable degree, interaction-only mode, and "
            "pre-split train/test indices for unbiased evaluation."
        )

    def category(self) -> str:
        return "regression"

    def default_params(self) -> dict[str, Any]:
        return {
            "target": "",
            "features": None,
            "degree": 2,
            "interaction_only": False,
            "include_bias": False,
            "train_indices": None,
            "test_indices": None,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        target = params.get("target", "")
        features = params.get("features")
        degree = params.get("degree", 2)
        interaction_only = params.get("interaction_only", False)
        include_bias = params.get("include_bias", False)
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

        # Guard against degree too high for the available data
        poly = PolynomialFeatures(
            degree=degree,
            interaction_only=interaction_only,
            include_bias=include_bias,
        )
        try:
            X_poly = poly.fit_transform(X)
        except Exception as exc:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"PolynomialFeatures error: {exc}",
            )

        if X_poly.shape[1] >= len(subset):
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=(
                    f"Degree {degree} produces {X_poly.shape[1]} features from "
                    f"{len(feature_cols)} inputs, but only {len(subset)} samples "
                    "available. Reduce degree or add more data."
                ),
            )

        expanded_names = poly.get_feature_names_out(feature_cols).tolist()

        train_idx = params.get("train_indices")
        test_idx = params.get("test_indices")

        if train_idx is not None and test_idx is not None:
            X_train, X_test = X_poly[train_idx], X_poly[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
        else:
            X_train, X_test = X_poly, X_poly
            y_train, y_test = y, y

        model = LinearRegression()
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        if train_idx is not None:
            note = "Metrics computed on held-out test set."
        else:
            note = (
                "Metrics are training-set only; use train_val_test_split "
                "for unbiased estimates."
            )

        return ToolResult(
            outputs={
                "feature_names": expanded_names,
                "note": note,
            },
            metrics={
                "r2": float(r2_score(y_test, y_pred)),
                "rmse": float(np.sqrt(mean_squared_error(y_test, y_pred))),
                "mae": float(mean_absolute_error(y_test, y_pred)),
                "n_features_original": float(len(feature_cols)),
                "n_features_expanded": float(X_poly.shape[1]),
            },
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return PolynomialRegressionMethod()
