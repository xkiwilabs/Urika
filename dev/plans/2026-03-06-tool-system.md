# Tool System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the tool infrastructure layer — ITool ABC, ToolResult dataclass, and ToolRegistry with dual discovery (builtins + project directory).

**Architecture:** Mirrors the method system exactly. `ITool` ABC defines the interface, `ToolResult` holds outputs + artifacts, `ToolRegistry` discovers tools from both `src/urika/tools/` (pkgutil) and `project_dir/tools/` (importlib). No built-in tools this phase.

**Tech Stack:** Python stdlib (`abc`, `dataclasses`, `importlib`, `pkgutil`), pytest.

**Reference files:**
- Design: `docs/plans/2026-03-06-tool-system-design.md`
- Pattern to follow: `src/urika/methods/base.py`, `src/urika/methods/registry.py`
- Test pattern: `tests/test_methods/test_base.py`, `tests/test_methods/test_registry.py`

---

### Task 1: Tools package skeleton

**Files:**
- Create: `src/urika/tools/__init__.py`
- Create: `src/urika/tools/base.py`
- Create: `src/urika/tools/registry.py`
- Create: `tests/test_tools/__init__.py`

**Step 1: Create the package skeleton**

Create `src/urika/tools/__init__.py` (empty for now — exports added in Task 5):

```python
```

Create `src/urika/tools/base.py` (empty placeholder):

```python
"""Base tool interface and result type."""
```

Create `src/urika/tools/registry.py` (empty placeholder):

```python
"""Tool registry with auto-discovery."""
```

Create `tests/test_tools/__init__.py` (empty):

```python
```

**Step 2: Verify the package is importable**

Run: `python -c "import urika.tools"`
Expected: No error.

**Step 3: Commit**

```bash
git add src/urika/tools/ tests/test_tools/
git commit -m "feat(tools): add tools package skeleton"
```

---

### Task 2: ToolResult dataclass and ITool ABC

**Files:**
- Modify: `src/urika/tools/base.py`
- Create: `tests/test_tools/test_base.py`

**Step 1: Write the failing tests**

Create `tests/test_tools/test_base.py`:

```python
"""Tests for ITool ABC and ToolResult."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from urika.data.models import DatasetSpec, DataSummary, DatasetView
from urika.tools.base import ITool, ToolResult


class DummyTool(ITool):
    """Concrete tool for testing."""

    def name(self) -> str:
        return "dummy_tool"

    def description(self) -> str:
        return "A dummy tool for testing"

    def category(self) -> str:
        return "exploration"

    def default_params(self) -> dict[str, Any]:
        return {"top_n": 10}

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            outputs={"column_count": 3, "summary": "all good"},
            artifacts=["profile.html"],
        )


class TestToolResult:
    def test_create_with_required_fields(self) -> None:
        result = ToolResult(outputs={"count": 42})
        assert result.outputs == {"count": 42}
        assert result.artifacts == []
        assert result.valid is True
        assert result.error is None

    def test_create_with_failure(self) -> None:
        result = ToolResult(
            outputs={},
            valid=False,
            error="Missing required column",
        )
        assert result.valid is False
        assert result.error == "Missing required column"

    def test_create_with_artifacts(self) -> None:
        result = ToolResult(
            outputs={"stats": {"mean": 1.5}},
            artifacts=["plot.png", "report.csv"],
        )
        assert len(result.artifacts) == 2


class TestITool:
    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            ITool()  # type: ignore[abstract]

    def test_concrete_implementation_metadata(self) -> None:
        tool = DummyTool()
        assert tool.name() == "dummy_tool"
        assert tool.description() == "A dummy tool for testing"
        assert tool.category() == "exploration"

    def test_default_params(self) -> None:
        tool = DummyTool()
        params = tool.default_params()
        assert params == {"top_n": 10}

    def test_run_returns_tool_result(self) -> None:
        tool = DummyTool()
        data = DatasetView(
            spec=DatasetSpec(path=Path("/tmp/test.csv"), format="csv"),
            data=pd.DataFrame({"x": [1, 2, 3]}),
            summary=DataSummary(
                n_rows=3,
                n_columns=1,
                columns=["x"],
                dtypes={"x": "int64"},
                missing_counts={"x": 0},
                numeric_stats={
                    "x": {
                        "mean": 2.0,
                        "std": 1.0,
                        "min": 1.0,
                        "max": 3.0,
                        "median": 2.0,
                    }
                },
            ),
        )
        result = tool.run(data, {"top_n": 10})
        assert isinstance(result, ToolResult)
        assert result.outputs["column_count"] == 3
        assert result.valid is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools/test_base.py -v`
