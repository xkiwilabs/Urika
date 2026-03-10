"""Visualization tool for creating plots from datasets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult


class VisualizationTool(ITool):
    """Create histogram, scatter, and boxplot visualizations."""

    def name(self) -> str:
        return "visualization"

    def description(self) -> str:
        return "Create histogram, scatter, and boxplot visualizations from data."

    def category(self) -> str:
        return "exploration"

    def default_params(self) -> dict[str, Any]:
        return {"plot_type": "histogram", "columns": None, "output_dir": "artifacts"}

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plot_type = params.get("plot_type", "histogram")
        columns = params.get("columns", None)
        output_dir = params.get("output_dir", "artifacts")

        if plot_type not in ("histogram", "scatter", "boxplot"):
            return ToolResult(
                outputs={},
                valid=False,
                error=f"Unsupported plot_type: {plot_type!r}. "
                f"Must be 'histogram', 'scatter', or 'boxplot'.",
            )

        numeric_cols = list(data.data.select_dtypes(include="number").columns)

        if columns is None:
            if not numeric_cols:
                return ToolResult(
                    outputs={},
                    valid=False,
                    error="No numeric columns in dataset",
                )
            columns = [numeric_cols[0]]
        elif isinstance(columns, str):
            columns = [columns]

        # Validate columns exist
        for col in columns:
            if col not in data.data.columns:
                return ToolResult(
                    outputs={},
                    valid=False,
                    error=f"Column {col!r} not found in dataset",
                )

        # Validate numeric for histogram and scatter
        if plot_type in ("histogram", "scatter"):
            for col in columns:
                if col not in numeric_cols:
                    return ToolResult(
                        outputs={},
                        valid=False,
                        error=f"Column {col!r} is not numeric",
                    )

        # Validate scatter requires exactly 2 columns
        if plot_type == "scatter" and len(columns) != 2:
            return ToolResult(
                outputs={},
                valid=False,
                error="Scatter plot requires exactly 2 columns",
            )

        # Create output directory
        out_path = Path(output_dir)
        os.makedirs(out_path, exist_ok=True)

        plot_paths: list[str] = []

        if plot_type == "histogram":
            for col in columns:
                fig, ax = plt.subplots()
                ax.hist(data.data[col].dropna(), bins="auto")
                ax.set_title(f"Histogram of {col}")
                ax.set_xlabel(col)
                ax.set_ylabel("Frequency")
                file_path = str(out_path / f"histogram_{col}.png")
                fig.savefig(file_path)
                plt.close(fig)
                plot_paths.append(file_path)

        elif plot_type == "scatter":
            col_x, col_y = columns[0], columns[1]
            fig, ax = plt.subplots()
            ax.scatter(data.data[col_x], data.data[col_y])
            ax.set_title(f"Scatter: {col_x} vs {col_y}")
            ax.set_xlabel(col_x)
            ax.set_ylabel(col_y)
            file_path = str(out_path / f"scatter_{col_x}_{col_y}.png")
            fig.savefig(file_path)
            plt.close(fig)
            plot_paths.append(file_path)

        elif plot_type == "boxplot":
            for col in columns:
                fig, ax = plt.subplots()
                ax.boxplot(data.data[col].dropna())
                ax.set_title(f"Boxplot of {col}")
                ax.set_ylabel(col)
                file_path = str(out_path / f"boxplot_{col}.png")
                fig.savefig(file_path)
                plt.close(fig)
                plot_paths.append(file_path)

        return ToolResult(
            outputs={"plot_paths": plot_paths},
            artifacts=plot_paths,
        )


def get_tool() -> ITool:
    """Factory function for auto-discovery."""
    return VisualizationTool()
