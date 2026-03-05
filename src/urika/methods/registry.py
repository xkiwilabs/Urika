"""Method registry with auto-discovery."""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from pathlib import Path

from urika.methods.base import IAnalysisMethod


class MethodRegistry:
    """Registry for analysis methods with auto-discovery."""

    def __init__(self) -> None:
        self._methods: dict[str, IAnalysisMethod] = {}

    def register(self, method: IAnalysisMethod) -> None:
        """Register a method by its name."""
        self._methods[method.name()] = method

    def get(self, name: str) -> IAnalysisMethod | None:
        """Get a method by name, or None if not found."""
        return self._methods.get(name)

    def list_all(self) -> list[str]:
        """Return a sorted list of all registered method names."""
        return sorted(self._methods.keys())

    def list_by_category(self, category: str) -> list[str]:
        """Return a sorted list of method names in the given category."""
        return sorted(
            name
            for name, method in self._methods.items()
            if method.category() == category
        )

    def discover(self) -> None:
        """Auto-discover built-in methods from methods/ submodules."""
        import urika.methods as methods_pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(methods_pkg.__path__):
            if modname in ("base", "registry"):
                continue
            module = importlib.import_module(f"urika.methods.{modname}")
            get_method = getattr(module, "get_method", None)
            if callable(get_method):
                method = get_method()
                if isinstance(method, IAnalysisMethod):
                    self.register(method)

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
                if isinstance(method, IAnalysisMethod):
                    self.register(method)
