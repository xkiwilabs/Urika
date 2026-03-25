"""Tests for FeatureScalerTool."""

from __future__ import annotations

import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ToolResult
from urika.tools.feature_scaler import FeatureScalerTool, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestFeatureScalerTool:
    def test_name(self) -> None:
        tool = FeatureScalerTool()
        assert tool.name() == "feature_scaler"

    def test_description(self) -> None:
        tool = FeatureScalerTool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        tool = FeatureScalerTool()
        assert tool.category() == "preprocessing"

    def test_default_params(self) -> None:
        tool = FeatureScalerTool()
        params = tool.default_params()
        assert params["method"] == "standard"
        assert params["columns"] is None

    def test_standard_scaling(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0], "b": [10.0, 20.0, 30.0, 40.0, 50.0]})
        view = _make_view(df)
        tool = FeatureScalerTool()
        result = tool.run(view, {"method": "standard"})
        assert result.valid is True
        assert result.outputs["scaler_type"] == "standard"
        assert set(result.outputs["scaled_columns"]) == {"a", "b"}
        assert "mean" in result.outputs["statistics"]["a"]
        assert "std" in result.outputs["statistics"]["a"]
        assert result.metrics == {}

    def test_minmax_scaling(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0]})
        view = _make_view(df)
        tool = FeatureScalerTool()
        result = tool.run(view, {"method": "minmax"})
        assert result.valid is True
        assert result.outputs["scaler_type"] == "minmax"
        assert "min" in result.outputs["statistics"]["a"]
        assert "max" in result.outputs["statistics"]["a"]
        assert result.outputs["statistics"]["a"]["min"] == 1.0
        assert result.outputs["statistics"]["a"]["max"] == 5.0

    def test_robust_scaling(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0]})
        view = _make_view(df)
        tool = FeatureScalerTool()
        result = tool.run(view, {"method": "robust"})
        assert result.valid is True
        assert result.outputs["scaler_type"] == "robust"
        assert "center" in result.outputs["statistics"]["a"]
        assert "scale" in result.outputs["statistics"]["a"]

    def test_invalid_method_returns_invalid(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = FeatureScalerTool()
        result = tool.run(view, {"method": "invalid"})
        assert result.valid is False
        assert "Invalid method" in result.error

    def test_no_numeric_columns_returns_invalid(self) -> None:
        df = pd.DataFrame({"a": ["x", "y", "z"], "b": ["p", "q", "r"]})
        view = _make_view(df)
        tool = FeatureScalerTool()
        result = tool.run(view, {"method": "standard"})
        assert result.valid is False
        assert "No numeric columns" in result.error

    def test_specific_columns(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0], "c": [7.0, 8.0, 9.0]})
        view = _make_view(df)
        tool = FeatureScalerTool()
        result = tool.run(view, {"method": "standard", "columns": ["a", "c"]})
        assert result.valid is True
        assert result.outputs["scaled_columns"] == ["a", "c"]

    def test_result_type(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = FeatureScalerTool()
        result = tool.run(view, {"method": "standard"})
        assert isinstance(result, ToolResult)


class TestFeatureScalerFactory:
    def test_get_tool_returns_instance(self) -> None:
        tool = get_tool()
        assert isinstance(tool, FeatureScalerTool)
