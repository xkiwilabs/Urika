"""Correlation analysis tool."""

from __future__ import annotations

from typing import Any

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class CorrelationAnalysisTool(ITool):
    """Compute pairwise correlations and rank strongest relationships."""

    def name(self) -> str:
        return "correlation_analysis"

    def description(self) -> str:
        return "Compute pairwise correlations and rank strongest relationships."

    def category(self) -> str:
        return "exploration"

    def default_params(self) -> dict[str, Any]:
        return {"method": "pearson"}

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        method = params.get("method", "pearson")
        numeric_df = data.data.select_dtypes(include="number")
        if numeric_df.shape[1] == 0:
            return ToolResult(
                outputs={}, valid=False, error="No numeric columns in dataset"
            )

        corr_matrix = numeric_df.corr(method=method)

        correlation_matrix = {
            col: {row: float(corr_matrix.loc[row, col]) for row in corr_matrix.index}
            for col in corr_matrix.columns
        }

        seen: set[tuple[str, str]] = set()
        top_correlations: list[dict[str, Any]] = []
        for col_a in corr_matrix.columns:
            for col_b in corr_matrix.columns:
                if col_a == col_b:
                    continue
                pair = tuple(sorted([col_a, col_b]))
                if pair in seen:
                    continue
                seen.add(pair)
                top_correlations.append(
                    {
                        "column_a": pair[0],
                        "column_b": pair[1],
                        "correlation": float(corr_matrix.loc[col_a, col_b]),
                    }
                )

        top_correlations.sort(key=lambda x: abs(x["correlation"]), reverse=True)

        return ToolResult(
            outputs={
                "correlation_matrix": correlation_matrix,
                "top_correlations": top_correlations,
            }
        )


def get_tool() -> ITool:
    """Factory function for auto-discovery."""
    return CorrelationAnalysisTool()
