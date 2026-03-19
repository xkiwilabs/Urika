"""One-way ANOVA tool using scipy."""

from __future__ import annotations

from typing import Any

from scipy.stats import f_oneway

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class OneWayAnovaMethod(ITool):
    """One-way ANOVA for comparing means across groups."""

    def name(self) -> str:
        return "one_way_anova"

    def description(self) -> str:
        return "One-way ANOVA for comparing means across groups using scipy."

    def category(self) -> str:
        return "statistical_test"

    def default_params(self) -> dict[str, Any]:
        return {"group_column": "", "value_column": ""}

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        group_column = params.get("group_column", "")
        value_column = params.get("value_column", "")
        df = data.data

        for col in (group_column, value_column):
            if col not in df.columns:
                return ToolResult(
                    outputs={}, metrics={}, valid=False, error=f"Column '{col}' not found"
                )

        subset = df[[group_column, value_column]].dropna()

        groups = subset.groupby(group_column)[value_column].apply(list).to_dict()

        if len(groups) < 2:
            return ToolResult(
                outputs={}, metrics={},
                valid=False,
                error=f"Need at least 2 groups, found {len(groups)}",
            )

        for grp_name, values in groups.items():
            if len(values) < 2:
                return ToolResult(
                    outputs={}, metrics={},
                    valid=False,
                    error=f"Group '{grp_name}' has fewer than 2 observations",
                )

        group_arrays = list(groups.values())
        f_stat, p_value = f_oneway(*group_arrays)

        return ToolResult(
            outputs={},
            metrics={
                "f_statistic": float(f_stat),
                "p_value": float(p_value),
            }
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return OneWayAnovaMethod()
