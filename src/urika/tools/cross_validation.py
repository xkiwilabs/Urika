"""K-fold cross-validation split tool using scikit-learn."""

from __future__ import annotations

from typing import Any

from sklearn.model_selection import KFold, StratifiedKFold

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class CrossValidationTool(ITool):
    """Generate k-fold cross-validation splits."""

    def name(self) -> str:
        return "cross_validation"

    def description(self) -> str:
        return "Generate k-fold cross-validation splits with optional stratification."

    def category(self) -> str:
        return "preprocessing"

    def default_params(self) -> dict[str, Any]:
        return {
            "n_folds": 5,
            "random_state": 42,
            "shuffle": True,
            "stratify_column": None,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        n_folds = params.get("n_folds", 5)
        random_state = params.get("random_state", 42)
        shuffle = params.get("shuffle", True)
        stratify_column = params.get("stratify_column")
        df = data.data
        n = len(df)

        if n_folds < 2:
            return ToolResult(
                outputs={}, valid=False, error="n_folds must be at least 2"
            )

        if n_folds > n:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"n_folds ({n_folds}) cannot exceed number of samples ({n})",
            )

        # sklearn raises if random_state is set when shuffle is False
        effective_random_state = random_state if shuffle else None

        try:
            if stratify_column is not None:
                if stratify_column not in df.columns:
                    return ToolResult(
                        outputs={},
                        valid=False,
                        error=f"Stratify column '{stratify_column}' not found",
                    )
                y = df[stratify_column]
                splitter = StratifiedKFold(
                    n_splits=n_folds,
                    shuffle=shuffle,
                    random_state=effective_random_state,
                )
                splits = list(splitter.split(df, y))
            else:
                splitter = KFold(
                    n_splits=n_folds,
                    shuffle=shuffle,
                    random_state=effective_random_state,
                )
                splits = list(splitter.split(df))
        except ValueError as exc:
            return ToolResult(outputs={}, valid=False, error=str(exc))

        folds = []
        total_test = 0
        for i, (train_idx, test_idx) in enumerate(splits):
            folds.append(
                {
                    "fold": i + 1,
                    "train_indices": train_idx.tolist(),
                    "test_indices": test_idx.tolist(),
                    "train_size": len(train_idx),
                    "test_size": len(test_idx),
                }
            )
            total_test += len(test_idx)

        return ToolResult(
            outputs={
                "n_folds": n_folds,
                "folds": folds,
            },
            metrics={
                "n_folds": float(n_folds),
                "avg_test_size": total_test / n_folds,
            },
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return CrossValidationTool()
