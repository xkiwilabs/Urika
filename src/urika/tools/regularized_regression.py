"""Regularized regression tools (Lasso, Ridge, ElasticNet) with CV alpha selection."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.linear_model import ElasticNetCV, LassoCV, RidgeCV
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class RegularizedRegressionMethod(ITool):
    """Lasso, Ridge, and ElasticNet regression with cross-validated alpha selection."""

    def name(self) -> str:
        return "regularized_regression"

    def description(self) -> str:
        return (
            "Lasso, Ridge, and ElasticNet regression with cross-validated alpha "
            "selection and automatic feature selection (for Lasso/ElasticNet). "
            "Uses scikit-learn's LassoCV, RidgeCV, and ElasticNetCV."
        )

    def category(self) -> str:
        return "regression"

    def default_params(self) -> dict[str, Any]:
        return {
            "target": "",
            "features": None,
            "method": "lasso",
            "cv_folds": 5,
            "train_indices": None,
            "test_indices": None,
            "l1_ratio": 0.5,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        target = params.get("target", "")
        features = params.get("features")
        method = params.get("method", "lasso")
        cv_folds = params.get("cv_folds", 5)
        l1_ratio = params.get("l1_ratio", 0.5)
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
            X_train, X_test = X, X
            y_train, y_test = y, y

        # Ensure cv_folds does not exceed training samples
        effective_cv = min(cv_folds, len(X_train))
        if effective_cv < 2:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Insufficient training data for cross-validation: {len(X_train)} samples",
            )

        if method == "ridge":
            model = RidgeCV(
                alphas=np.logspace(-6, 6, 50),
                cv=effective_cv,
            )
        elif method == "elasticnet":
            model = ElasticNetCV(
                l1_ratio=l1_ratio,
                cv=effective_cv,
                random_state=42,
            )
        else:
            # Default to lasso
            model = LassoCV(
                cv=effective_cv,
                random_state=42,
            )

        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        best_alpha = float(model.alpha_)
        coefficients = dict(zip(feature_cols, model.coef_.tolist()))

        # Identify selected features (non-zero coefficients) for lasso/elasticnet
        if method in ("lasso", "elasticnet"):
            selected_features = [
                f for f, c in zip(feature_cols, model.coef_) if abs(c) > 0
            ]
            n_features_selected = len(selected_features)

            if n_features_selected == 0:
                return ToolResult(
                    outputs={
                        "selected_features": [],
                        "coefficients": coefficients,
                        "note": "All features were eliminated by regularization.",
                    },
                    metrics={
                        "r2": float(r2_score(y_test, y_pred)),
                        "rmse": float(np.sqrt(mean_squared_error(y_test, y_pred))),
                        "mae": float(mean_absolute_error(y_test, y_pred)),
                        "best_alpha": best_alpha,
                        "n_features_selected": 0,
                    },
                    valid=True,
                )
        else:
            # Ridge keeps all features
            selected_features = list(feature_cols)
            n_features_selected = len(selected_features)

        if train_idx is not None:
            note = "Metrics computed on held-out test set."
        else:
            note = "Metrics are training-set only; use train_val_test_split for unbiased estimates."

        return ToolResult(
            outputs={
                "selected_features": selected_features,
                "coefficients": coefficients,
                "note": note,
            },
            metrics={
                "r2": float(r2_score(y_test, y_pred)),
                "rmse": float(np.sqrt(mean_squared_error(y_test, y_pred))),
                "mae": float(mean_absolute_error(y_test, y_pred)),
                "best_alpha": best_alpha,
                "n_features_selected": n_features_selected,
            },
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return RegularizedRegressionMethod()
