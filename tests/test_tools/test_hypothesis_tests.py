"""Tests for HypothesisTestsTool."""

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


class TestHypothesisTestsTool:
    def test_name(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        tool = HypothesisTestsTool()
        assert tool.name() == "hypothesis_tests"

    def test_description(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        tool = HypothesisTestsTool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        tool = HypothesisTestsTool()
        assert tool.category() == "statistics"

    def test_default_params(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        tool = HypothesisTestsTool()
        params = tool.default_params()
        assert params == {
            "test_type": "t_test",
            "column_a": None,
            "column_b": None,
            "column": None,
        }

    def test_basic_t_test(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame(
            {
                "group1": [1.0, 2.0, 3.0, 4.0, 5.0],
                "group2": [10.0, 20.0, 30.0, 40.0, 50.0],
            }
        )
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(
            view,
            {"test_type": "t_test", "column_a": "group1", "column_b": "group2"},
        )
        assert result.valid is True
        assert "t_statistic" in result.outputs
        assert "p_value" in result.outputs
        assert "mean_a" in result.outputs
        assert "mean_b" in result.outputs
        assert result.outputs["mean_a"] == 3.0
        assert result.outputs["mean_b"] == 30.0

    def test_t_test_identical_groups(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0, 4.0, 5.0],
                "b": [1.0, 2.0, 3.0, 4.0, 5.0],
            }
        )
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(
            view, {"test_type": "t_test", "column_a": "a", "column_b": "b"}
        )
        assert result.valid is True
        assert result.outputs["t_statistic"] == 0.0
        assert result.outputs["p_value"] == 1.0

    def test_t_test_missing_columns(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(view, {"test_type": "t_test", "column_a": "x"})
        assert result.valid is False
        assert "column_a and column_b" in result.error

    def test_t_test_column_not_found(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(
            view,
            {"test_type": "t_test", "column_a": "x", "column_b": "missing"},
        )
        assert result.valid is False
        assert "not found" in result.error

    def test_t_test_insufficient_data(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame({"a": [1.0], "b": [2.0]})
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(
            view, {"test_type": "t_test", "column_a": "a", "column_b": "b"}
        )
        assert result.valid is False
        assert "at least 2 values" in result.error

    def test_chi_squared(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame(
            {
                "gender": ["M", "M", "F", "F", "M", "F", "M", "F"],
                "preference": ["A", "B", "A", "A", "B", "B", "A", "B"],
            }
        )
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(
            view,
            {
                "test_type": "chi_squared",
                "column_a": "gender",
                "column_b": "preference",
            },
        )
        assert result.valid is True
        assert "chi2" in result.outputs
        assert "p_value" in result.outputs
        assert "dof" in result.outputs
        assert isinstance(result.outputs["dof"], int)

    def test_chi_squared_missing_columns(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame({"x": ["a", "b", "c"]})
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(view, {"test_type": "chi_squared", "column_a": "x"})
        assert result.valid is False
        assert "column_a and column_b" in result.error

    def test_normality(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame({"vals": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]})
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(view, {"test_type": "normality", "column": "vals"})
        assert result.valid is True
        assert "w_statistic" in result.outputs
        assert "p_value" in result.outputs
        assert 0.0 <= result.outputs["w_statistic"] <= 1.0
        assert 0.0 <= result.outputs["p_value"] <= 1.0

    def test_normality_missing_column_param(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(view, {"test_type": "normality"})
        assert result.valid is False
        assert "'column' parameter" in result.error

    def test_normality_column_not_found(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(view, {"test_type": "normality", "column": "missing"})
        assert result.valid is False
        assert "not found" in result.error

    def test_normality_insufficient_data(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame({"x": [1.0, 2.0]})
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(view, {"test_type": "normality", "column": "x"})
        assert result.valid is False
        assert "at least 3 values" in result.error

    def test_unsupported_test_type(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(view, {"test_type": "anova"})
        assert result.valid is False
        assert "Unsupported test_type" in result.error

    def test_result_type(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool

        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [5.0, 6.0, 7.0, 8.0]})
        view = _make_view(df)
        tool = HypothesisTestsTool()
        result = tool.run(
            view, {"test_type": "t_test", "column_a": "a", "column_b": "b"}
        )
        assert isinstance(result, ToolResult)


class TestHypothesisTestsFactory:
    def test_get_tool_returns_instance(self) -> None:
        from urika.tools.hypothesis_tests import HypothesisTestsTool, get_tool

        tool = get_tool()
        assert isinstance(tool, HypothesisTestsTool)
