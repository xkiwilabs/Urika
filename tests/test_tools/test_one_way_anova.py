"""Tests for OneWayAnovaMethod."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ToolResult
from urika.tools.one_way_anova import OneWayAnovaMethod, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestOneWayAnovaMethod:
    def test_name(self) -> None:
        method = OneWayAnovaMethod()
        assert method.name() == "one_way_anova"

    def test_description(self) -> None:
        method = OneWayAnovaMethod()
        assert isinstance(method.description(), str)
        assert len(method.description()) > 0

    def test_category(self) -> None:
        method = OneWayAnovaMethod()
        assert method.category() == "statistical_test"

    def test_default_params(self) -> None:
        method = OneWayAnovaMethod()
        params = method.default_params()
        assert "group_column" in params
        assert "value_column" in params

    def test_basic_run(self) -> None:
        rng = np.random.default_rng(42)
        df = pd.DataFrame(
            {
                "group": ["A"] * 20 + ["B"] * 20 + ["C"] * 20,
                "value": np.concatenate(
                    [
                        rng.normal(0, 1, 20),
                        rng.normal(5, 1, 20),
                        rng.normal(10, 1, 20),
                    ]
                ),
            }
        )
        view = _make_view(df)
        method = OneWayAnovaMethod()
        result = method.run(view, {"group_column": "group", "value_column": "value"})
        assert result.valid is True
        assert result.metrics["f_statistic"] > 0
        assert result.metrics["p_value"] < 0.05

    def test_no_difference_high_p_value(self) -> None:
        rng = np.random.default_rng(42)
        values = rng.standard_normal(60)
        df = pd.DataFrame(
            {
                "group": ["A"] * 20 + ["B"] * 20 + ["C"] * 20,
                "value": values,
            }
        )
        view = _make_view(df)
        method = OneWayAnovaMethod()
        result = method.run(view, {"group_column": "group", "value_column": "value"})
        assert result.valid is True
        assert result.metrics["p_value"] > 0.01

    def test_missing_column_returns_invalid(self) -> None:
        df = pd.DataFrame({"group": ["A", "B"], "value": [1.0, 2.0]})
        view = _make_view(df)
        method = OneWayAnovaMethod()
        result = method.run(
            view, {"group_column": "nonexistent", "value_column": "value"}
        )
        assert result.valid is False
        assert "nonexistent" in result.error

    def test_single_group_returns_invalid(self) -> None:
        df = pd.DataFrame(
            {
                "group": ["A", "A", "A"],
                "value": [1.0, 2.0, 3.0],
            }
        )
        view = _make_view(df)
        method = OneWayAnovaMethod()
        result = method.run(view, {"group_column": "group", "value_column": "value"})
        assert result.valid is False
        assert "2 groups" in result.error

    def test_insufficient_data_returns_invalid(self) -> None:
        df = pd.DataFrame(
            {
                "group": ["A", "B"],
                "value": [1.0, 2.0],
            }
        )
        view = _make_view(df)
        method = OneWayAnovaMethod()
        result = method.run(view, {"group_column": "group", "value_column": "value"})
        assert result.valid is False
        assert "fewer than 2" in result.error

    def test_result_type(self) -> None:
        df = pd.DataFrame(
            {
                "group": ["A"] * 5 + ["B"] * 5,
                "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
            }
        )
        view = _make_view(df)
        method = OneWayAnovaMethod()
        result = method.run(view, {"group_column": "group", "value_column": "value"})
        assert isinstance(result, ToolResult)


class TestOneWayAnovaFactory:
    def test_get_tool_returns_instance(self) -> None:
        method = get_tool()
        assert isinstance(method, OneWayAnovaMethod)
