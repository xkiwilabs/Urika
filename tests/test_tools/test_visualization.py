"""Tests for VisualizationTool."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

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


class TestVisualizationTool:
    def test_name(self) -> None:
        from urika.tools.visualization import VisualizationTool

        tool = VisualizationTool()
        assert tool.name() == "visualization"

    def test_description(self) -> None:
        from urika.tools.visualization import VisualizationTool

        tool = VisualizationTool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        from urika.tools.visualization import VisualizationTool

        tool = VisualizationTool()
        assert tool.category() == "exploration"

    def test_default_params(self) -> None:
        from urika.tools.visualization import VisualizationTool

        tool = VisualizationTool()
        params = tool.default_params()
        assert params == {
            "plot_type": "histogram",
            "columns": None,
            "output_dir": "artifacts",
        }

    def test_basic_histogram(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(
            view, {"plot_type": "histogram", "columns": ["x"], "output_dir": out_dir}
        )
        assert result.valid is True
        assert len(result.outputs["plot_paths"]) == 1
        assert Path(result.outputs["plot_paths"][0]).exists()
        assert "histogram_x.png" in result.outputs["plot_paths"][0]

    def test_histogram_default_column(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(view, {"plot_type": "histogram", "output_dir": out_dir})
        assert result.valid is True
        assert len(result.outputs["plot_paths"]) == 1
        assert "histogram_a.png" in result.outputs["plot_paths"][0]

    def test_scatter_plot(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 6.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(
            view,
            {"plot_type": "scatter", "columns": ["x", "y"], "output_dir": out_dir},
        )
        assert result.valid is True
        assert len(result.outputs["plot_paths"]) == 1
        assert Path(result.outputs["plot_paths"][0]).exists()
        assert "scatter_x_y.png" in result.outputs["plot_paths"][0]

    def test_scatter_requires_two_columns(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(
            view, {"plot_type": "scatter", "columns": ["x"], "output_dir": out_dir}
        )
        assert result.valid is False
        assert "exactly 2 columns" in result.error

    def test_boxplot(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"val": [1.0, 2.0, 3.0, 4.0, 5.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(
            view,
            {"plot_type": "boxplot", "columns": ["val"], "output_dir": out_dir},
        )
        assert result.valid is True
        assert len(result.outputs["plot_paths"]) == 1
        assert Path(result.outputs["plot_paths"][0]).exists()
        assert "boxplot_val.png" in result.outputs["plot_paths"][0]

    def test_invalid_plot_type(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(
            view, {"plot_type": "pie", "columns": ["x"], "output_dir": out_dir}
        )
        assert result.valid is False
        assert "Unsupported plot_type" in result.error

    def test_missing_column(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(
            view,
            {"plot_type": "histogram", "columns": ["z"], "output_dir": out_dir},
        )
        assert result.valid is False
        assert "not found" in result.error

    def test_non_numeric_column_histogram(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"label": ["a", "b", "c"], "x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(
            view,
            {"plot_type": "histogram", "columns": ["label"], "output_dir": out_dir},
        )
        assert result.valid is False
        assert "not numeric" in result.error

    def test_no_numeric_columns_default(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"name": ["Alice", "Bob"], "city": ["London", "Paris"]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(view, {"plot_type": "histogram", "output_dir": out_dir})
        assert result.valid is False
        assert "No numeric columns" in result.error

    def test_artifacts_match_plot_paths(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(
            view, {"plot_type": "histogram", "columns": ["x"], "output_dir": out_dir}
        )
        assert result.artifacts == result.outputs["plot_paths"]

    def test_multiple_columns_histogram(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(
            view,
            {
                "plot_type": "histogram",
                "columns": ["a", "b"],
                "output_dir": out_dir,
            },
        )
        assert result.valid is True
        assert len(result.outputs["plot_paths"]) == 2

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "nested" / "dir")
        assert not Path(out_dir).exists()
        result = tool.run(
            view, {"plot_type": "histogram", "columns": ["x"], "output_dir": out_dir}
        )
        assert result.valid is True
        assert Path(out_dir).exists()

    def test_result_type(self, tmp_path: Path) -> None:
        from urika.tools.visualization import VisualizationTool

        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        view = _make_view(df)
        tool = VisualizationTool()
        out_dir = str(tmp_path / "plots")
        result = tool.run(
            view, {"plot_type": "histogram", "columns": ["x"], "output_dir": out_dir}
        )
        assert isinstance(result, ToolResult)


class TestVisualizationFactory:
    def test_get_tool_returns_instance(self) -> None:
        from urika.tools.visualization import VisualizationTool, get_tool

        tool = get_tool()
        assert isinstance(tool, VisualizationTool)
