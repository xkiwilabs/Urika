"""Mann-Whitney U test tool using scipy."""

from __future__ import annotations

from typing import Any

from scipy.stats import mannwhitneyu

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class MannWhitneyUMethod(ITool):
    """Mann-Whitney U test for comparing two independent samples."""

    def name(self) -> str:
        return "mann_whitney_u"

    def description(self) -> str:
        return "Mann-Whitney U test for comparing two independent samples using scipy."

    def category(self) -> str:
        return "statistical_test"

    def default_params(self) -> dict[str, Any]:
        return {"column_a": "", "column_b": ""}

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        col_a = params.get("column_a", "")
        col_b = params.get("column_b", "")
        df = data.data

        for col in (col_a, col_b):
            if col not in df.columns:
                return ToolResult(
                    outputs={}, metrics={}, valid=False, error=f"Column '{col}' not found"
                )

        subset = df[[col_a, col_b]].dropna()
        if len(subset) < 2:
            return ToolResult(
                outputs={}, metrics={},
                valid=False,
                error=f"Insufficient data: {len(subset)} rows after dropping NaN",
            )

        u_stat, p_value = mannwhitneyu(subset[col_a], subset[col_b])

        return ToolResult(
            outputs={},
            metrics={
                "u_statistic": float(u_stat),
                "p_value": float(p_value),
            }
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return MannWhitneyUMethod()
