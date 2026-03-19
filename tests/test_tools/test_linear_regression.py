"""Tests for LinearRegressionMethod."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ToolResult
from urika.tools.linear_regression import LinearRegressionMethod, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestLinearRegressionMethod:
    def test_name(self) -> None:
        method = LinearRegressionMethod()
        assert method.name() == "linear_regression"

    def test_description(self) -> None:
        method = LinearRegressionMethod()
        assert isinstance(method.description(), str)
        assert len(method.description()) > 0

    def test_category(self) -> None:
        method = LinearRegressionMethod()
        assert method.category() == "regression"

    def test_default_params(self) -> None:
        method = LinearRegressionMethod()
        params = method.default_params()
        assert "target" in params
        assert "features" in params
        assert params["features"] is None

    def test_perfect_fit(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        df["y"] = 2.0 * df["x"]
        view = _make_view(df)
        method = LinearRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert result.valid is True
        assert result.metrics["r2"] >= 0.999
        assert result.metrics["rmse"] < 1e-10
        assert result.metrics["mae"] < 1e-10

    def test_features_defaults_to_all_numeric_except_target(self) -> None:
        rng = np.random.default_rng(42)
        df = pd.DataFrame(
            {
                "a": rng.standard_normal(20),
                "b": rng.standard_normal(20),
                "y": rng.standard_normal(20),
            }
        )
        view = _make_view(df)
        method = LinearRegressionMethod()
        result = method.run(view, {"target": "y"})
        assert result.valid is True
        assert "r2" in result.metrics

    def test_drops_nan_rows(self) -> None:
        df = pd.DataFrame(
            {
                "x": [1.0, 2.0, float("nan"), 4.0, 5.0],
                "y": [2.0, 4.0, 6.0, 8.0, 10.0],
            }
        )
        view = _make_view(df)
        method = LinearRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert result.valid is True
        assert "r2" in result.metrics

    def test_all_nan_returns_invalid(self) -> None:
        df = pd.DataFrame(
            {
                "x": [float("nan")] * 5,
                "y": [float("nan")] * 5,
            }
        )
        view = _make_view(df)
        method = LinearRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert result.valid is False
        assert result.error is not None

    def test_insufficient_data_returns_invalid(self) -> None:
        df = pd.DataFrame({"x": [1.0], "y": [2.0]})
        view = _make_view(df)
        method = LinearRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert result.valid is False
        assert result.error is not None

    def test_missing_target_column_returns_invalid(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        method = LinearRegressionMethod()
        result = method.run(view, {"target": "nonexistent"})
        assert result.valid is False
        assert "nonexistent" in result.error

    def test_result_type(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 6.0, 8.0]})
        view = _make_view(df)
        method = LinearRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert isinstance(result, ToolResult)


class TestLinearRegressionFactory:
    def test_get_tool_returns_instance(self) -> None:
        method = get_tool()
        assert isinstance(method, LinearRegressionMethod)
