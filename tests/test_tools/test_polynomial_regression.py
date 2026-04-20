"""Tests for PolynomialRegressionMethod."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ToolResult
from urika.tools.polynomial_regression import PolynomialRegressionMethod, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestPolynomialRegressionMethod:
    def test_name(self) -> None:
        method = PolynomialRegressionMethod()
        assert method.name() == "polynomial_regression"

    def test_description(self) -> None:
        method = PolynomialRegressionMethod()
        assert isinstance(method.description(), str)
        assert len(method.description()) > 0

    def test_category(self) -> None:
        method = PolynomialRegressionMethod()
        assert method.category() == "regression"

    def test_default_params(self) -> None:
        method = PolynomialRegressionMethod()
        params = method.default_params()
        assert "target" in params
        assert "features" in params
        assert params["features"] is None
        assert params["degree"] == 2
        assert params["interaction_only"] is False
        assert params["include_bias"] is False

    def test_quadratic_fit(self) -> None:
        """y = x^2 should be perfectly captured by degree-2 polynomial."""
        x = np.linspace(-5, 5, 50)
        df = pd.DataFrame({"x": x, "y": x**2})
        view = _make_view(df)
        method = PolynomialRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"], "degree": 2})
        assert result.valid is True
        assert result.metrics["r2"] >= 0.999
        assert result.metrics["rmse"] < 1e-6
        assert "feature_names" in result.outputs
        assert result.metrics["n_features_original"] == 1.0
        assert result.metrics["n_features_expanded"] >= 2.0

    def test_interaction_only(self) -> None:
        """interaction_only=True should produce fewer features than full polynomial."""
        rng = np.random.default_rng(42)
        df = pd.DataFrame(
            {
                "a": rng.standard_normal(100),
                "b": rng.standard_normal(100),
                "c": rng.standard_normal(100),
                "y": rng.standard_normal(100),
            }
        )
        view = _make_view(df)
        method = PolynomialRegressionMethod()

        result_full = method.run(
            view,
            {"target": "y", "features": ["a", "b", "c"], "degree": 2, "interaction_only": False},
        )
        result_interact = method.run(
            view,
            {"target": "y", "features": ["a", "b", "c"], "degree": 2, "interaction_only": True},
        )

        assert result_full.valid is True
        assert result_interact.valid is True
        assert (
            result_interact.metrics["n_features_expanded"]
            < result_full.metrics["n_features_expanded"]
        )

    def test_with_train_test(self) -> None:
        """Providing train/test indices should produce held-out metrics."""
        x = np.linspace(0, 10, 30)
        df = pd.DataFrame({"x": x, "y": 0.5 * x**2 + 3 * x + 1})
        view = _make_view(df)
        method = PolynomialRegressionMethod()

        train_idx = list(range(0, 20))
        test_idx = list(range(20, 30))

        result = method.run(
            view,
            {
                "target": "y",
                "features": ["x"],
                "degree": 2,
                "train_indices": train_idx,
                "test_indices": test_idx,
            },
        )
        assert result.valid is True
        assert result.metrics["r2"] >= 0.999
        assert "held-out" in result.outputs["note"]

    def test_missing_target(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        method = PolynomialRegressionMethod()
        result = method.run(view, {"target": "nonexistent"})
        assert result.valid is False
        assert "nonexistent" in result.error

    def test_no_features(self) -> None:
        df = pd.DataFrame({"y": [1.0, 2.0, 3.0], "label": ["a", "b", "c"]})
        view = _make_view(df)
        method = PolynomialRegressionMethod()
        result = method.run(view, {"target": "y"})
        assert result.valid is False
        assert "No feature columns" in result.error

    def test_result_type(self) -> None:
        x = np.linspace(0, 5, 20)
        df = pd.DataFrame({"x": x, "y": x**2})
        view = _make_view(df)
        method = PolynomialRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert isinstance(result, ToolResult)

    def test_get_tool_returns_instance(self) -> None:
        method = get_tool()
        assert isinstance(method, PolynomialRegressionMethod)
