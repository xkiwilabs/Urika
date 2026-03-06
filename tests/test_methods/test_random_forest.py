"""Tests for RandomForestMethod."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.methods.base import MethodResult
from urika.methods.random_forest import RandomForestMethod, get_method


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestRandomForestMethod:
    def test_name(self) -> None:
        method = RandomForestMethod()
        assert method.name() == "random_forest"

    def test_description(self) -> None:
        method = RandomForestMethod()
        assert isinstance(method.description(), str)
        assert len(method.description()) > 0

    def test_category(self) -> None:
        method = RandomForestMethod()
        assert method.category() == "regression"

    def test_default_params(self) -> None:
        method = RandomForestMethod()
        params = method.default_params()
        assert params["target"] == ""
        assert params["features"] is None
        assert params["n_estimators"] == 100
        assert params["max_depth"] is None
        assert params["random_state"] == 42

    def test_basic_fit(self) -> None:
        rng = np.random.default_rng(42)
        x1 = rng.standard_normal(50)
        x2 = rng.standard_normal(50)
        y = 3.0 * x1 + 2.0 * x2 + rng.standard_normal(50) * 0.1
        df = pd.DataFrame({"x1": x1, "x2": x2, "y": y})
        view = _make_view(df)
        method = RandomForestMethod()
        result = method.run(view, {"target": "y", "random_state": 42})
        assert result.valid is True
        assert result.metrics["r2"] > 0.5

    def test_respects_n_estimators(self) -> None:
        rng = np.random.default_rng(0)
        df = pd.DataFrame(
            {
                "x": rng.standard_normal(30),
                "y": rng.standard_normal(30),
            }
        )
        view = _make_view(df)
        method = RandomForestMethod()
        result5 = method.run(
            view, {"target": "y", "n_estimators": 5, "random_state": 0}
        )
        result200 = method.run(
            view, {"target": "y", "n_estimators": 200, "random_state": 0}
        )
        assert result5.valid is True
        assert result200.valid is True

    def test_respects_random_state(self) -> None:
        rng = np.random.default_rng(7)
        df = pd.DataFrame(
            {
                "x": rng.standard_normal(30),
                "y": rng.standard_normal(30),
            }
        )
        view = _make_view(df)
        method = RandomForestMethod()
        r1 = method.run(view, {"target": "y", "random_state": 99})
        r2 = method.run(view, {"target": "y", "random_state": 99})
        assert r1.metrics["r2"] == r2.metrics["r2"]
        assert r1.metrics["rmse"] == r2.metrics["rmse"]

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
        method = RandomForestMethod()
        result = method.run(view, {"target": "y", "random_state": 42})
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
        method = RandomForestMethod()
        result = method.run(
            view, {"target": "y", "features": ["x"], "random_state": 42}
        )
        assert result.valid is True

    def test_all_nan_returns_invalid(self) -> None:
        df = pd.DataFrame(
            {
                "x": [float("nan")] * 5,
                "y": [float("nan")] * 5,
            }
        )
        view = _make_view(df)
        method = RandomForestMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert result.valid is False
        assert result.error is not None

    def test_insufficient_data_returns_invalid(self) -> None:
        df = pd.DataFrame({"x": [1.0], "y": [2.0]})
        view = _make_view(df)
        method = RandomForestMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert result.valid is False
        assert result.error is not None

    def test_missing_target_returns_invalid(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        method = RandomForestMethod()
        result = method.run(view, {"target": "nonexistent"})
        assert result.valid is False
        assert "nonexistent" in result.error

    def test_result_type(self) -> None:
        rng = np.random.default_rng(42)
        df = pd.DataFrame({"x": rng.standard_normal(10), "y": rng.standard_normal(10)})
        view = _make_view(df)
        method = RandomForestMethod()
        result = method.run(view, {"target": "y", "random_state": 42})
        assert isinstance(result, MethodResult)


class TestRandomForestFactory:
    def test_get_method_returns_instance(self) -> None:
        method = get_method()
        assert isinstance(method, RandomForestMethod)
