"""Logistic regression tool using scikit-learn."""

from __future__ import annotations

from typing import Any

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class LogisticRegressionMethod(ITool):
    """Logistic regression for binary and multiclass classification."""

    def name(self) -> str:
        return "logistic_regression"

    def description(self) -> str:
        return "Logistic regression for classification using scikit-learn."

    def category(self) -> str:
        return "classification"

    def default_params(self) -> dict[str, Any]:
        return {"target": "", "features": None}

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

        subset = df[[target, *feature_cols]].dropna()
        if len(subset) < 2:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Insufficient data: {len(subset)} rows after dropping NaN",
            )

        classes = subset[target].nunique()
        if classes < 2:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Need at least 2 classes in target, found {classes}",
            )

        X = subset[feature_cols].values  # noqa: N806
        y = subset[target].values

        model = LogisticRegression(max_iter=1000)
        model.fit(X, y)
        y_pred = model.predict(X)

        avg = "binary" if classes == 2 else "weighted"

        return ToolResult(
            outputs={},
            metrics={
                "accuracy": float(accuracy_score(y, y_pred)),
                "f1": float(f1_score(y, y_pred, average=avg)),
            },
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return LogisticRegressionMethod()
