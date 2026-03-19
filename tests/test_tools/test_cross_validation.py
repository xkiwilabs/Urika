"""Tests for CrossValidationTool."""

from __future__ import annotations

import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ITool, ToolResult
from urika.tools.cross_validation import CrossValidationTool, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestCrossValidationTool:
    def test_name(self) -> None:
        tool = CrossValidationTool()
        assert tool.name() == "cross_validation"

    def test_description(self) -> None:
        tool = CrossValidationTool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        tool = CrossValidationTool()
        assert tool.category() == "preprocessing"

    def test_default_params(self) -> None:
        tool = CrossValidationTool()
        params = tool.default_params()
        assert params["n_folds"] == 5
        assert params["random_state"] == 42
        assert params["shuffle"] is True
        assert params["stratify_column"] is None

    def test_default_5_fold_split(self) -> None:
        df = pd.DataFrame({"x": range(100), "y": range(100)})
        view = _make_view(df)
        tool = CrossValidationTool()
        result = tool.run(view, tool.default_params())
        assert result.valid is True
        assert result.outputs["n_folds"] == 5
        assert len(result.outputs["folds"]) == 5

    def test_10_fold_split(self) -> None:
        df = pd.DataFrame({"x": range(100), "y": range(100)})
        view = _make_view(df)
        tool = CrossValidationTool()
        result = tool.run(view, {"n_folds": 10})
        assert result.valid is True
        assert result.outputs["n_folds"] == 10
        assert len(result.outputs["folds"]) == 10

    def test_stratified_split(self) -> None:
        df = pd.DataFrame(
            {
                "x": range(100),
                "label": [0] * 50 + [1] * 50,
            }
        )
        view = _make_view(df)
        tool = CrossValidationTool()
        result = tool.run(view, {"n_folds": 5, "stratify_column": "label"})
        assert result.valid is True
        assert len(result.outputs["folds"]) == 5

    def test_no_shuffle(self) -> None:
        df = pd.DataFrame({"x": range(20)})
        view = _make_view(df)
        tool = CrossValidationTool()
        result = tool.run(view, {"n_folds": 4, "shuffle": False})
        assert result.valid is True
        # First fold test indices should be the first chunk when not shuffled
        first_test = result.outputs["folds"][0]["test_indices"]
        assert first_test == list(range(5))

    def test_custom_random_state(self) -> None:
        df = pd.DataFrame({"x": range(20)})
        view = _make_view(df)
        tool = CrossValidationTool()
        result_a = tool.run(view, {"n_folds": 5, "random_state": 0})
        result_b = tool.run(view, {"n_folds": 5, "random_state": 99})
        # Different seeds should produce different splits
        folds_a = result_a.outputs["folds"][0]["test_indices"]
        folds_b = result_b.outputs["folds"][0]["test_indices"]
        assert folds_a != folds_b

    def test_error_n_folds_less_than_2(self) -> None:
        df = pd.DataFrame({"x": range(10)})
        view = _make_view(df)
        tool = CrossValidationTool()
        result = tool.run(view, {"n_folds": 1})
        assert result.valid is False
        assert "n_folds must be at least 2" in result.error

    def test_error_n_folds_exceeds_samples(self) -> None:
        df = pd.DataFrame({"x": range(3)})
        view = _make_view(df)
        tool = CrossValidationTool()
        result = tool.run(view, {"n_folds": 5})
        assert result.valid is False
        assert "cannot exceed" in result.error

    def test_error_stratify_column_not_found(self) -> None:
        df = pd.DataFrame({"x": range(10)})
        view = _make_view(df)
        tool = CrossValidationTool()
        result = tool.run(view, {"n_folds": 2, "stratify_column": "missing"})
        assert result.valid is False
        assert "missing" in result.error

    def test_all_samples_covered(self) -> None:
        n = 50
        df = pd.DataFrame({"x": range(n)})
        view = _make_view(df)
        tool = CrossValidationTool()
        result = tool.run(view, {"n_folds": 5})
        all_test_indices: set[int] = set()
        for fold in result.outputs["folds"]:
            all_test_indices.update(fold["test_indices"])
        assert all_test_indices == set(range(n))

    def test_no_overlap_train_test_within_fold(self) -> None:
        df = pd.DataFrame({"x": range(30)})
        view = _make_view(df)
        tool = CrossValidationTool()
        result = tool.run(view, {"n_folds": 3})
        for fold in result.outputs["folds"]:
            train = set(fold["train_indices"])
            test = set(fold["test_indices"])
            assert train.isdisjoint(test)

    def test_metrics_correctness(self) -> None:
        df = pd.DataFrame({"x": range(100)})
        view = _make_view(df)
        tool = CrossValidationTool()
        result = tool.run(view, {"n_folds": 5})
        assert result.metrics["n_folds"] == 5.0
        assert result.metrics["avg_test_size"] == 20.0

    def test_result_type(self) -> None:
        df = pd.DataFrame({"x": range(10)})
        view = _make_view(df)
        tool = CrossValidationTool()
        result = tool.run(view, {"n_folds": 2})
        assert isinstance(result, ToolResult)


class TestCrossValidationFactory:
    def test_get_tool_returns_instance(self) -> None:
        tool = get_tool()
        assert isinstance(tool, CrossValidationTool)
        assert isinstance(tool, ITool)
