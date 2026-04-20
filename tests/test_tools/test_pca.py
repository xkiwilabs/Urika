"""Tests for PCATool."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ToolResult


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


class TestPCATool:
    def test_name(self) -> None:
        from urika.tools.pca import PCATool

        tool = PCATool()
        assert tool.name() == "pca"

    def test_description(self) -> None:
        from urika.tools.pca import PCATool

        tool = PCATool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        from urika.tools.pca import PCATool

        tool = PCATool()
        assert tool.category() == "dimensionality_reduction"

    def test_default_params(self) -> None:
        from urika.tools.pca import PCATool

        tool = PCATool()
        params = tool.default_params()
        assert params == {
            "features": None,
            "n_components": 0.95,
            "standardize": True,
        }

    def test_reduces_dimensions(self) -> None:
        from urika.tools.pca import PCATool

        rng = np.random.RandomState(42)
        base = rng.randn(100)
        df = pd.DataFrame(
            {
                "a": base + rng.randn(100) * 0.01,
                "b": base * 2 + rng.randn(100) * 0.01,
                "c": base * -1 + rng.randn(100) * 0.01,
                "d": base * 0.5 + rng.randn(100) * 0.01,
                "e": base * 3 + rng.randn(100) * 0.01,
            }
        )
        view = _make_view(df)
        tool = PCATool()
        result = tool.run(view, {"n_components": 0.95, "standardize": True})

        assert result.valid is True
        # Highly correlated features should reduce to fewer components
        assert result.metrics["n_components_selected"] < 5
        assert result.metrics["total_variance_explained"] >= 0.95

    def test_variance_threshold(self) -> None:
        from urika.tools.pca import PCATool

        rng = np.random.RandomState(42)
        base = rng.randn(100)
        df = pd.DataFrame(
            {
                "a": base + rng.randn(100) * 0.01,
                "b": base * 2 + rng.randn(100) * 0.01,
                "c": rng.randn(100),  # independent noise
                "d": rng.randn(100),  # independent noise
            }
        )
        view = _make_view(df)
        tool = PCATool()
        result = tool.run(view, {"n_components": 0.9, "standardize": True})

        assert result.valid is True
        n_sel = int(result.metrics["n_components_selected"])
        assert result.metrics["total_variance_explained"] >= 0.9
        # Should select fewer than all 4
        assert n_sel < 4

    def test_integer_components(self) -> None:
        from urika.tools.pca import PCATool

        rng = np.random.RandomState(42)
        df = pd.DataFrame(rng.randn(50, 5), columns=["a", "b", "c", "d", "e"])
        view = _make_view(df)
        tool = PCATool()
        result = tool.run(view, {"n_components": 2, "standardize": True})

        assert result.valid is True
        assert result.metrics["n_components_selected"] == 2.0
        assert len(result.outputs["explained_variance_ratio"]) == 2
        assert len(result.outputs["cumulative_variance"]) == 2
        assert len(result.outputs["loadings"]) == 2

    def test_standardize_flag(self) -> None:
        from urika.tools.pca import PCATool

        rng = np.random.RandomState(42)
        # Features with very different scales
        df = pd.DataFrame(
            {
                "small": rng.randn(50) * 0.001,
                "big": rng.randn(50) * 1000,
            }
        )
        view = _make_view(df)
        tool = PCATool()

        result_std = tool.run(view, {"n_components": 2, "standardize": True})
        result_raw = tool.run(view, {"n_components": 2, "standardize": False})

        assert result_std.valid is True
        assert result_raw.valid is True

        # Without standardization, the large-scale feature dominates PC1
        raw_loadings_pc1 = result_raw.outputs["loadings"]["PC1"]
        assert abs(raw_loadings_pc1["big"]) > abs(raw_loadings_pc1["small"])

        # With standardization, loadings should be more balanced
        std_loadings_pc1 = result_std.outputs["loadings"]["PC1"]
        raw_ratio = abs(raw_loadings_pc1["big"]) / max(
            abs(raw_loadings_pc1["small"]), 1e-15
        )
        std_ratio = abs(std_loadings_pc1["big"]) / max(
            abs(std_loadings_pc1["small"]), 1e-15
        )
        assert std_ratio < raw_ratio

    def test_loadings_structure(self) -> None:
        from urika.tools.pca import PCATool

        rng = np.random.RandomState(42)
        df = pd.DataFrame(rng.randn(30, 3), columns=["x", "y", "z"])
        view = _make_view(df)
        tool = PCATool()
        result = tool.run(view, {"n_components": 2, "standardize": True})

        assert result.valid is True
        loadings = result.outputs["loadings"]
        assert "PC1" in loadings
        assert "PC2" in loadings
        # Each component maps every original feature
        for comp_name in ("PC1", "PC2"):
            assert set(loadings[comp_name].keys()) == {"x", "y", "z"}
            for val in loadings[comp_name].values():
                assert isinstance(val, float)

    def test_no_features(self) -> None:
        from urika.tools.pca import PCATool

        df = pd.DataFrame({"name": ["Alice", "Bob", "Carol"], "city": ["A", "B", "C"]})
        view = _make_view(df)
        tool = PCATool()
        result = tool.run(view, {"n_components": 0.95, "standardize": True})

        assert result.valid is False
        assert result.error is not None

    def test_result_type(self) -> None:
        from urika.tools.pca import PCATool

        rng = np.random.RandomState(42)
        df = pd.DataFrame(rng.randn(20, 3), columns=["a", "b", "c"])
        view = _make_view(df)
        tool = PCATool()
        result = tool.run(view, {"n_components": 2, "standardize": True})

        assert isinstance(result, ToolResult)


class TestPCAFactory:
    def test_get_tool_returns_instance(self) -> None:
        from urika.tools.pca import PCATool, get_tool

        tool = get_tool()
        assert isinstance(tool, PCATool)
