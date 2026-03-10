"""Hypothesis tests tool."""

from __future__ import annotations

from typing import Any

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class HypothesisTestsTool(ITool):
    """Run statistical hypothesis tests: t-test, chi-squared, and normality."""

    def name(self) -> str:
        return "hypothesis_tests"

    def description(self) -> str:
        return "Run statistical hypothesis tests: t-test, chi-squared, and normality."

    def category(self) -> str:
        return "statistics"

    def default_params(self) -> dict[str, Any]:
        return {
            "test_type": "t_test",
            "column_a": None,
            "column_b": None,
            "column": None,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        from scipy import stats

        test_type = params.get("test_type", "t_test")

        if test_type == "t_test":
            return self._run_t_test(data, params, stats)
        elif test_type == "chi_squared":
            return self._run_chi_squared(data, params, stats)
        elif test_type == "normality":
            return self._run_normality(data, params, stats)
        else:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Unsupported test_type: {test_type!r}. "
                f"Must be 't_test', 'chi_squared', or 'normality'.",
            )

    def _run_t_test(
        self, data: DatasetView, params: dict[str, Any], stats: Any
    ) -> ToolResult:
        column_a = params.get("column_a")
        column_b = params.get("column_b")

        if column_a is None or column_b is None:
            return ToolResult(
                outputs={},
                valid=False,
                error="t_test requires both column_a and column_b",
            )

        for col in (column_a, column_b):
            if col not in data.data.columns:
                return ToolResult(
                    outputs={},
                    valid=False,
                    error=f"Column {col!r} not found in dataset",
                )

        series_a = data.data[column_a].dropna()
        series_b = data.data[column_b].dropna()

        if len(series_a) < 2 or len(series_b) < 2:
            return ToolResult(
                outputs={},
                valid=False,
                error="t_test requires at least 2 values per group",
            )

        t_stat, p_value = stats.ttest_ind(series_a, series_b)

        return ToolResult(
            outputs={
                "t_statistic": float(t_stat),
                "p_value": float(p_value),
                "mean_a": float(series_a.mean()),
                "mean_b": float(series_b.mean()),
            }
        )

    def _run_chi_squared(
        self, data: DatasetView, params: dict[str, Any], stats: Any
    ) -> ToolResult:
        import pandas as pd

        column_a = params.get("column_a")
        column_b = params.get("column_b")

        if column_a is None or column_b is None:
            return ToolResult(
                outputs={},
                valid=False,
                error="chi_squared requires both column_a and column_b",
            )

        for col in (column_a, column_b):
            if col not in data.data.columns:
                return ToolResult(
                    outputs={},
                    valid=False,
                    error=f"Column {col!r} not found in dataset",
                )

        crosstab = pd.crosstab(data.data[column_a], data.data[column_b])
        chi2, p_value, dof, _expected = stats.chi2_contingency(crosstab)

        return ToolResult(
            outputs={
                "chi2": float(chi2),
                "p_value": float(p_value),
                "dof": int(dof),
            }
        )

    def _run_normality(
        self, data: DatasetView, params: dict[str, Any], stats: Any
    ) -> ToolResult:
        column = params.get("column")

        if column is None:
            return ToolResult(
                outputs={},
                valid=False,
                error="normality test requires 'column' parameter",
            )

        if column not in data.data.columns:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Column {column!r} not found in dataset",
            )

        series = data.data[column].dropna()

        if len(series) < 3:
            return ToolResult(
                outputs={},
                valid=False,
                error="normality test requires at least 3 values",
            )

        w_stat, p_value = stats.shapiro(series)

        return ToolResult(
            outputs={
                "w_statistic": float(w_stat),
                "p_value": float(p_value),
            }
        )


def get_tool() -> ITool:
    """Factory function for auto-discovery."""
    return HypothesisTestsTool()
