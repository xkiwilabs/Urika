"""Feature scaling tool using scikit-learn."""

from __future__ import annotations

from typing import Any

from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class FeatureScalerTool(ITool):
    """Scale numeric features using standard, minmax, or robust scaling."""

    def name(self) -> str:
        return "feature_scaler"

    def description(self) -> str:
        return "Scale numeric features using standard, minmax, or robust scaling."

    def category(self) -> str:
        return "preprocessing"

    def default_params(self) -> dict[str, Any]:
        return {
            "method": "standard",
            "columns": None,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        method = params.get("method", "standard")
        columns = params.get("columns")
        df = data.data

        valid_methods = ("standard", "minmax", "robust")
        if method not in valid_methods:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Invalid method '{method}'. Must be one of: {', '.join(valid_methods)}",
            )

        numeric_df = df.select_dtypes(include="number")
        if columns is not None:
            numeric_cols = [c for c in columns if c in numeric_df.columns]
        else:
            numeric_cols = list(numeric_df.columns)

        if not numeric_cols:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error="No numeric columns available for scaling",
            )

        subset = numeric_df[numeric_cols].dropna()

        if method == "standard":
            scaler = StandardScaler()
        elif method == "minmax":
            scaler = MinMaxScaler()
        else:
            scaler = RobustScaler()

        scaler.fit(subset)

        statistics: dict[str, dict[str, float]] = {}
        if method == "standard":
            for i, col in enumerate(numeric_cols):
                statistics[col] = {
                    "mean": float(scaler.mean_[i]),
                    "std": float(scaler.scale_[i]),
                }
        elif method == "minmax":
            for i, col in enumerate(numeric_cols):
                statistics[col] = {
                    "min": float(scaler.data_min_[i]),
                    "max": float(scaler.data_max_[i]),
                }
        else:  # robust
            for i, col in enumerate(numeric_cols):
                statistics[col] = {
                    "center": float(scaler.center_[i]),
                    "scale": float(scaler.scale_[i]),
                }

        return ToolResult(
            outputs={
                "scaled_columns": numeric_cols,
                "scaler_type": method,
                "statistics": statistics,
            },
            metrics={},
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return FeatureScalerTool()
