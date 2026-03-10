"""Tests for DescriptiveStatsMethod."""

from __future__ import annotations

import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.methods.base import MethodResult
from urika.methods.descriptive_stats import DescriptiveStatsMethod, get_method


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestDescriptiveStatsMethod:
    def test_name(self) -> None:
        method = DescriptiveStatsMethod()
        assert method.name() == "descriptive_stats"

    def test_description(self) -> None:
        method = DescriptiveStatsMethod()
        assert isinstance(method.description(), str)
        assert len(method.description()) > 0

    def test_category(self) -> None:
        method = DescriptiveStatsMethod()
        assert method.category() == "statistics"

    def test_default_params(self) -> None:
        method = DescriptiveStatsMethod()
        params = method.default_params()
        assert "columns" in params
        assert params["columns"] is None

    def test_basic_run(self) -> None:
        df = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0, 4.0, 5.0],
                "b": [10.0, 20.0, 30.0, 40.0, 50.0],
            }
        )
        view = _make_view(df)
        method = DescriptiveStatsMethod()
        result = method.run(view, {"columns": None})
        assert result.valid is True
        assert result.metrics["n_rows"] == 5.0
        assert result.metrics["n_columns"] == 2.0
        assert len(result.artifacts) == 2

    def test_specific_columns(self) -> None:
        df = pd.DataFrame(
            {
                "a": [1.0, 2.0, 3.0],
                "b": [4.0, 5.0, 6.0],
                "c": [7.0, 8.0, 9.0],
            }
        )
        view = _make_view(df)
        method = DescriptiveStatsMethod()
        result = method.run(view, {"columns": ["a", "c"]})
        assert result.valid is True
        assert result.metrics["n_columns"] == 2.0

    def test_missing_column_returns_invalid(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        method = DescriptiveStatsMethod()
        result = method.run(view, {"columns": ["nonexistent"]})
        assert result.valid is False
        assert "nonexistent" in result.error

    def test_no_numeric_columns_returns_invalid(self) -> None:
        df = pd.DataFrame({"label": ["a", "b", "c"]})
        view = _make_view(df)
        method = DescriptiveStatsMethod()
        result = method.run(view, {"columns": None})
        assert result.valid is False
        assert "numeric" in result.error.lower()

    def test_insufficient_data_returns_invalid(self) -> None:
        df = pd.DataFrame({"a": [float("nan")], "b": [float("nan")]})
        view = _make_view(df)
        method = DescriptiveStatsMethod()
        result = method.run(view, {"columns": None})
        assert result.valid is False
        assert result.error is not None

    def test_result_type(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]})
        view = _make_view(df)
        method = DescriptiveStatsMethod()
        result = method.run(view, {"columns": None})
        assert isinstance(result, MethodResult)


class TestDescriptiveStatsFactory:
    def test_get_method_returns_instance(self) -> None:
        method = get_method()
        assert isinstance(method, DescriptiveStatsMethod)
