"""Method registry — discovers agent-created methods from project directories."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from urika.methods.base import IMethod


class MethodRegistry:
    """Registry for agent-created analysis methods."""

    def __init__(self) -> None:
        self._methods: dict[str, IMethod] = {}

    def register(self, method: IMethod) -> None:
        """Register a method by its name."""
        self._methods[method.name()] = method

    def get(self, name: str) -> IMethod | None:
        """Get a method by name, or None if not found."""
        return self._methods.get(name)

    def list_all(self) -> list[str]:
        """Return a sorted list of all registered method names."""
        return sorted(self._methods.keys())

    def discover_project(self, methods_dir: Path) -> None:
        """Discover agent-created methods from a project's methods/ directory."""
        if not methods_dir.is_dir():
            return

        for py_file in sorted(methods_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = py_file.stem
            spec = importlib.util.spec_from_file_location(
                f"urika_project_methods.{module_name}", py_file
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception:
                continue
            get_method = getattr(module, "get_method", None)
            if callable(get_method):
                method = get_method()
                if isinstance(method, IMethod):
                    self.register(method)
