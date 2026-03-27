"""Train/validation/test split tool using scikit-learn."""

from __future__ import annotations

from typing import Any

from sklearn.model_selection import train_test_split

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class TrainValTestSplitTool(ITool):
    """Split dataset into train, optional validation, and test sets."""

    def name(self) -> str:
        return "train_val_test_split"

    def description(self) -> str:
        return "Split dataset into train/validation/test sets with optional stratification."

    def category(self) -> str:
        return "preprocessing"

    def default_params(self) -> dict[str, Any]:
        return {
            "test_size": 0.2,
            "val_size": 0.0,
            "random_state": 42,
            "stratify_column": None,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        test_size = params.get("test_size", 0.2)
        val_size = params.get("val_size", 0.0)
        random_state = params.get("random_state", 42)
        stratify_column = params.get("stratify_column")
        df = data.data

        if len(df) < 2:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error="Insufficient data for splitting",
            )

        if test_size + val_size >= 1.0:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"test_size ({test_size}) + val_size ({val_size}) must be < 1.0",
            )

        stratify = None
        if stratify_column is not None:
            if stratify_column not in df.columns:
                return ToolResult(
                    outputs={},
                    metrics={},
                    valid=False,
                    error=f"Stratify column '{stratify_column}' not found",
                )
            stratify = df[stratify_column]

        indices = list(range(len(df)))

        try:
            train_val_idx, test_idx = train_test_split(
                indices,
                test_size=test_size,
                random_state=random_state,
                stratify=stratify,
            )
        except ValueError as exc:
            return ToolResult(outputs={}, metrics={}, valid=False, error=str(exc))

        val_idx: list[int] = []
        if val_size > 0:
            # val_size is relative to original data, convert to fraction of train_val
            relative_val = val_size / (1.0 - test_size)
            val_stratify = None
            if stratify is not None:
                val_stratify = stratify.iloc[train_val_idx]
            try:
                train_idx, val_idx = train_test_split(
                    train_val_idx,
                    test_size=relative_val,
                    random_state=random_state,
                    stratify=val_stratify,
                )
            except ValueError as exc:
                return ToolResult(outputs={}, metrics={}, valid=False, error=str(exc))
        else:
            train_idx = train_val_idx

        n = len(df)
        return ToolResult(
            outputs={
                "train_size": len(train_idx),
                "val_size": len(val_idx),
                "test_size": len(test_idx),
                "train_indices": train_idx,
                "val_indices": val_idx,
                "test_indices": test_idx,
            },
            metrics={
                "train_fraction": len(train_idx) / n,
                "val_fraction": len(val_idx) / n,
                "test_fraction": len(test_idx) / n,
            },
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return TrainValTestSplitTool()
