"""Descriptive statistics method using pandas and scipy."""

from __future__ import annotations

from typing import Any

from scipy.stats import kurtosis, skew

from urika.data.models import DatasetView
from urika.methods.base import IAnalysisMethod, MethodResult


class DescriptiveStatsMethod(IAnalysisMethod):
    """Descriptive statistics for numeric columns."""

    def name(self) -> str:
        return "descriptive_stats"

    def description(self) -> str:
        return (
            "Descriptive statistics (mean, std, skew, kurtosis) using pandas and scipy."
        )

    def category(self) -> str:
        return "statistics"

    def default_params(self) -> dict[str, Any]:
        return {"columns": None}

    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult:
        columns = params.get("columns")
        df = data.data

        numeric_df = df.select_dtypes(include="number")

        if columns is not None:
            missing = [c for c in columns if c not in df.columns]
            if missing:
                return MethodResult(
                    metrics={},
                    valid=False,
                    error=f"Columns not found: {', '.join(missing)}",
                )
            numeric_df = numeric_df[[c for c in columns if c in numeric_df.columns]]

        if numeric_df.shape[1] == 0:
            return MethodResult(
                metrics={},
                valid=False,
                error="No numeric columns available",
            )

        clean = numeric_df.dropna(how="all")
        if len(clean) < 1:
            return MethodResult(
                metrics={},
                valid=False,
                error="No data after dropping all-NaN rows",
            )

        # Compute per-column stats as observations; metrics are summary counts
        observations: list[str] = []
        for col in numeric_df.columns:
            vals = numeric_df[col].dropna()
            if len(vals) == 0:
                continue
            col_skew = float(skew(vals, nan_policy="omit"))
            col_kurt = float(kurtosis(vals, nan_policy="omit"))
            observations.append(
                f"{col}: mean={vals.mean():.4f}, std={vals.std():.4f}, "
                f"skew={col_skew:.4f}, kurtosis={col_kurt:.4f}"
            )

        return MethodResult(
            metrics={
                "n_rows": float(len(df)),
                "n_columns": float(numeric_df.shape[1]),
            },
            artifacts=observations,
        )


def get_method() -> IAnalysisMethod:
    """Factory function for registry auto-discovery."""
    return DescriptiveStatsMethod()
