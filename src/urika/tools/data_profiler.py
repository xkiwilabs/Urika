"""Data profiler tool — wraps profile_dataset() as a tool."""

from __future__ import annotations

from typing import Any

from urika.data.models import DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ITool, ToolResult


class DataProfilerTool(ITool):
    """Profile a dataset for counts, dtypes, missing data, and numeric stats."""

    def name(self) -> str:
        return "data_profiler"

    def description(self) -> str:
        return (
            "Profile a dataset: counts, dtypes, missing data, and numeric statistics."
        )

    def category(self) -> str:
        return "exploration"

    def default_params(self) -> dict[str, Any]:
        return {}

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        summary = profile_dataset(data.data)
        outputs: dict[str, Any] = {
            "n_rows": summary.n_rows,
            "n_columns": summary.n_columns,
            "columns": summary.columns,
            "dtypes": summary.dtypes,
            "missing_counts": summary.missing_counts,
        }
        if summary.numeric_stats:
            outputs["numeric_stats"] = summary.numeric_stats
        return ToolResult(outputs=outputs)


def get_tool() -> ITool:
    """Factory function for auto-discovery."""
    return DataProfilerTool()
