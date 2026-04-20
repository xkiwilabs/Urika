"""Cluster analysis tool using KMeans and Agglomerative clustering."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class ClusterAnalysisTool(ITool):
    """KMeans and Agglomerative clustering with silhouette scoring."""

    def name(self) -> str:
        return "cluster_analysis"

    def description(self) -> str:
        return (
            "KMeans and Agglomerative clustering with silhouette scoring. "
            "Supports automatic selection of optimal cluster count."
        )

    def category(self) -> str:
        return "exploration"

    def default_params(self) -> dict[str, Any]:
        return {
            "features": None,
            "method": "kmeans",
            "n_clusters": None,
            "standardize": True,
            "random_state": 42,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        features = params.get("features", None)
        method = params.get("method", "kmeans")
        n_clusters = params.get("n_clusters", None)
        standardize = params.get("standardize", True)
        random_state = params.get("random_state", 42)
        df = data.data

        if method not in ("kmeans", "agglomerative"):
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Unsupported method: {method!r}. Must be 'kmeans' or 'agglomerative'.",
            )

        numeric_df = df.select_dtypes(include="number")

        if features is not None:
            feature_cols = [c for c in features if c in numeric_df.columns]
        else:
            feature_cols = list(numeric_df.columns)

        if not feature_cols:
            return ToolResult(
                outputs={},
                valid=False,
                error="No numeric features available for clustering.",
            )

        X = numeric_df[feature_cols].dropna().values

        if len(X) < 2:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Insufficient data: {len(X)} rows after dropping NaN.",
            )

        # Check for only 1 unique row
        if len(np.unique(X, axis=0)) < 2:
            return ToolResult(
                outputs={},
                valid=False,
                error="All rows are identical; clustering is not meaningful.",
            )

        if standardize:
            X = StandardScaler().fit_transform(X)

        if n_clusters is not None:
            if n_clusters < 2:
                return ToolResult(
                    outputs={},
                    valid=False,
                    error="n_clusters must be at least 2.",
                )
            if n_clusters >= len(X):
                return ToolResult(
                    outputs={},
                    valid=False,
                    error=f"n_clusters ({n_clusters}) must be less than number of samples ({len(X)}).",
                )
            return self._fit(X, method, n_clusters, random_state)

        # Auto-select k: try 2..min(10, n_samples-1)
        max_k = min(10, len(X) - 1)
        if max_k < 2:
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Insufficient data for auto-selection: need at least 3 samples, got {len(X)}.",
            )

        silhouette_scores: dict[int, float] = {}
        best_k = 2
        best_score = -1.0

        for k in range(2, max_k + 1):
            labels = self._cluster(X, method, k, random_state)
            score = float(silhouette_score(X, labels))
            silhouette_scores[k] = score
            if score > best_score:
                best_score = score
                best_k = k

        result = self._fit(X, method, best_k, random_state)
        result.outputs["silhouette_scores"] = silhouette_scores
        result.outputs["note"] = (
            f"Auto-selected k={best_k} from range [2, {max_k}] "
            f"with best silhouette score {best_score:.4f}."
        )
        return result

    def _cluster(
        self, X: np.ndarray, method: str, n_clusters: int, random_state: int
    ) -> np.ndarray:
        """Fit a clustering model and return labels."""
        if method == "kmeans":
            model = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
        else:
            model = AgglomerativeClustering(n_clusters=n_clusters)
        return model.fit_predict(X)

    def _fit(
        self, X: np.ndarray, method: str, n_clusters: int, random_state: int
    ) -> ToolResult:
        """Fit clustering and build a ToolResult."""
        if method == "kmeans":
            model = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
            labels = model.fit_predict(X)
            sil = float(silhouette_score(X, labels))
            inertia = float(model.inertia_)

            unique, counts = np.unique(labels, return_counts=True)
            cluster_sizes = {int(k): int(v) for k, v in zip(unique, counts)}

            return ToolResult(
                outputs={
                    "cluster_sizes": cluster_sizes,
                    "note": f"KMeans clustering with k={n_clusters}.",
                },
                metrics={
                    "silhouette_score": sil,
                    "n_clusters": float(n_clusters),
                    "inertia": inertia,
                },
            )
        else:
            model = AgglomerativeClustering(n_clusters=n_clusters)
            labels = model.fit_predict(X)
            sil = float(silhouette_score(X, labels))

            unique, counts = np.unique(labels, return_counts=True)
            cluster_sizes = {int(k): int(v) for k, v in zip(unique, counts)}

            return ToolResult(
                outputs={
                    "cluster_sizes": cluster_sizes,
                    "note": f"Agglomerative clustering with k={n_clusters}.",
                },
                metrics={
                    "silhouette_score": sil,
                    "n_clusters": float(n_clusters),
                },
            )


def get_tool() -> ITool:
    """Factory function for auto-discovery."""
    return ClusterAnalysisTool()
