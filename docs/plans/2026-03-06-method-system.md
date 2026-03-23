# Method System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the method infrastructure — IAnalysisMethod ABC, MethodResult dataclass, and MethodRegistry with dual discovery (builtins + project directory).

**Architecture:** `IAnalysisMethod` defines the interface all analysis methods implement. `MethodRegistry` discovers methods from two sources: built-in package modules (via `pkgutil`) and project-specific methods on disk (via `importlib.util`). This follows the same auto-discovery pattern as `MetricRegistry`, `AgentRegistry`, and `ReaderRegistry`.

**Tech Stack:** Python dataclasses, ABC, pkgutil, importlib.util, pytest.

**Design doc:** `docs/plans/2026-03-06-method-system-design.md`

---

### Task 1: Create methods package skeleton

**Files:**
- Create: `src/urika/methods/__init__.py`

**Step 1: Create empty package file**

Create `src/urika/methods/__init__.py` — empty file.

**Step 2: Verify**

Run: `python -c "import urika.methods; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add src/urika/methods/__init__.py
git commit -m "feat(methods): add methods package skeleton"
```

---

### Task 2: MethodResult dataclass and IAnalysisMethod ABC

**Files:**
- Create: `src/urika/methods/base.py`
- Create: `tests/test_methods/__init__.py`
- Create: `tests/test_methods/test_base.py`

**Step 1: Write the failing tests**

Create `tests/test_methods/__init__.py` — empty file.

Create `tests/test_methods/test_base.py`:

```python
"""Tests for IAnalysisMethod ABC and MethodResult."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from urika.data.models import DatasetSpec, DataSummary, DatasetView
from urika.methods.base import IAnalysisMethod, MethodResult


class DummyMethod(IAnalysisMethod):
    """Concrete method for testing."""

    def name(self) -> str:
        return "dummy"

    def description(self) -> str:
        return "A dummy method for testing"

    def category(self) -> str:
        return "test"

    def default_params(self) -> dict[str, Any]:
        return {"alpha": 0.1}

    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult:
        return MethodResult(
            metrics={"r2": 0.85, "rmse": 0.12},
            artifacts=["output.csv"],
        )


class TestMethodResult:
    """Test MethodResult dataclass."""

    def test_create_with_required_fields(self) -> None:
        result = MethodResult(metrics={"r2": 0.9}, artifacts=[])
        assert result.metrics == {"r2": 0.9}
        assert result.artifacts == []
        assert result.valid is True
        assert result.error is None

    def test_create_with_failure(self) -> None:
        result = MethodResult(
            metrics={},
            artifacts=[],
            valid=False,
            error="Division by zero",
        )
        assert result.valid is False
        assert result.error == "Division by zero"

    def test_create_with_artifacts(self) -> None:
        result = MethodResult(
            metrics={"f1": 0.88},
            artifacts=["plot.png", "predictions.csv"],
        )
        assert len(result.artifacts) == 2


class TestIAnalysisMethod:
    """Test IAnalysisMethod ABC."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            IAnalysisMethod()  # type: ignore[abstract]

    def test_concrete_implementation_metadata(self) -> None:
        method = DummyMethod()
        assert method.name() == "dummy"
        assert method.description() == "A dummy method for testing"
        assert method.category() == "test"

    def test_default_params(self) -> None:
        method = DummyMethod()
        params = method.default_params()
        assert params == {"alpha": 0.1}

    def test_run_returns_method_result(self) -> None:
        method = DummyMethod()
        data = DatasetView(
            spec=DatasetSpec(path=Path("/tmp/test.csv"), format="csv"),
            data=pd.DataFrame({"x": [1, 2, 3]}),
            summary=DataSummary(
                n_rows=3,
                n_columns=1,
                columns=["x"],
                dtypes={"x": "int64"},
                missing_counts={"x": 0},
                numeric_stats={"x": {"mean": 2.0, "std": 1.0, "min": 1.0, "max": 3.0, "median": 2.0}},
            ),
        )
        result = method.run(data, {"alpha": 0.1})
        assert isinstance(result, MethodResult)
        assert result.metrics["r2"] == 0.85
        assert result.valid is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_methods/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'urika.methods.base'`

