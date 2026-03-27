"""Tool registry with auto-discovery."""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from pathlib import Path

from urika.tools.base import ITool


class ToolRegistry:
    """Registry for analysis tools with auto-discovery."""

    def __init__(self) -> None:
        self._tools: dict[str, ITool] = {}

    def register(self, tool: ITool) -> None:
        """Register a tool by its name."""
        self._tools[tool.name()] = tool

    def get(self, name: str) -> ITool | None:
        """Get a tool by name, or None if not found."""
        return self._tools.get(name)

    def list_all(self) -> list[str]:
        """Return a sorted list of all registered tool names."""
        return sorted(self._tools.keys())

    def list_by_category(self, category: str) -> list[str]:
        """Return a sorted list of tool names in the given category."""
        return sorted(
            name for name, tool in self._tools.items() if tool.category() == category
        )

    def discover(self) -> None:
        """Auto-discover built-in tools from tools/ submodules."""
        import urika.tools as tools_pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(tools_pkg.__path__):
            if modname in ("base", "registry"):
                continue
            module = importlib.import_module(f"urika.tools.{modname}")
            get_tool = getattr(module, "get_tool", None)
            if callable(get_tool):
                tool = get_tool()
                if isinstance(tool, ITool):
                    self.register(tool)

    def discover_project(self, tools_dir: Path) -> None:
        """Discover agent-created tools from a project's tools/ directory."""
        if not tools_dir.is_dir():
            return

        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = py_file.stem
            spec = importlib.util.spec_from_file_location(
                f"urika_project_tools.{module_name}", py_file
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception:
                continue
            get_tool = getattr(module, "get_tool", None)
            if callable(get_tool):
                tool = get_tool()
                if isinstance(tool, ITool):
                    self.register(tool)
