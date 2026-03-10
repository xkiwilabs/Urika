"""Outlier detection tool."""

from __future__ import annotations

from typing import Any

import numpy as np

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class OutlierDetectionTool(ITool):
    """Detect outliers using IQR or z-score methods."""

    def name(self) -> str:
        return "outlier_detection"

    def description(self) -> str:
        return "Detect outliers using IQR or z-score methods."

    def category(self) -> str:
        return "exploration"

    def default_params(self) -> dict[str, Any]:
        return {"method": "iqr", "columns": None, "threshold": None}

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        method = params.get("method", "iqr")
        columns = params.get("columns", None)
        threshold = params.get("threshold", None)

        if method not in ("iqr", "zscore"):
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Unsupported method: {method!r}. Must be 'iqr' or 'zscore'.",
            )

        if threshold is None:
            threshold = 1.5 if method == "iqr" else 3.0

        numeric_cols = list(data.data.select_dtypes(include="number").columns)

        if columns is None:
            columns = numeric_cols
        elif isinstance(columns, str):
            columns = [columns]

        if not columns:
            return ToolResult(
                outputs={},
                valid=False,
                error="No numeric columns available for outlier detection",
            )

        # Validate columns exist and are numeric
        for col in columns:
            if col not in data.data.columns:
                return ToolResult(
                    outputs={},
                    valid=False,
                    error=f"Column {col!r} not found in dataset",
                )
            if col not in numeric_cols:
                return ToolResult(
                    outputs={},
                    valid=False,
                    error=f"Column {col!r} is not numeric",
                )

        outlier_counts: dict[str, int] = {}
        outlier_indices: dict[str, list[int]] = {}
        total_outliers = 0

        for col in columns:
            series = data.data[col]

            if method == "iqr":
                q1 = float(series.quantile(0.25))
                q3 = float(series.quantile(0.75))
                iqr = q3 - q1
                lower = q1 - threshold * iqr
                upper = q3 + threshold * iqr
                mask = (series < lower) | (series > upper)
            else:  # zscore
                mean = float(series.mean())
                std = float(series.std())
                if std == 0:
                    mask = series.isna()  # No outliers if no variance
                    mask[:] = False
                else:
                    z_scores = np.abs((series - mean) / std)
                    mask = z_scores > threshold

            indices = list(data.data.index[mask])
            outlier_counts[col] = int(mask.sum())
            outlier_indices[col] = indices
            total_outliers += int(mask.sum())

        return ToolResult(
            outputs={
                "outlier_counts": outlier_counts,
                "total_outliers": total_outliers,
                "n_rows": len(data.data),
                "outlier_indices": outlier_indices,
            }
        )


def get_tool() -> ITool:
    """Factory function for auto-discovery."""
    return OutlierDetectionTool()
