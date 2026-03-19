"""Tests for PairedTTestMethod."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ToolResult
from urika.tools.paired_t_test import PairedTTestMethod, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestPairedTTestMethod:
    def test_name(self) -> None:
        method = PairedTTestMethod()
        assert method.name() == "paired_t_test"

    def test_description(self) -> None:
        method = PairedTTestMethod()
        assert isinstance(method.description(), str)
        assert len(method.description()) > 0

    def test_category(self) -> None:
        method = PairedTTestMethod()
        assert method.category() == "statistical_test"

    def test_default_params(self) -> None:
        method = PairedTTestMethod()
        params = method.default_params()
        assert "column_a" in params
        assert "column_b" in params

    def test_identical_columns_not_significant(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        df = pd.DataFrame({"a": values, "b": values})
        view = _make_view(df)
        method = PairedTTestMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert result.valid is True
        # scipy returns NaN for t and p when all differences are zero
        assert np.isnan(result.metrics["t_statistic"])
        assert np.isnan(result.metrics["p_value"])

    def test_different_columns_significant(self) -> None:
        rng = np.random.default_rng(42)
        a = rng.standard_normal(50)
        b = a + 10.0  # large systematic difference
        df = pd.DataFrame({"a": a, "b": b})
        view = _make_view(df)
        method = PairedTTestMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert result.valid is True
        assert result.metrics["p_value"] < 0.05

    def test_drops_nan_rows(self) -> None:
        df = pd.DataFrame(
            {
                "a": [1.0, 2.0, float("nan"), 4.0, 5.0],
                "b": [1.0, 2.0, 3.0, 4.0, 5.0],
            }
        )
        view = _make_view(df)
        method = PairedTTestMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert result.valid is True

    def test_all_nan_returns_invalid(self) -> None:
        df = pd.DataFrame(
            {
                "a": [float("nan")] * 5,
                "b": [float("nan")] * 5,
            }
        )
        view = _make_view(df)
        method = PairedTTestMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert result.valid is False
        assert result.error is not None

    def test_too_few_observations_returns_invalid(self) -> None:
        df = pd.DataFrame({"a": [1.0], "b": [2.0]})
        view = _make_view(df)
        method = PairedTTestMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert result.valid is False
        assert result.error is not None

    def test_missing_column_returns_invalid(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        method = PairedTTestMethod()
        result = method.run(view, {"column_a": "a", "column_b": "missing"})
        assert result.valid is False
        assert "missing" in result.error

    def test_result_type(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [2.0, 3.0, 4.0, 5.0]})
        view = _make_view(df)
        method = PairedTTestMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert isinstance(result, ToolResult)


class TestPairedTTestFactory:
    def test_get_tool_returns_instance(self) -> None:
        method = get_tool()
        assert isinstance(method, PairedTTestMethod)
