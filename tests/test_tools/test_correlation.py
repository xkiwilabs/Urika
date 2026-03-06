"""Tests for CorrelationAnalysisTool."""

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


class TestCorrelationAnalysisTool:
    def test_name(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        tool = CorrelationAnalysisTool()
        assert tool.name() == "correlation_analysis"

    def test_description(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        tool = CorrelationAnalysisTool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        tool = CorrelationAnalysisTool()
        assert tool.category() == "exploration"

    def test_default_params(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        tool = CorrelationAnalysisTool()
        params = tool.default_params()
        assert params == {"method": "pearson"}

    def test_perfect_positive_correlation(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        df["y"] = 2.0 * df["x"]
        view = _make_view(df)
        tool = CorrelationAnalysisTool()
        result = tool.run(view, {"method": "pearson"})
        assert result.valid is True
        assert result.outputs["correlation_matrix"]["x"]["y"] == 1.0
        assert result.outputs["correlation_matrix"]["y"]["x"] == 1.0

    def test_perfect_negative_correlation(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        df = pd.DataFrame(
            {"x": [1.0, 2.0, 3.0, 4.0, 5.0], "y": [5.0, 4.0, 3.0, 2.0, 1.0]}
        )
        view = _make_view(df)
        tool = CorrelationAnalysisTool()
        result = tool.run(view, {"method": "pearson"})
        assert result.valid is True
        assert result.outputs["correlation_matrix"]["x"]["y"] == -1.0

    def test_top_correlations_sorted(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        df = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0, 4.0, 5.0],
                "b": [2.0, 4.0, 6.0, 8.0, 10.0],  # perfect with a
                "c": [5.0, 4.0, 3.0, 2.0, 1.0],  # perfect negative with a
                "d": [1.0, 3.0, 2.0, 5.0, 4.0],  # weak correlation
            }
        )
        view = _make_view(df)
        tool = CorrelationAnalysisTool()
        result = tool.run(view, {"method": "pearson"})
        top = result.outputs["top_correlations"]
        # Should be sorted by absolute correlation descending
        abs_values = [abs(entry["correlation"]) for entry in top]
        assert abs_values == sorted(abs_values, reverse=True)

    def test_top_correlations_exclude_self(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 6.0]})
        view = _make_view(df)
        tool = CorrelationAnalysisTool()
        result = tool.run(view, {"method": "pearson"})
        top = result.outputs["top_correlations"]
        for entry in top:
            assert entry["column_a"] != entry["column_b"]

    def test_spearman_method(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        df["y"] = 2.0 * df["x"]
        view = _make_view(df)
        tool = CorrelationAnalysisTool()
        result = tool.run(view, {"method": "spearman"})
        assert result.valid is True
        assert result.outputs["correlation_matrix"]["x"]["y"] == 1.0

    def test_kendall_method(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        df["y"] = 2.0 * df["x"]
        view = _make_view(df)
        tool = CorrelationAnalysisTool()
        result = tool.run(view, {"method": "kendall"})
        assert result.valid is True
        assert abs(result.outputs["correlation_matrix"]["x"]["y"] - 1.0) < 1e-10

    def test_ignores_non_numeric_columns(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        df = pd.DataFrame(
            {
                "x": [1.0, 2.0, 3.0],
                "y": [4.0, 5.0, 6.0],
                "label": ["a", "b", "c"],
            }
        )
        view = _make_view(df)
        tool = CorrelationAnalysisTool()
        result = tool.run(view, {"method": "pearson"})
        assert result.valid is True
        assert "label" not in result.outputs["correlation_matrix"]

    def test_no_numeric_columns_returns_invalid(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        df = pd.DataFrame({"name": ["Alice", "Bob"], "city": ["London", "Paris"]})
        view = _make_view(df)
        tool = CorrelationAnalysisTool()
        result = tool.run(view, {"method": "pearson"})
        assert result.valid is False
        assert result.error is not None

    def test_result_type(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 6.0]})
        view = _make_view(df)
        tool = CorrelationAnalysisTool()
        result = tool.run(view, {"method": "pearson"})
        assert isinstance(result, ToolResult)


class TestCorrelationAnalysisFactory:
    def test_get_tool_returns_instance(self) -> None:
        from urika.tools.correlation import CorrelationAnalysisTool, get_tool

        tool = get_tool()
        assert isinstance(tool, CorrelationAnalysisTool)
