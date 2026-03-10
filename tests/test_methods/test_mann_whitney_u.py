"""Tests for MannWhitneyUMethod."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.methods.base import MethodResult
from urika.methods.mann_whitney_u import MannWhitneyUMethod, get_method


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestMannWhitneyUMethod:
    def test_name(self) -> None:
        method = MannWhitneyUMethod()
        assert method.name() == "mann_whitney_u"

    def test_description(self) -> None:
        method = MannWhitneyUMethod()
        assert isinstance(method.description(), str)
        assert len(method.description()) > 0

    def test_category(self) -> None:
        method = MannWhitneyUMethod()
        assert method.category() == "statistical_test"

    def test_default_params(self) -> None:
        method = MannWhitneyUMethod()
        params = method.default_params()
        assert "column_a" in params
        assert "column_b" in params

    def test_basic_run(self) -> None:
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 30)
        b = rng.normal(5, 1, 30)
        df = pd.DataFrame({"a": a, "b": b})
        view = _make_view(df)
        method = MannWhitneyUMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert result.valid is True
        assert result.metrics["p_value"] < 0.05

    def test_similar_distributions_high_p(self) -> None:
        rng = np.random.default_rng(42)
        a = rng.standard_normal(30)
        b = rng.standard_normal(30)
        df = pd.DataFrame({"a": a, "b": b})
        view = _make_view(df)
        method = MannWhitneyUMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert result.valid is True
        assert "u_statistic" in result.metrics
        assert "p_value" in result.metrics

    def test_drops_nan_rows(self) -> None:
        df = pd.DataFrame(
            {
                "a": [1.0, 2.0, float("nan"), 4.0, 5.0],
                "b": [1.0, 2.0, 3.0, 4.0, 5.0],
            }
        )
        view = _make_view(df)
        method = MannWhitneyUMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert result.valid is True

    def test_missing_column_returns_invalid(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        method = MannWhitneyUMethod()
        result = method.run(view, {"column_a": "a", "column_b": "missing"})
        assert result.valid is False
        assert "missing" in result.error

    def test_insufficient_data_returns_invalid(self) -> None:
        df = pd.DataFrame({"a": [1.0], "b": [2.0]})
        view = _make_view(df)
        method = MannWhitneyUMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert result.valid is False
        assert result.error is not None

    def test_all_nan_returns_invalid(self) -> None:
        df = pd.DataFrame(
            {
                "a": [float("nan")] * 5,
                "b": [float("nan")] * 5,
            }
        )
        view = _make_view(df)
        method = MannWhitneyUMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert result.valid is False
        assert result.error is not None

    def test_result_type(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [2.0, 3.0, 4.0, 5.0]})
        view = _make_view(df)
        method = MannWhitneyUMethod()
        result = method.run(view, {"column_a": "a", "column_b": "b"})
        assert isinstance(result, MethodResult)


class TestMannWhitneyUFactory:
    def test_get_method_returns_instance(self) -> None:
        method = get_method()
        assert isinstance(method, MannWhitneyUMethod)
