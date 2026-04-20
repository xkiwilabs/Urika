"""Tests for TimeSeriesDecompositionTool."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ToolResult


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestTimeSeriesDecompositionTool:
    def test_name(self) -> None:
        from urika.tools.time_series_decomposition import (
            TimeSeriesDecompositionTool,
        )

        tool = TimeSeriesDecompositionTool()
        assert tool.name() == "time_series_decomposition"

    def test_description(self) -> None:
        from urika.tools.time_series_decomposition import (
            TimeSeriesDecompositionTool,
        )

        tool = TimeSeriesDecompositionTool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        from urika.tools.time_series_decomposition import (
            TimeSeriesDecompositionTool,
        )

        tool = TimeSeriesDecompositionTool()
        assert tool.category() == "time_series"

    def test_default_params(self) -> None:
        from urika.tools.time_series_decomposition import (
            TimeSeriesDecompositionTool,
        )

        tool = TimeSeriesDecompositionTool()
        params = tool.default_params()
        assert "column" in params
        assert "period" in params
        assert "model" in params
        assert params["model"] == "additive"
        assert "date_column" in params

    def test_additive_decomposition(self) -> None:
        from urika.tools.time_series_decomposition import (
            TimeSeriesDecompositionTool,
        )

        # Create data with known trend + seasonal pattern
        n = 100
        t = np.arange(n, dtype=float)
        trend = 0.5 * t
        seasonal = 10.0 * np.sin(2 * np.pi * t / 7)
        values = trend + seasonal + np.random.default_rng(42).normal(0, 0.5, n)
        df = pd.DataFrame({"value": values})
        view = _make_view(df)

        tool = TimeSeriesDecompositionTool()
        result = tool.run(view, {"column": "value", "period": 7, "model": "additive"})

        assert result.valid is True
        assert result.metrics["trend_strength"] > 0
        assert result.metrics["seasonal_strength"] > 0
        assert "residual_std" in result.metrics
        assert result.outputs["period_used"] == 7
        assert result.outputs["model_type"] == "additive"
        assert result.outputs["n_observations"] == n

    def test_multiplicative_decomposition(self) -> None:
        from urika.tools.time_series_decomposition import (
            TimeSeriesDecompositionTool,
        )

        # Multiplicative: base * seasonal factor (all positive values required)
        n = 100
        t = np.arange(n, dtype=float)
        trend = 50.0 + 0.5 * t
        seasonal_factor = 1.0 + 0.3 * np.sin(2 * np.pi * t / 7)
        values = trend * seasonal_factor
        df = pd.DataFrame({"value": values})
        view = _make_view(df)

        tool = TimeSeriesDecompositionTool()
        result = tool.run(
            view, {"column": "value", "period": 7, "model": "multiplicative"}
        )

        assert result.valid is True
        assert result.outputs["model_type"] == "multiplicative"
        assert result.metrics["trend_strength"] > 0

    def test_auto_period(self) -> None:
        from urika.tools.time_series_decomposition import (
            TimeSeriesDecompositionTool,
        )

        # Omit period, should auto-detect/default
        n = 56  # 8 weeks of daily data
        t = np.arange(n, dtype=float)
        values = 10.0 + 0.1 * t + 5.0 * np.sin(2 * np.pi * t / 7)
        df = pd.DataFrame({"value": values})
        view = _make_view(df)

        tool = TimeSeriesDecompositionTool()
        result = tool.run(view, {"column": "value"})

        assert result.valid is True
        assert result.outputs["period_used"] > 0

    def test_missing_column(self) -> None:
        from urika.tools.time_series_decomposition import (
            TimeSeriesDecompositionTool,
        )

        df = pd.DataFrame({"value": [1.0, 2.0, 3.0]})
        view = _make_view(df)

        tool = TimeSeriesDecompositionTool()
        result = tool.run(view, {"column": "nonexistent", "period": 2})

        assert result.valid is False
        assert "nonexistent" in result.error

    def test_insufficient_data(self) -> None:
        from urika.tools.time_series_decomposition import (
            TimeSeriesDecompositionTool,
        )

        # Only 5 observations with period=7 requires 14
        df = pd.DataFrame({"value": [1.0, 2.0, 3.0, 4.0, 5.0]})
        view = _make_view(df)

        tool = TimeSeriesDecompositionTool()
        result = tool.run(view, {"column": "value", "period": 7})

        assert result.valid is False
        assert "Insufficient" in result.error

    def test_result_type(self) -> None:
        from urika.tools.time_series_decomposition import (
            TimeSeriesDecompositionTool,
        )

        n = 28
        t = np.arange(n, dtype=float)
        values = t + 5.0 * np.sin(2 * np.pi * t / 7)
        df = pd.DataFrame({"value": values})
        view = _make_view(df)

        tool = TimeSeriesDecompositionTool()
        result = tool.run(view, {"column": "value", "period": 7})
        assert isinstance(result, ToolResult)

    def test_get_tool_returns_instance(self) -> None:
        from urika.tools.time_series_decomposition import (
            TimeSeriesDecompositionTool,
            get_tool,
        )

        tool = get_tool()
        assert isinstance(tool, TimeSeriesDecompositionTool)
