"""Tests for XGBoostRegressionMethod."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ToolResult
from urika.tools.xgboost_regression import XGBoostRegressionMethod, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestXGBoostRegressionMethod:
    def test_name(self) -> None:
        method = XGBoostRegressionMethod()
        assert method.name() == "xgboost_regression"

    def test_description(self) -> None:
        method = XGBoostRegressionMethod()
        assert isinstance(method.description(), str)
        assert len(method.description()) > 0

    def test_category(self) -> None:
        method = XGBoostRegressionMethod()
        assert method.category() == "regression"

    def test_default_params(self) -> None:
        method = XGBoostRegressionMethod()
        params = method.default_params()
        assert params["target"] == ""
        assert params["features"] is None
        assert params["n_estimators"] == 100
        assert params["max_depth"] == 3
        assert params["learning_rate"] == 0.1

    def test_basic_run(self) -> None:
        rng = np.random.default_rng(42)
        x1 = rng.standard_normal(50)
        x2 = rng.standard_normal(50)
        y = 3.0 * x1 + 2.0 * x2 + rng.standard_normal(50) * 0.1
        df = pd.DataFrame({"x1": x1, "x2": x2, "y": y})
        view = _make_view(df)
        method = XGBoostRegressionMethod()
        result = method.run(view, {"target": "y"})
        assert result.valid is True
        assert result.metrics["r2"] > 0.5
        assert "rmse" in result.metrics
        assert "mae" in result.metrics

    def test_respects_hyperparams(self) -> None:
        rng = np.random.default_rng(42)
        df = pd.DataFrame(
            {
                "x": rng.standard_normal(30),
                "y": rng.standard_normal(30),
            }
        )
        view = _make_view(df)
        method = XGBoostRegressionMethod()
        result = method.run(
            view,
            {
                "target": "y",
                "n_estimators": 10,
                "max_depth": 2,
                "learning_rate": 0.05,
            },
        )
        assert result.valid is True

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
        method = XGBoostRegressionMethod()
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
        method = XGBoostRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert result.valid is True

    def test_missing_column_returns_invalid(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        method = XGBoostRegressionMethod()
        result = method.run(view, {"target": "nonexistent"})
        assert result.valid is False
        assert "nonexistent" in result.error

    def test_insufficient_data_returns_invalid(self) -> None:
        df = pd.DataFrame({"x": [1.0], "y": [2.0]})
        view = _make_view(df)
        method = XGBoostRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert result.valid is False
        assert result.error is not None

    def test_result_type(self) -> None:
        rng = np.random.default_rng(42)
        df = pd.DataFrame({"x": rng.standard_normal(10), "y": rng.standard_normal(10)})
        view = _make_view(df)
        method = XGBoostRegressionMethod()
        result = method.run(view, {"target": "y"})
        assert isinstance(result, ToolResult)


class TestXGBoostRegressionFactory:
    def test_get_tool_returns_instance(self) -> None:
        method = get_tool()
        assert isinstance(method, XGBoostRegressionMethod)
