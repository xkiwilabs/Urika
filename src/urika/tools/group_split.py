"""Group-based splitting tool for participant-level train/test separation."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.model_selection import LeaveOneGroupOut

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class GroupSplitTool(ITool):
    """Split dataset by group (e.g., participant), keeping groups intact."""

    def name(self) -> str:
        return "group_split"

    def description(self) -> str:
        return "Group-based splitting (LOGO CV or group train/val/test split) for participant-level separation."

    def category(self) -> str:
        return "preprocessing"

    def default_params(self) -> dict[str, Any]:
        return {
            "group_column": "",
            "mode": "logo",
            "test_groups": 1,
            "val_groups": 0,
            "random_state": 42,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        group_column = params.get("group_column", "")
        mode = params.get("mode", "logo")
        df = data.data

        if not group_column:
            return ToolResult(outputs={}, valid=False, error="group_column is required")

        if group_column not in df.columns:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Group column '{group_column}' not found",
            )

        groups = df[group_column]
        unique_groups = sorted(groups.unique().tolist())
        n_groups = len(unique_groups)

        if n_groups < 2:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Need at least 2 groups, found {n_groups}",
            )

        if mode == "logo":
            return self._logo_split(df, groups, unique_groups, n_groups)
        elif mode == "split":
            return self._group_split(df, groups, unique_groups, n_groups, params)
        else:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Unknown mode '{mode}'. Use 'logo' or 'split'.",
            )

    def _logo_split(self, df, groups, unique_groups, n_groups) -> ToolResult:
        logo = LeaveOneGroupOut()
        folds = []
        for train_idx, test_idx in logo.split(df, groups=groups):
            test_group_vals = sorted(groups.iloc[test_idx].unique().tolist())
            train_group_vals = sorted(groups.iloc[train_idx].unique().tolist())
            folds.append(
                {
                    "test_groups": test_group_vals,
                    "train_groups": train_group_vals,
                    "train_indices": train_idx.tolist(),
                    "test_indices": test_idx.tolist(),
                    "train_size": len(train_idx),
                    "test_size": len(test_idx),
                }
            )

        return ToolResult(
            outputs={"n_groups": n_groups, "folds": folds},
            metrics={"n_groups": float(n_groups)},
        )

    def _group_split(self, df, groups, unique_groups, n_groups, params) -> ToolResult:
        test_n = params.get("test_groups", 1)
        val_n = params.get("val_groups", 0)
        random_state = params.get("random_state", 42)

        needed = test_n + val_n
        if needed >= n_groups:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"test_groups ({test_n}) + val_groups ({val_n}) must be < n_groups ({n_groups})",
            )

        rng = np.random.RandomState(random_state)
        shuffled = list(unique_groups)
        rng.shuffle(shuffled)

        test_grps = shuffled[:test_n]
        val_grps = shuffled[test_n : test_n + val_n]
        train_grps = shuffled[test_n + val_n :]

        test_mask = groups.isin(test_grps)
        val_mask = groups.isin(val_grps)
        train_mask = groups.isin(train_grps)

        test_idx = df.index[test_mask].tolist()
        val_idx = df.index[val_mask].tolist()
        train_idx = df.index[train_mask].tolist()

        n = len(df)
        return ToolResult(
            outputs={
                "train_groups": sorted(train_grps),
                "val_groups": sorted(val_grps),
                "test_groups": sorted(test_grps),
                "train_indices": train_idx,
                "val_indices": val_idx,
                "test_indices": test_idx,
                "train_size": len(train_idx),
                "val_size": len(val_idx),
                "test_size": len(test_idx),
            },
            metrics={
                "n_groups": float(n_groups),
                "train_fraction": len(train_idx) / n,
                "val_fraction": len(val_idx) / n,
                "test_fraction": len(test_idx) / n,
            },
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return GroupSplitTool()
