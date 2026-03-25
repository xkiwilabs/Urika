"""Tests for ToolRegistry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult
from urika.tools.registry import ToolRegistry


class FakeTool(ITool):
    def __init__(self, tool_name: str = "fake", cat: str = "test") -> None:
        self._name = tool_name
        self._cat = cat

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return f"Fake tool: {self._name}"

    def category(self) -> str:
        return self._cat

    def default_params(self) -> dict[str, Any]:
        return {}

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        return ToolResult(outputs={})


class TestToolRegistry:
    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        tool = FakeTool()
        registry.register(tool)
        assert registry.get("fake") is tool

    def test_get_nonexistent_returns_none(self) -> None:
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_list_all_sorted(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeTool("beta"))
        registry.register(FakeTool("alpha"))
        assert registry.list_all() == ["alpha", "beta"]

    def test_list_all_empty(self) -> None:
        registry = ToolRegistry()
        assert registry.list_all() == []

    def test_list_by_category(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeTool("profiler", "exploration"))
        registry.register(FakeTool("ttest", "statistical"))
        registry.register(FakeTool("corr", "exploration"))
        assert registry.list_by_category("exploration") == ["corr", "profiler"]
        assert registry.list_by_category("statistical") == ["ttest"]

    def test_list_by_category_empty(self) -> None:
        registry = ToolRegistry()
        assert registry.list_by_category("exploration") == []

    def test_register_overwrites_same_name(self) -> None:
        registry = ToolRegistry()
        tool1 = FakeTool("same")
        tool2 = FakeTool("same")
        registry.register(tool1)
        registry.register(tool2)
        assert registry.get("same") is tool2

    def test_discover_finds_builtin_tools(self) -> None:
        registry = ToolRegistry()
        registry.discover()
        names = registry.list_all()
        assert len(names) == 18
        expected = [
            "correlation_analysis",
            "cross_validation",
            "data_profiler",
            "descriptive_stats",
            "feature_scaler",
            "gradient_boosting",
            "group_split",
            "hypothesis_tests",
            "linear_regression",
            "logistic_regression",
            "mann_whitney_u",
            "one_way_anova",
            "outlier_detection",
            "paired_t_test",
            "random_forest",
            "random_forest_classifier",
            "train_val_test_split",
            "visualization",
        ]
        assert names == expected


class TestToolRegistryProjectDiscovery:
    """Test discover_project() for agent-created tools."""

    def test_discover_project_finds_tool(self, tmp_path: Path) -> None:
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "__init__.py").touch()
        (tools_dir / "my_tool.py").write_text(
            """
from urika.tools.base import ITool, ToolResult

class MyTool(ITool):
    def name(self): return "my_tool"
    def description(self): return "Test tool"
    def category(self): return "test"
    def default_params(self): return {}
    def run(self, data, params): return ToolResult(outputs={})

def get_tool():
    return MyTool()
"""
        )

        registry = ToolRegistry()
        registry.discover_project(tools_dir)
        assert "my_tool" in registry.list_all()

    def test_discover_project_skips_files_without_get_tool(
        self, tmp_path: Path
    ) -> None:
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "__init__.py").touch()
        (tools_dir / "helper.py").write_text("X = 42\n")

        registry = ToolRegistry()
        registry.discover_project(tools_dir)
        assert registry.list_all() == []

    def test_discover_project_nonexistent_dir(self, tmp_path: Path) -> None:
        registry = ToolRegistry()
        registry.discover_project(tmp_path / "nonexistent")
        assert registry.list_all() == []

    def test_discover_project_empty_dir(self, tmp_path: Path) -> None:
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        registry = ToolRegistry()
        registry.discover_project(tools_dir)
        assert registry.list_all() == []

    def test_discover_project_combined_with_builtins(self, tmp_path: Path) -> None:
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "__init__.py").touch()
        (tools_dir / "proj_tool.py").write_text(
            """
from urika.tools.base import ITool, ToolResult

class ProjTool(ITool):
    def name(self): return "proj_tool"
    def description(self): return "Project tool"
    def category(self): return "test"
    def default_params(self): return {}
    def run(self, data, params): return ToolResult(outputs={})

def get_tool():
    return ProjTool()
"""
        )

        registry = ToolRegistry()
        registry.discover()
        registry.discover_project(tools_dir)
        assert "proj_tool" in registry.list_all()
