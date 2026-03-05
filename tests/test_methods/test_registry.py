"""Tests for MethodRegistry."""

from __future__ import annotations

from typing import Any

from urika.data.models import DatasetView
from urika.methods.base import IAnalysisMethod, MethodResult
from urika.methods.registry import MethodRegistry


class FakeMethod(IAnalysisMethod):
    def __init__(self, method_name: str = "fake", cat: str = "test") -> None:
        self._name = method_name
        self._cat = cat

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return f"Fake method: {self._name}"

    def category(self) -> str:
        return self._cat

    def default_params(self) -> dict[str, Any]:
        return {}

    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult:
        return MethodResult(metrics={})


class TestMethodRegistry:
    def test_register_and_get(self) -> None:
        registry = MethodRegistry()
        method = FakeMethod()
        registry.register(method)
        assert registry.get("fake") is method

    def test_get_nonexistent_returns_none(self) -> None:
        registry = MethodRegistry()
        assert registry.get("nonexistent") is None

    def test_list_all_sorted(self) -> None:
        registry = MethodRegistry()
        registry.register(FakeMethod("beta"))
        registry.register(FakeMethod("alpha"))
        assert registry.list_all() == ["alpha", "beta"]

    def test_list_all_empty(self) -> None:
        registry = MethodRegistry()
        assert registry.list_all() == []

    def test_list_by_category(self) -> None:
        registry = MethodRegistry()
        registry.register(FakeMethod("lr", "regression"))
        registry.register(FakeMethod("rf", "classification"))
        registry.register(FakeMethod("xgb", "regression"))
        assert registry.list_by_category("regression") == ["lr", "xgb"]
        assert registry.list_by_category("classification") == ["rf"]

    def test_list_by_category_empty(self) -> None:
        registry = MethodRegistry()
        assert registry.list_by_category("regression") == []

    def test_register_overwrites_same_name(self) -> None:
        registry = MethodRegistry()
        method1 = FakeMethod("same")
        method2 = FakeMethod("same")
        registry.register(method1)
        registry.register(method2)
        assert registry.get("same") is method2

    def test_discover_finds_nothing_when_no_builtins(self) -> None:
        registry = MethodRegistry()
        registry.discover()
        assert isinstance(registry.list_all(), list)
