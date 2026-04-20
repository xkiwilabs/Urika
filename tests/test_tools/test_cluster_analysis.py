"""Tests for ClusterAnalysisTool."""

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


class TestClusterAnalysisTool:
    def test_name(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        tool = ClusterAnalysisTool()
        assert tool.name() == "cluster_analysis"

    def test_description(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        tool = ClusterAnalysisTool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        tool = ClusterAnalysisTool()
        assert tool.category() == "exploration"

    def test_default_params(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        tool = ClusterAnalysisTool()
        params = tool.default_params()
        assert params == {
            "features": None,
            "method": "kmeans",
            "n_clusters": None,
            "standardize": True,
            "random_state": 42,
        }

    def test_kmeans_known_clusters(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        rng = np.random.RandomState(0)
        # Three well-separated clusters
        c1 = rng.randn(30, 2) + [0, 0]
        c2 = rng.randn(30, 2) + [10, 10]
        c3 = rng.randn(30, 2) + [20, 0]
        data = np.vstack([c1, c2, c3])
        df = pd.DataFrame(data, columns=["x", "y"])
        view = _make_view(df)

        tool = ClusterAnalysisTool()
        result = tool.run(view, {"method": "kmeans", "n_clusters": 3})

        assert result.valid is True
        assert result.metrics["n_clusters"] == 3.0
        assert result.metrics["silhouette_score"] > 0.5
        assert "inertia" in result.metrics
        assert "cluster_sizes" in result.outputs
        assert sum(result.outputs["cluster_sizes"].values()) == 90

    def test_agglomerative(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        rng = np.random.RandomState(1)
        c1 = rng.randn(20, 2) + [0, 0]
        c2 = rng.randn(20, 2) + [10, 10]
        data = np.vstack([c1, c2])
        df = pd.DataFrame(data, columns=["x", "y"])
        view = _make_view(df)

        tool = ClusterAnalysisTool()
        result = tool.run(view, {"method": "agglomerative", "n_clusters": 2})

        assert result.valid is True
        assert result.metrics["n_clusters"] == 2.0
        assert result.metrics["silhouette_score"] > 0.5
        # Agglomerative should not have inertia
        assert "inertia" not in result.metrics
        assert "cluster_sizes" in result.outputs

    def test_auto_k(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        rng = np.random.RandomState(2)
        c1 = rng.randn(30, 2) + [0, 0]
        c2 = rng.randn(30, 2) + [10, 10]
        c3 = rng.randn(30, 2) + [20, 0]
        data = np.vstack([c1, c2, c3])
        df = pd.DataFrame(data, columns=["x", "y"])
        view = _make_view(df)

        tool = ClusterAnalysisTool()
        result = tool.run(view, {"method": "kmeans", "n_clusters": None})

        assert result.valid is True
        assert "silhouette_scores" in result.outputs
        scores = result.outputs["silhouette_scores"]
        # Should have tried k=2 through k=9 (min(10, 90-1)=10, range 2..10)
        assert 2 in scores
        assert 3 in scores
        assert result.metrics["silhouette_score"] > 0.0
        # With well-separated clusters, auto-select should find k=3
        assert result.metrics["n_clusters"] == 3.0

    def test_standardize(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        rng = np.random.RandomState(3)
        c1 = rng.randn(20, 2) + [0, 0]
        c2 = rng.randn(20, 2) + [10, 10]
        data = np.vstack([c1, c2])
        df = pd.DataFrame(data, columns=["x", "y"])
        view = _make_view(df)

        tool = ClusterAnalysisTool()

        result_std = tool.run(
            view, {"method": "kmeans", "n_clusters": 2, "standardize": True}
        )
        result_no_std = tool.run(
            view, {"method": "kmeans", "n_clusters": 2, "standardize": False}
        )

        assert result_std.valid is True
        assert result_no_std.valid is True
        # Both should produce valid silhouette scores
        assert result_std.metrics["silhouette_score"] > 0.0
        assert result_no_std.metrics["silhouette_score"] > 0.0

    def test_no_features(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        df = pd.DataFrame({"name": ["Alice", "Bob", "Carol"], "city": ["A", "B", "C"]})
        view = _make_view(df)

        tool = ClusterAnalysisTool()
        result = tool.run(view, {})

        assert result.valid is False
        assert "No numeric features" in result.error

    def test_insufficient_data(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        df = pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]})
        view = _make_view(df)

        tool = ClusterAnalysisTool()
        # Ask for 3 clusters with only 2 data points
        result = tool.run(view, {"method": "kmeans", "n_clusters": 3})

        assert result.valid is False
        assert "n_clusters" in result.error or "Insufficient" in result.error

    def test_identical_rows(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        df = pd.DataFrame({"x": [5.0, 5.0, 5.0, 5.0], "y": [3.0, 3.0, 3.0, 3.0]})
        view = _make_view(df)

        tool = ClusterAnalysisTool()
        result = tool.run(view, {"method": "kmeans", "n_clusters": 2})

        assert result.valid is False
        assert "identical" in result.error.lower()

    def test_result_type(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool

        rng = np.random.RandomState(4)
        c1 = rng.randn(15, 2) + [0, 0]
        c2 = rng.randn(15, 2) + [10, 10]
        data = np.vstack([c1, c2])
        df = pd.DataFrame(data, columns=["x", "y"])
        view = _make_view(df)

        tool = ClusterAnalysisTool()
        result = tool.run(view, {"method": "kmeans", "n_clusters": 2})
        assert isinstance(result, ToolResult)


class TestClusterAnalysisFactory:
    def test_get_tool_returns_instance(self) -> None:
        from urika.tools.cluster_analysis import ClusterAnalysisTool, get_tool

        tool = get_tool()
        assert isinstance(tool, ClusterAnalysisTool)
