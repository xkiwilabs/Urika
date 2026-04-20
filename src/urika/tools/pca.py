"""PCA / dimensionality reduction tool using scikit-learn."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class PCATool(ITool):
    """PCA with automatic component selection and variance analysis."""

    def name(self) -> str:
        return "pca"

    def description(self) -> str:
        return (
            "Principal Component Analysis with automatic component selection "
            "and variance analysis."
        )

    def category(self) -> str:
        return "dimensionality_reduction"

    def default_params(self) -> dict[str, Any]:
        return {
            "features": None,
            "n_components": 0.95,
            "standardize": True,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        features = params.get("features", None)
        n_components = params.get("n_components", 0.95)
        standardize = params.get("standardize", True)

        df = data.data
        numeric_df = df.select_dtypes(include="number")

        # Select requested features (must be numeric)
        if features is not None:
            available = [c for c in features if c in numeric_df.columns]
            if not available:
                return ToolResult(
                    outputs={},
                    metrics={},
                    valid=False,
                    error="None of the specified features are numeric columns",
                )
            numeric_df = numeric_df[available]
        else:
            if numeric_df.shape[1] == 0:
                return ToolResult(
                    outputs={},
                    metrics={},
                    valid=False,
                    error="No numeric columns in dataset",
                )

        # Drop rows with NaN
        clean = numeric_df.dropna()
        if len(clean) < 2:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error="Insufficient data rows after dropping NaN values (need at least 2)",
            )

        feature_names = list(clean.columns)
        n_original = len(feature_names)
        X = clean.values

        # Standardize if requested
        if standardize:
            X = StandardScaler().fit_transform(X)

        # Validate n_components
        max_components = min(X.shape[0], X.shape[1])
        if isinstance(n_components, float):
            if not (0.0 < n_components <= 1.0):
                return ToolResult(
                    outputs={},
                    metrics={},
                    valid=False,
                    error=f"Float n_components must be in (0, 1], got {n_components}",
                )
        elif isinstance(n_components, int):
            if n_components < 1 or n_components > max_components:
                return ToolResult(
                    outputs={},
                    metrics={},
                    valid=False,
                    error=(
                        f"Integer n_components must be between 1 and {max_components}, "
                        f"got {n_components}"
                    ),
                )
        else:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"n_components must be int or float, got {type(n_components).__name__}",
            )

        # Fit PCA
        pca = PCA(n_components=n_components)
        pca.fit(X)

        n_selected = pca.n_components_
        explained = pca.explained_variance_ratio_
        cumulative = np.cumsum(explained).tolist()

        # Build loadings: component name → {feature: loading_value}
        loadings: dict[str, dict[str, float]] = {}
        for i in range(n_selected):
            comp_name = f"PC{i + 1}"
            loadings[comp_name] = {
                feat: float(pca.components_[i, j])
                for j, feat in enumerate(feature_names)
            }

        note = (
            f"Reduced {n_original} features to {n_selected} components "
            f"explaining {cumulative[-1]:.1%} of variance."
        )

        return ToolResult(
            outputs={
                "explained_variance_ratio": [float(v) for v in explained],
                "cumulative_variance": cumulative,
                "loadings": loadings,
                "note": note,
            },
            metrics={
                "n_components_selected": float(n_selected),
                "total_variance_explained": float(cumulative[-1]),
                "n_original_features": float(n_original),
            },
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return PCATool()