**Step 3: Write minimal implementation**

Create `src/urika/methods/base.py`:

```python
"""Base method interface and result type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from urika.data.models import DatasetView


@dataclass
class MethodResult:
    """What a method run produced."""

    metrics: dict[str, float]
    artifacts: list[str] = field(default_factory=list)
    valid: bool = True
    error: str | None = None


class IAnalysisMethod(ABC):
    """Interface for all analysis methods."""

    @abstractmethod
    def name(self) -> str:
        """Return the unique name of this method."""
        ...

    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description."""
        ...

    @abstractmethod
    def category(self) -> str:
        """Return the method category (e.g. 'regression', 'classification')."""
        ...

    @abstractmethod
    def default_params(self) -> dict[str, Any]:
        """Return default parameters for this method."""
        ...

    @abstractmethod
    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult:
        """Run the method on data with given parameters."""
        ...
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_methods/test_base.py -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
git add src/urika/methods/base.py tests/test_methods/__init__.py tests/test_methods/test_base.py
git commit -m "feat(methods): add IAnalysisMethod ABC and MethodResult"
```

---

### Task 3: MethodRegistry with builtin discovery

**Files:**
- Create: `src/urika/methods/registry.py`
- Create: `tests/test_methods/test_registry.py`

**Step 1: Write the failing tests**

Create `tests/test_methods/test_registry.py`:

```python
"""Tests for MethodRegistry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from urika.data.models import DatasetSpec, DataSummary, DatasetView
from urika.methods.base import IAnalysisMethod, MethodResult
from urika.methods.registry import MethodRegistry


class FakeMethod(IAnalysisMethod):
    """Concrete method for testing."""

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
    """Test the MethodRegistry."""

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
        """discover() should work even with no built-in method modules."""
        registry = MethodRegistry()
        registry.discover()
        # No built-in methods in this phase, so list should be empty
        assert isinstance(registry.list_all(), list)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_methods/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'urika.methods.registry'`

**Step 3: Write minimal implementation**

Create `src/urika/methods/registry.py`:

```python
"""Method registry with auto-discovery."""

from __future__ import annotations

import importlib
import pkgutil

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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_methods/test_registry.py -v`
Expected: 8 PASSED

**Step 5: Commit**

```bash
git add src/urika/methods/registry.py tests/test_methods/test_registry.py
git commit -m "feat(methods): add MethodRegistry with builtin discovery"
```

---

### Task 4: Project directory discovery (discover_project)

**Files:**
- Modify: `src/urika/methods/registry.py`
- Modify: `tests/test_methods/test_registry.py`

**Step 1: Write the failing tests**

Add to `tests/test_methods/test_registry.py`:

