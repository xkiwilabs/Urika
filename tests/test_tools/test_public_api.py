"""Tests for tools package public API."""

from __future__ import annotations


class TestPublicAPI:
    """Test that key types are importable from urika.tools."""

    def test_import_itool(self) -> None:
        from urika.tools import ITool

        assert ITool is not None

    def test_import_tool_result(self) -> None:
        from urika.tools import ToolResult

        assert ToolResult is not None

    def test_import_tool_registry(self) -> None:
        from urika.tools import ToolRegistry

        assert ToolRegistry is not None
