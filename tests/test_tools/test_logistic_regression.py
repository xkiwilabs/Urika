"""Tests for LogisticRegressionMethod."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ToolResult
from urika.tools.logistic_regression import LogisticRegressionMethod, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestLogisticRegressionMethod:
    def test_name(self) -> None:
        method = LogisticRegressionMethod()
        assert method.name() == "logistic_regression"

    def test_description(self) -> None:
        method = LogisticRegressionMethod()
        assert isinstance(method.description(), str)
        assert len(method.description()) > 0

    def test_category(self) -> None:
        method = LogisticRegressionMethod()
        assert method.category() == "classification"

    def test_default_params(self) -> None:
        method = LogisticRegressionMethod()
        params = method.default_params()
        assert "target" in params
        assert "features" in params
        assert params["features"] is None

    def test_basic_run(self) -> None:
        rng = np.random.default_rng(42)
        x1 = rng.standard_normal(100)
        x2 = rng.standard_normal(100)
        y = (x1 + x2 > 0).astype(int)
        df = pd.DataFrame({"x1": x1, "x2": x2, "y": y})
        view = _make_view(df)
        method = LogisticRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x1", "x2"]})
        assert result.valid is True
        assert result.metrics["accuracy"] > 0.5
        assert 0.0 <= result.metrics["f1"] <= 1.0

    def test_features_defaults_to_all_numeric_except_target(self) -> None:
        rng = np.random.default_rng(42)
        x = rng.standard_normal(50)
        y = (x > 0).astype(int)
        df = pd.DataFrame({"x": x, "y": y})
        view = _make_view(df)
        method = LogisticRegressionMethod()
        result = method.run(view, {"target": "y"})
        assert result.valid is True
        assert "accuracy" in result.metrics

    def test_multiclass(self) -> None:
        rng = np.random.default_rng(42)
        x = rng.standard_normal(90)
        y = np.repeat([0, 1, 2], 30)
        df = pd.DataFrame({"x": x, "y": y})
        view = _make_view(df)
        method = LogisticRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert result.valid is True
        assert "accuracy" in result.metrics
        assert "f1" in result.metrics

    def test_missing_column_returns_invalid(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        method = LogisticRegressionMethod()
        result = method.run(view, {"target": "nonexistent"})
        assert result.valid is False
        assert "nonexistent" in result.error

    def test_insufficient_data_returns_invalid(self) -> None:
        df = pd.DataFrame({"x": [1.0], "y": [0]})
        view = _make_view(df)
        method = LogisticRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert result.valid is False
        assert result.error is not None

    def test_single_class_returns_invalid(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [0, 0, 0]})
        view = _make_view(df)
        method = LogisticRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert result.valid is False
        assert "2 classes" in result.error

    def test_result_type(self) -> None:
        rng = np.random.default_rng(42)
        x = rng.standard_normal(20)
        y = (x > 0).astype(int)
        df = pd.DataFrame({"x": x, "y": y})
        view = _make_view(df)
        method = LogisticRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert isinstance(result, ToolResult)


class TestLogisticRegressionFactory:
    def test_get_tool_returns_instance(self) -> None:
        method = get_tool()
        assert isinstance(method, LogisticRegressionMethod)