```python
class TestMethodRegistryProjectDiscovery:
    """Test discover_project() for agent-created methods."""

    def test_discover_project_finds_method(self, tmp_path: Path) -> None:
        methods_dir = tmp_path / "methods"
        methods_dir.mkdir()
        (methods_dir / "__init__.py").touch()
        (methods_dir / "my_method.py").write_text(
            '''
from urika.methods.base import IAnalysisMethod, MethodResult

class MyMethod(IAnalysisMethod):
    def name(self): return "my_method"
    def description(self): return "Test method"
    def category(self): return "test"
    def default_params(self): return {}
    def run(self, data, params): return MethodResult(metrics={})

def get_method():
    return MyMethod()
'''
        )

        registry = MethodRegistry()
        registry.discover_project(methods_dir)
        assert "my_method" in registry.list_all()

    def test_discover_project_skips_files_without_get_method(self, tmp_path: Path) -> None:
        methods_dir = tmp_path / "methods"
        methods_dir.mkdir()
        (methods_dir / "__init__.py").touch()
        (methods_dir / "helper.py").write_text("X = 42\n")

        registry = MethodRegistry()
        registry.discover_project(methods_dir)
        assert registry.list_all() == []

    def test_discover_project_nonexistent_dir(self, tmp_path: Path) -> None:
        registry = MethodRegistry()
        registry.discover_project(tmp_path / "nonexistent")
        assert registry.list_all() == []

    def test_discover_project_empty_dir(self, tmp_path: Path) -> None:
        methods_dir = tmp_path / "methods"
        methods_dir.mkdir()

        registry = MethodRegistry()
        registry.discover_project(methods_dir)
        assert registry.list_all() == []

    def test_discover_project_combined_with_builtins(self, tmp_path: Path) -> None:
        methods_dir = tmp_path / "methods"
        methods_dir.mkdir()
        (methods_dir / "__init__.py").touch()
        (methods_dir / "proj_method.py").write_text(
            '''
from urika.methods.base import IAnalysisMethod, MethodResult

class ProjMethod(IAnalysisMethod):
    def name(self): return "proj_method"
    def description(self): return "Project method"
    def category(self): return "test"
    def default_params(self): return {}
    def run(self, data, params): return MethodResult(metrics={})

def get_method():
    return ProjMethod()
'''
        )

        registry = MethodRegistry()
        registry.discover()
        registry.discover_project(methods_dir)
        assert "proj_method" in registry.list_all()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_methods/test_registry.py::TestMethodRegistryProjectDiscovery -v`
Expected: FAIL — `AttributeError: 'MethodRegistry' object has no attribute 'discover_project'`

**Step 3: Add discover_project to MethodRegistry**

Add to `src/urika/methods/registry.py`, add `importlib.util` to imports and add the method:

```python
import importlib.util
```

Add method to `MethodRegistry`:

```python
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
```

Also add `from pathlib import Path` to the imports.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_methods/test_registry.py -v`
Expected: 13 PASSED (8 from Task 3 + 5 new)

**Step 5: Commit**

```bash
git add src/urika/methods/registry.py tests/test_methods/test_registry.py
git commit -m "feat(methods): add project directory discovery (discover_project)"
```

---

### Task 5: Public API exports

**Files:**
- Modify: `src/urika/methods/__init__.py`
- Create: `tests/test_methods/test_public_api.py`

**Step 1: Write the failing tests**

Create `tests/test_methods/test_public_api.py`:

```python
"""Tests for methods package public API."""

from __future__ import annotations


class TestPublicAPI:
    """Test that key types are importable from urika.methods."""

    def test_import_analysis_method(self) -> None:
        from urika.methods import IAnalysisMethod
        assert IAnalysisMethod is not None

    def test_import_method_result(self) -> None:
        from urika.methods import MethodResult
        assert MethodResult is not None

    def test_import_method_registry(self) -> None:
        from urika.methods import MethodRegistry
        assert MethodRegistry is not None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_methods/test_public_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'IAnalysisMethod' from 'urika.methods'`

**Step 3: Write implementation**

Update `src/urika/methods/__init__.py`:

```python
"""Analysis method infrastructure."""

from urika.methods.base import IAnalysisMethod, MethodResult
from urika.methods.registry import MethodRegistry

__all__ = [
    "IAnalysisMethod",
    "MethodRegistry",
    "MethodResult",
]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_methods/test_public_api.py -v`
Expected: 3 PASSED

**Step 5: Run full test suite**

Run: `pytest -v`
Expected: All tests pass (236 existing + ~23 new)

**Step 6: Run linting**

Run: `ruff check src/urika/methods/ tests/test_methods/`
Run: `ruff format --check src/urika/methods/ tests/test_methods/`

Fix any issues if needed.

**Step 7: Commit**

```bash
git add src/urika/methods/__init__.py tests/test_methods/test_public_api.py
git commit -m "feat(methods): add public API exports for methods package"
```
