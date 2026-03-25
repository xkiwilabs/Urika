"""Random forest classification tool using scikit-learn."""

from __future__ import annotations

from typing import Any

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class RandomForestClassifierMethod(ITool):
    """Random forest classification using scikit-learn."""

    def name(self) -> str:
        return "random_forest_classifier"

    def category(self) -> str:
        return "classification"

    def description(self) -> str:
        return (
            "Random forest classification using scikit-learn. "
            "Supports pre-split train/test indices for "
            "unbiased evaluation."
        )

    def default_params(self) -> dict[str, Any]:
        return {
            "target": "",
            "features": None,
            "n_estimators": 100,
            "max_depth": None,
            "random_state": 42,
            "train_indices": None,
            "test_indices": None,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        target = params.get("target", "")
        features = params.get("features")
        n_estimators = params.get("n_estimators", 100)
        max_depth = params.get("max_depth")
        random_state = params.get("random_state", 42)
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
            feature_cols = [c for c in features if c in numeric_df.columns]

        if not feature_cols:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error="No feature columns available",
            )

        subset = df[[target, *feature_cols]].dropna().reset_index(drop=True)
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

        train_idx = params.get("train_indices")
        test_idx = params.get("test_indices")
        if train_idx is not None and test_idx is not None:
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
            note = "Metrics computed on held-out test set."
        else:
            X_train, X_test = X, X
            y_train, y_test = y, y
            note = (
                "Metrics are training-set only; use "
                "cross_validation or train_val_test_split "
                "for unbiased estimates."
            )

        model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=random_state,
        )
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        avg = "binary" if classes == 2 else "weighted"

        return ToolResult(
            outputs={"note": note},
            metrics={
                "accuracy": float(accuracy_score(y_test, y_pred)),
                "f1": float(f1_score(y_test, y_pred, average=avg)),
            },
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return RandomForestClassifierMethod()
