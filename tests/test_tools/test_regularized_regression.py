"""Tests for RegularizedRegressionMethod."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ToolResult
from urika.tools.regularized_regression import RegularizedRegressionMethod, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestRegularizedRegressionMethod:
    def test_name(self) -> None:
        method = RegularizedRegressionMethod()
        assert method.name() == "regularized_regression"

    def test_description(self) -> None:
        method = RegularizedRegressionMethod()
        assert isinstance(method.description(), str)
        assert len(method.description()) > 0

    def test_category(self) -> None:
        method = RegularizedRegressionMethod()
        assert method.category() == "regression"

    def test_default_params(self) -> None:
        method = RegularizedRegressionMethod()
        params = method.default_params()
        assert "target" in params
        assert "features" in params
        assert params["features"] is None
        assert params["method"] == "lasso"
        assert params["cv_folds"] == 5
        assert params["l1_ratio"] == 0.5

    def test_lasso_selects_features(self) -> None:
        """Lasso should drop irrelevant features (zero coefficients)."""
        rng = np.random.default_rng(42)
        n = 100
        x_signal = rng.standard_normal(n)
        y = 3.0 * x_signal + rng.standard_normal(n) * 0.1
        df = pd.DataFrame(
            {
                "x_signal": x_signal,
                "noise_1": rng.standard_normal(n),
                "noise_2": rng.standard_normal(n),
                "noise_3": rng.standard_normal(n),
                "y": y,
            }
        )
        view = _make_view(df)
        method = RegularizedRegressionMethod()
        result = method.run(view, {"target": "y", "method": "lasso"})
        assert result.valid is True
        assert "selected_features" in result.outputs
        selected = result.outputs["selected_features"]
        # Lasso should select the signal feature and drop at least some noise
        assert "x_signal" in selected
        assert len(selected) < 4  # should drop at least one noise feature
        assert result.metrics["n_features_selected"] == len(selected)
        assert result.metrics["best_alpha"] > 0

    def test_ridge_keeps_all_features(self) -> None:
        """Ridge should not zero out any coefficients."""
        rng = np.random.default_rng(42)
        n = 100
        df = pd.DataFrame(
            {
                "a": rng.standard_normal(n),
                "b": rng.standard_normal(n),
                "c": rng.standard_normal(n),
                "y": rng.standard_normal(n),
            }
        )
        view = _make_view(df)
        method = RegularizedRegressionMethod()
        result = method.run(view, {"target": "y", "method": "ridge"})
        assert result.valid is True
        selected = result.outputs["selected_features"]
        assert len(selected) == 3  # all features kept
        assert result.metrics["n_features_selected"] == 3

    def test_elasticnet(self) -> None:
        """ElasticNet should run and return valid metrics."""
        rng = np.random.default_rng(42)
        n = 100
        x = rng.standard_normal(n)
        y = 2.0 * x + rng.standard_normal(n) * 0.5
        df = pd.DataFrame(
            {
                "x": x,
                "noise": rng.standard_normal(n),
                "y": y,
            }
        )
        view = _make_view(df)
        method = RegularizedRegressionMethod()
        result = method.run(
            view, {"target": "y", "method": "elasticnet", "l1_ratio": 0.5}
        )
        assert result.valid is True
        assert "r2" in result.metrics
        assert "rmse" in result.metrics
        assert "mae" in result.metrics
        assert "best_alpha" in result.metrics
        assert "n_features_selected" in result.metrics
        assert result.metrics["r2"] > 0.5

    def test_with_train_test_split(self) -> None:
        """Providing train/test indices should work and report test-set metrics."""
        rng = np.random.default_rng(42)
        n = 50
        x = rng.standard_normal(n)
        y = 2.0 * x + rng.standard_normal(n) * 0.1
        df = pd.DataFrame({"x": x, "y": y})
        view = _make_view(df)
        method = RegularizedRegressionMethod()
        train_idx = list(range(0, 40))
        test_idx = list(range(40, 50))
        result = method.run(
            view,
            {
                "target": "y",
                "features": ["x"],
                "method": "lasso",
                "train_indices": train_idx,
                "test_indices": test_idx,
            },
        )
        assert result.valid is True
        assert "held-out" in result.outputs["note"]
        assert result.metrics["r2"] > 0.8

    def test_missing_target(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        method = RegularizedRegressionMethod()
        result = method.run(view, {"target": "nonexistent"})
        assert result.valid is False
        assert "nonexistent" in result.error

    def test_no_features(self) -> None:
        df = pd.DataFrame({"y": [1.0, 2.0, 3.0], "label": ["a", "b", "c"]})
        view = _make_view(df)
        method = RegularizedRegressionMethod()
        result = method.run(view, {"target": "y"})
        assert result.valid is False
        assert "No feature columns" in result.error

    def test_result_type(self) -> None:
        rng = np.random.default_rng(42)
        n = 50
        df = pd.DataFrame(
            {"x": rng.standard_normal(n), "y": rng.standard_normal(n)}
        )
        view = _make_view(df)
        method = RegularizedRegressionMethod()
        result = method.run(view, {"target": "y", "features": ["x"]})
        assert isinstance(result, ToolResult)


class TestRegularizedRegressionFactory:
    def test_get_tool_returns_instance(self) -> None:
        method = get_tool()
        assert isinstance(method, RegularizedRegressionMethod)
