"""Tests for TrainValTestSplitTool."""

from __future__ import annotations

import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ITool, ToolResult
from urika.tools.train_val_test_split import TrainValTestSplitTool, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestTrainValTestSplitTool:
    def test_name(self) -> None:
        tool = TrainValTestSplitTool()
        assert tool.name() == "train_val_test_split"

    def test_description(self) -> None:
        tool = TrainValTestSplitTool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        tool = TrainValTestSplitTool()
        assert tool.category() == "preprocessing"

    def test_default_params(self) -> None:
        tool = TrainValTestSplitTool()
        params = tool.default_params()
        assert params["test_size"] == 0.2
        assert params["val_size"] == 0.0
        assert params["random_state"] == 42
        assert params["stratify_column"] is None

    def test_default_80_20_split(self) -> None:
        df = pd.DataFrame({"x": range(100), "y": range(100)})
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result = tool.run(view, {"test_size": 0.2})
        assert result.valid is True
        assert result.outputs["train_size"] == 80
        assert result.outputs["test_size"] == 20
        assert result.outputs["val_size"] == 0
        assert result.outputs["val_indices"] == []

    def test_three_way_split(self) -> None:
        df = pd.DataFrame({"x": range(100), "y": range(100)})
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result = tool.run(view, {"test_size": 0.2, "val_size": 0.1})
        assert result.valid is True
        assert result.outputs["test_size"] == 20
        assert result.outputs["val_size"] == 10
        assert result.outputs["train_size"] == 70

    def test_stratified_split(self) -> None:
        df = pd.DataFrame(
            {
                "x": range(100),
                "label": [0] * 50 + [1] * 50,
            }
        )
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result = tool.run(view, {"test_size": 0.2, "stratify_column": "label"})
        assert result.valid is True
        # Check that test set has roughly balanced classes
        test_labels = df.iloc[result.outputs["test_indices"]]["label"]
        assert test_labels.sum() == 10  # 10 of class 1 out of 20 test

    def test_custom_random_state(self) -> None:
        df = pd.DataFrame({"x": range(50)})
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result_a = tool.run(view, {"test_size": 0.2, "random_state": 1})
        result_b = tool.run(view, {"test_size": 0.2, "random_state": 2})
        assert result_a.valid is True
        assert result_b.valid is True
        # Different random states should produce different splits
        assert result_a.outputs["test_indices"] != result_b.outputs["test_indices"]

    def test_error_insufficient_data(self) -> None:
        df = pd.DataFrame({"x": [1]})
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result = tool.run(view, {"test_size": 0.2})
        assert result.valid is False
        assert "Insufficient data" in result.error

    def test_error_invalid_ratios(self) -> None:
        df = pd.DataFrame({"x": range(100)})
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result = tool.run(view, {"test_size": 0.6, "val_size": 0.5})
        assert result.valid is False
        assert "must be < 1.0" in result.error

    def test_error_ratios_equal_one(self) -> None:
        df = pd.DataFrame({"x": range(100)})
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result = tool.run(view, {"test_size": 0.5, "val_size": 0.5})
        assert result.valid is False
        assert "must be < 1.0" in result.error

    def test_error_stratify_column_not_found(self) -> None:
        df = pd.DataFrame({"x": range(20)})
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result = tool.run(view, {"test_size": 0.2, "stratify_column": "nonexistent"})
        assert result.valid is False
        assert "nonexistent" in result.error

    def test_indices_disjoint(self) -> None:
        df = pd.DataFrame({"x": range(100)})
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result = tool.run(view, {"test_size": 0.2, "val_size": 0.1})
        assert result.valid is True
        train_set = set(result.outputs["train_indices"])
        val_set = set(result.outputs["val_indices"])
        test_set = set(result.outputs["test_indices"])
        assert train_set & val_set == set()
        assert train_set & test_set == set()
        assert val_set & test_set == set()

    def test_all_indices_covered(self) -> None:
        df = pd.DataFrame({"x": range(50)})
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result = tool.run(view, {"test_size": 0.2, "val_size": 0.1})
        assert result.valid is True
        all_indices = sorted(
            result.outputs["train_indices"]
            + result.outputs["val_indices"]
            + result.outputs["test_indices"]
        )
        assert all_indices == list(range(50))

    def test_metrics_match_actual_fractions(self) -> None:
        df = pd.DataFrame({"x": range(100)})
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result = tool.run(view, {"test_size": 0.2, "val_size": 0.1})
        assert result.valid is True
        assert result.metrics["train_fraction"] == 0.7
        assert result.metrics["val_fraction"] == 0.1
        assert result.metrics["test_fraction"] == 0.2

    def test_result_type(self) -> None:
        df = pd.DataFrame({"x": range(20), "y": range(20)})
        view = _make_view(df)
        tool = TrainValTestSplitTool()
        result = tool.run(view, {"test_size": 0.2})
        assert isinstance(result, ToolResult)


class TestTrainValTestSplitFactory:
    def test_get_tool_returns_instance(self) -> None:
        tool = get_tool()
        assert isinstance(tool, TrainValTestSplitTool)

    def test_get_tool_returns_itool(self) -> None:
        tool = get_tool()
        assert isinstance(tool, ITool)
