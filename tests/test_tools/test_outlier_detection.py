"""Tests for OutlierDetectionTool."""

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


class TestOutlierDetectionTool:
    def test_name(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        tool = OutlierDetectionTool()
        assert tool.name() == "outlier_detection"

    def test_description(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        tool = OutlierDetectionTool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        tool = OutlierDetectionTool()
        assert tool.category() == "exploration"

    def test_default_params(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        tool = OutlierDetectionTool()
        params = tool.default_params()
        assert params == {"method": "iqr", "columns": None, "threshold": None}

    def test_basic_iqr(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        # Data with a clear outlier
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0, 100.0]})
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "iqr"})
        assert result.valid is True
        assert "outlier_counts" in result.outputs
        assert "total_outliers" in result.outputs
        assert "n_rows" in result.outputs
        assert "outlier_indices" in result.outputs
        assert result.outputs["n_rows"] == 6
        assert result.outputs["outlier_counts"]["x"] >= 1
        assert result.outputs["total_outliers"] >= 1

    def test_no_outliers(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "iqr"})
        assert result.valid is True
        assert result.outputs["outlier_counts"]["x"] == 0
        assert result.outputs["total_outliers"] == 0

    def test_zscore_method(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        # Use a tight threshold to detect outliers with z-score
        df = pd.DataFrame({"x": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 100.0]})
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "zscore", "threshold": 2.0})
        assert result.valid is True
        assert result.outputs["outlier_counts"]["x"] >= 1

    def test_custom_threshold(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0, 10.0]})
        view = _make_view(df)
        tool = OutlierDetectionTool()

        # With a very tight threshold, more outliers
        result_tight = tool.run(view, {"method": "iqr", "threshold": 0.5})
        # With a loose threshold, fewer outliers
        result_loose = tool.run(view, {"method": "iqr", "threshold": 5.0})

        assert (
            result_tight.outputs["total_outliers"]
            >= result_loose.outputs["total_outliers"]
        )

    def test_multiple_columns(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        df = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0, 4.0, 100.0],
                "b": [10.0, 20.0, 30.0, 40.0, 50.0],
            }
        )
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "iqr"})
        assert result.valid is True
        assert "a" in result.outputs["outlier_counts"]
        assert "b" in result.outputs["outlier_counts"]

    def test_specific_columns(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        df = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0, 4.0, 100.0],
                "b": [10.0, 20.0, 30.0, 40.0, 50.0],
            }
        )
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "iqr", "columns": ["a"]})
        assert result.valid is True
        assert "a" in result.outputs["outlier_counts"]
        assert "b" not in result.outputs["outlier_counts"]

    def test_column_not_found(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "iqr", "columns": ["missing"]})
        assert result.valid is False
        assert "not found" in result.error

    def test_non_numeric_column(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        df = pd.DataFrame({"label": ["a", "b", "c"], "x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "iqr", "columns": ["label"]})
        assert result.valid is False
        assert "not numeric" in result.error

    def test_no_numeric_columns(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        df = pd.DataFrame({"name": ["Alice", "Bob"], "city": ["London", "Paris"]})
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "iqr"})
        assert result.valid is False
        assert "No numeric columns" in result.error

    def test_unsupported_method(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "dbscan"})
        assert result.valid is False
        assert "Unsupported method" in result.error

    def test_outlier_indices_correct(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        # Place outlier at known index
        df = pd.DataFrame({"x": [2.0, 2.0, 2.0, 2.0, 2.0, 100.0]})
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "iqr"})
        assert result.valid is True
        assert 5 in result.outputs["outlier_indices"]["x"]

    def test_zscore_zero_std(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        df = pd.DataFrame({"x": [5.0, 5.0, 5.0, 5.0]})
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "zscore"})
        assert result.valid is True
        assert result.outputs["outlier_counts"]["x"] == 0

    def test_result_type(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        view = _make_view(df)
        tool = OutlierDetectionTool()
        result = tool.run(view, {"method": "iqr"})
        assert isinstance(result, ToolResult)


class TestOutlierDetectionFactory:
    def test_get_tool_returns_instance(self) -> None:
        from urika.tools.outlier_detection import OutlierDetectionTool, get_tool

        tool = get_tool()
        assert isinstance(tool, OutlierDetectionTool)
