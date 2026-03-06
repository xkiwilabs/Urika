"""Tests for DataProfilerTool."""

from __future__ import annotations

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


class TestDataProfilerTool:
    def test_name(self) -> None:
        from urika.tools.data_profiler import DataProfilerTool

        tool = DataProfilerTool()
        assert tool.name() == "data_profiler"

    def test_description(self) -> None:
        from urika.tools.data_profiler import DataProfilerTool

        tool = DataProfilerTool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        from urika.tools.data_profiler import DataProfilerTool

        tool = DataProfilerTool()
        assert tool.category() == "exploration"

    def test_default_params(self) -> None:
        from urika.tools.data_profiler import DataProfilerTool

        tool = DataProfilerTool()
        assert tool.default_params() == {}

    def test_basic_profiling(self) -> None:
        from urika.tools.data_profiler import DataProfilerTool

        df = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0], "c": ["x", "y", "z"]})
        view = _make_view(df)
        tool = DataProfilerTool()
        result = tool.run(view, {})
        assert result.valid is True
        assert result.outputs["n_rows"] == 3
        assert result.outputs["n_columns"] == 3
        assert result.outputs["columns"] == ["a", "b", "c"]
        assert "a" in result.outputs["dtypes"]
        assert "a" in result.outputs["missing_counts"]
        assert "a" in result.outputs["numeric_stats"]

    def test_missing_data_counted(self) -> None:
        from urika.tools.data_profiler import DataProfilerTool

        df = pd.DataFrame(
            {"x": [1.0, float("nan"), 3.0], "y": [float("nan"), float("nan"), 1.0]}
        )
        view = _make_view(df)
        tool = DataProfilerTool()
        result = tool.run(view, {})
        assert result.outputs["missing_counts"]["x"] == 1
        assert result.outputs["missing_counts"]["y"] == 2

    def test_no_numeric_columns_returns_invalid(self) -> None:
        from urika.tools.data_profiler import DataProfilerTool

        df = pd.DataFrame({"name": ["Alice", "Bob"], "city": ["London", "Paris"]})
        view = _make_view(df)
        tool = DataProfilerTool()
        result = tool.run(view, {})
        assert result.valid is False
        assert result.error is not None

    def test_result_type(self) -> None:
        from urika.tools.data_profiler import DataProfilerTool

        df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
        view = _make_view(df)
        tool = DataProfilerTool()
        result = tool.run(view, {})
        assert isinstance(result, ToolResult)

    def test_numeric_stats_keys(self) -> None:
        from urika.tools.data_profiler import DataProfilerTool

        df = pd.DataFrame({"val": [10.0, 20.0, 30.0, 40.0, 50.0]})
        view = _make_view(df)
        tool = DataProfilerTool()
        result = tool.run(view, {})
        stats = result.outputs["numeric_stats"]["val"]
        assert "mean" in stats
        assert "std" in stats
        assert "min" in stats
        assert "max" in stats
        assert "median" in stats


class TestDataProfilerFactory:
    def test_get_tool_returns_instance(self) -> None:
        from urika.tools.data_profiler import DataProfilerTool, get_tool

        tool = get_tool()
        assert isinstance(tool, DataProfilerTool)
