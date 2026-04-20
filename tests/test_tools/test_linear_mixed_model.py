"""Tests for LinearMixedModelMethod."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ToolResult
from urika.tools.linear_mixed_model import LinearMixedModelMethod, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


def _make_lmm_data(n_subjects: int = 10, n_obs: int = 5, seed: int = 42) -> pd.DataFrame:
    """Create synthetic repeated-measures data with known group structure."""
    rng = np.random.default_rng(seed)
    rows = []
    for subj in range(n_subjects):
        intercept = rng.normal(0, 1)
        for _ in range(n_obs):
            x = rng.normal(0, 1)
            y = 2.0 + intercept + 1.5 * x + rng.normal(0, 0.3)
            rows.append({"subject": f"s{subj}", "x": x, "y": y})
    return pd.DataFrame(rows)


class TestLinearMixedModelMethod:
    def test_name(self) -> None:
        tool = LinearMixedModelMethod()
        assert tool.name() == "linear_mixed_model"

    def test_description(self) -> None:
        tool = LinearMixedModelMethod()
        desc = tool.description()
        assert isinstance(desc, str)
        assert len(desc) > 0
        assert "mixed" in desc.lower()

    def test_category(self) -> None:
        tool = LinearMixedModelMethod()
        assert tool.category() == "regression"

    def test_default_params(self) -> None:
        tool = LinearMixedModelMethod()
        params = tool.default_params()
        assert "target" in params
        assert "features" in params
        assert "groups" in params
        assert "random_effects" in params
        assert "formula" in params
        assert params["features"] is None

    def test_basic_random_intercept(self) -> None:
        df = _make_lmm_data()
        view = _make_view(df)
        tool = LinearMixedModelMethod()
        result = tool.run(view, {"target": "y", "features": ["x"], "groups": "subject"})
        assert result.valid is True
        assert "aic" in result.metrics
        assert "bic" in result.metrics
        assert "log_likelihood" in result.metrics
        assert "converged" in result.metrics
        assert "fixed_effects" in result.outputs
        assert "random_effects_variance" in result.outputs
        assert "formula_used" in result.outputs

    def test_formula_mode(self) -> None:
        df = _make_lmm_data()
        view = _make_view(df)
        tool = LinearMixedModelMethod()
        result = tool.run(
            view,
            {"formula": "y ~ x", "groups": "subject"},
        )
        assert result.valid is True
        assert "aic" in result.metrics
        assert "fixed_effects" in result.outputs

    def test_missing_target(self) -> None:
        df = _make_lmm_data()
        view = _make_view(df)
        tool = LinearMixedModelMethod()
        result = tool.run(
            view,
            {"target": "nonexistent", "features": ["x"], "groups": "subject"},
        )
        assert result.valid is False
        assert result.error is not None
        assert "nonexistent" in result.error

    def test_missing_group_column(self) -> None:
        df = _make_lmm_data()
        view = _make_view(df)
        tool = LinearMixedModelMethod()
        result = tool.run(
            view,
            {"target": "y", "features": ["x"], "groups": "bad_group"},
        )
        assert result.valid is False
        assert result.error is not None
        assert "bad_group" in result.error

    def test_insufficient_groups(self) -> None:
        df = _make_lmm_data(n_subjects=1, n_obs=10)
        view = _make_view(df)
        tool = LinearMixedModelMethod()
        result = tool.run(
            view,
            {"target": "y", "features": ["x"], "groups": "subject"},
        )
        assert result.valid is False
        assert result.error is not None
        assert "group" in result.error.lower()

    def test_result_type(self) -> None:
        df = _make_lmm_data()
        view = _make_view(df)
        tool = LinearMixedModelMethod()
        result = tool.run(view, {"target": "y", "features": ["x"], "groups": "subject"})
        assert isinstance(result, ToolResult)

    def test_get_tool_returns_instance(self) -> None:
        tool = get_tool()
        assert isinstance(tool, LinearMixedModelMethod)