Expected: FAIL — `ImportError: cannot import name 'ITool' from 'urika.tools.base'`

**Step 3: Write minimal implementation**

Update `src/urika/tools/base.py`:

```python
"""Base tool interface and result type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from urika.data.models import DatasetView


@dataclass
class ToolResult:
    """What a tool execution produced."""

    outputs: dict[str, Any]
    artifacts: list[str] = field(default_factory=list)
    valid: bool = True
    error: str | None = None


class ITool(ABC):
    """Interface for all analysis tools."""

    @abstractmethod
    def name(self) -> str:
        """Return the unique name of this tool."""
        ...

    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description."""
        ...

    @abstractmethod
    def category(self) -> str:
        """Return the tool category (e.g. 'exploration', 'statistical')."""
        ...

    @abstractmethod
    def default_params(self) -> dict[str, Any]:
        """Return default parameters for this tool."""
        ...

    @abstractmethod
    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        """Run the tool on data with given parameters."""
        ...
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tools/test_base.py -v`
Expected: 7 PASSED

**Step 5: Commit**

```bash
git add src/urika/tools/base.py tests/test_tools/test_base.py
git commit -m "feat(tools): add ToolResult dataclass and ITool ABC"
```

---

### Task 3: ToolRegistry with auto-discovery

**Files:**
- Modify: `src/urika/tools/registry.py`
- Create: `tests/test_tools/test_registry.py`

**Step 1: Write the failing tests**

Create `tests/test_tools/test_registry.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools/test_registry.py -v`
Expected: FAIL — `ImportError: cannot import name 'ToolRegistry' from 'urika.tools.registry'`

**Step 3: Write minimal implementation**

Update `src/urika/tools/registry.py`:

```python
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
            name
            for name, tool in self._tools.items()
            if tool.category() == category
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tools/test_registry.py -v`
Expected: 8 PASSED

**Step 5: Commit**

```bash
git add src/urika/tools/registry.py tests/test_tools/test_registry.py
git commit -m "feat(tools): add ToolRegistry with auto-discovery"
```

---

### Task 4: Project directory discovery (discover_project)

**Files:**
- Tests already cover `discover_project()` via `test_registry.py` (added in this task)
- No new source files needed — `discover_project()` is already in `registry.py` from Task 3

**Step 1: Add project discovery tests to `tests/test_tools/test_registry.py`**

Append to `tests/test_tools/test_registry.py`:

```python
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
```

Note: You must also add `from pathlib import Path` to the imports at the top of the file.

**Step 2: Run the project discovery tests**

Run: `pytest tests/test_tools/test_registry.py::TestToolRegistryProjectDiscovery -v`
Expected: 5 PASSED

**Step 3: Run all tool tests**

Run: `pytest tests/test_tools/ -v`
Expected: 15 PASSED (7 base + 8 registry)... wait, 8 + 5 = 13 registry. Total: 7 + 13 = 20 PASSED.

**Step 4: Commit**

```bash
git add tests/test_tools/test_registry.py
git commit -m "feat(tools): add project directory discovery (discover_project)"
```

---

### Task 5: Public API exports

**Files:**
- Modify: `src/urika/tools/__init__.py`
- Create: `tests/test_tools/test_public_api.py`

**Step 1: Write the failing tests**

Create `tests/test_tools/test_public_api.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools/test_public_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'ITool' from 'urika.tools'`

**Step 3: Write the exports**

Update `src/urika/tools/__init__.py`:

```python
"""Analysis tool infrastructure."""

from urika.tools.base import ITool, ToolResult
from urika.tools.registry import ToolRegistry

__all__ = ["ITool", "ToolRegistry", "ToolResult"]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tools/test_public_api.py -v`
Expected: 3 PASSED

**Step 5: Run full test suite and lint**

Run: `pytest -v --tb=short`
Expected: All tests pass (259 existing + 23 new = 282 total).

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`
Expected: No errors.

**Step 6: Commit**

```bash
git add src/urika/tools/__init__.py tests/test_tools/test_public_api.py
git commit -m "feat(tools): add public API exports for tools package"
```
