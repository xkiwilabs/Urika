"""Paired t-test method using scipy."""

from __future__ import annotations

from typing import Any

from scipy.stats import ttest_rel

from urika.data.models import DatasetView
from urika.methods.base import IAnalysisMethod, MethodResult


class PairedTTestMethod(IAnalysisMethod):
    """Paired t-test for comparing two related samples."""

    def name(self) -> str:
        return "paired_t_test"

    def description(self) -> str:
        return "Paired t-test for comparing two related samples using scipy."

    def category(self) -> str:
        return "statistical_test"

    def default_params(self) -> dict[str, Any]:
        return {"column_a": "", "column_b": ""}

    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult:
        col_a = params.get("column_a", "")
        col_b = params.get("column_b", "")
        df = data.data

        for col in (col_a, col_b):
            if col not in df.columns:
                return MethodResult(
                    metrics={}, valid=False, error=f"Column '{col}' not found"
                )

        subset = df[[col_a, col_b]].dropna()
        if len(subset) < 2:
            return MethodResult(
                metrics={},
                valid=False,
                error=f"Insufficient data: {len(subset)} paired observations after dropping NaN",
            )

        t_stat, p_value = ttest_rel(subset[col_a], subset[col_b])

        return MethodResult(
            metrics={
                "t_statistic": float(t_stat),
                "p_value": float(p_value),
            }
        )


def get_method() -> IAnalysisMethod:
    """Factory function for registry auto-discovery."""
    return PairedTTestMethod()
