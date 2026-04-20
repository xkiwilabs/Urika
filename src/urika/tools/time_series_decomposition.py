"""Time series decomposition tool using statsmodels."""

from __future__ import annotations

from typing import Any

import numpy as np
from statsmodels.tsa.seasonal import seasonal_decompose

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class TimeSeriesDecompositionTool(ITool):
    """Decompose time series into trend, seasonal, and residual components."""

    def name(self) -> str:
        return "time_series_decomposition"

    def description(self) -> str:
        return (
            "Decompose time series into trend, seasonal, and residual components "
            "using classical seasonal decomposition."
        )

    def category(self) -> str:
        return "time_series"

    def default_params(self) -> dict[str, Any]:
        return {
            "column": "",
            "period": None,
            "model": "additive",
            "date_column": None,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        column = params.get("column", "")
        period = params.get("period", None)
        model = params.get("model", "additive")
        date_column = params.get("date_column", None)

        df = data.data

        # --- Validate column exists ---
        if column not in df.columns:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Column '{column}' not found in dataset",
            )

        series = df[column]

        # --- Validate numeric ---
        if not np.issubdtype(series.dtype, np.number):
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Column '{column}' is not numeric",
            )

        # --- Drop NaN and check for all-NaN ---
        if date_column is not None and date_column in df.columns:
            temp = df[[date_column, column]].dropna(subset=[column])
            temp = temp.set_index(date_column).sort_index()
            series = temp[column]
        else:
            series = series.dropna().reset_index(drop=True)

        if len(series) == 0:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Column '{column}' contains no valid (non-NaN) values",
            )

        # --- Auto-detect or validate period ---
        if period is None:
            # Default heuristic: try common periods, fall back to n // 2
            n = len(series)
            if n >= 14:
                period = 7  # weekly seasonality as default
            elif n >= 4:
                period = 2
            else:
                return ToolResult(
                    outputs={},
                    valid=False,
                    error=(
                        f"Insufficient data for decomposition: {n} observations, "
                        "need at least 4"
                    ),
                )

        # --- Check minimum data length (need at least 2 full periods) ---
        min_required = 2 * period
        if len(series) < min_required:
            return ToolResult(
                outputs={},
                valid=False,
                error=(
                    f"Insufficient data for decomposition: {len(series)} observations, "
                    f"need at least {min_required} (2 full periods of {period})"
                ),
            )

        # --- Run decomposition ---
        try:
            result = seasonal_decompose(series, model=model, period=period)
        except Exception as exc:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Decomposition failed: {exc}",
            )

        resid = result.resid.dropna()

        # --- Compute strength metrics ---
        # Trend strength: 1 - Var(residual) / Var(detrended)
        detrended = series - result.trend
        detrended_clean = detrended.dropna()
        if len(detrended_clean) > 0 and np.var(detrended_clean) > 0:
            trend_strength = max(
                0.0, 1.0 - float(np.var(resid) / np.var(detrended_clean))
            )
        else:
            trend_strength = 0.0

        # Seasonal strength: 1 - Var(residual) / Var(deseasonalized)
        deseasonalized = series - result.seasonal
        deseason_clean = deseasonalized.dropna()
        if len(deseason_clean) > 0 and np.var(deseason_clean) > 0:
            seasonal_strength = max(
                0.0, 1.0 - float(np.var(resid) / np.var(deseason_clean))
            )
        else:
            seasonal_strength = 0.0

        residual_std = float(np.std(resid)) if len(resid) > 0 else 0.0

        return ToolResult(
            outputs={
                "period_used": int(period),
                "model_type": model,
                "n_observations": len(series),
                "note": (
                    f"Decomposed {len(series)} observations with period={period}, "
                    f"model={model}"
                ),
            },
            metrics={
                "trend_strength": trend_strength,
                "seasonal_strength": seasonal_strength,
                "residual_std": residual_std,
            },
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return TimeSeriesDecompositionTool()
