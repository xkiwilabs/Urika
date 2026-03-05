"""Tests for ToolRegistry."""

from __future__ import annotations

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

    def test_discover_finds_nothing_when_no_builtins(self) -> None:
        registry = ToolRegistry()
        registry.discover()
        assert isinstance(registry.list_all(), list)
