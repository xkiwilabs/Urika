# Tool System Design

**Date**: 2026-03-06
**Status**: Approved
**Context**: Phase 6 of Urika — tool infrastructure for analysis utilities.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Phase scope | Infrastructure only — no built-in tools | Prove the pattern. Agents create tools as Python files. |
| Interface style | Same as methods: `run(data, params) -> ToolResult` | Consistent with IAnalysisMethod. Uniform pattern across the codebase. |
| Result type | `outputs: dict[str, Any]` + `artifacts: list[str]` | Tools produce diverse structured data (tables, stats), not just numeric metrics. |
| Categories | Yes — `category()` method on ITool | Enables `list_by_category()`. Agents discover tools by type. |
| Discovery | Package builtins + project `tools/` dir | ToolRegistry discovers from both `src/urika/tools/` (shipped) and `project_dir/tools/` (agent-created). |

---

## 2. Module Structure

```
src/urika/tools/
    __init__.py              # Public API exports
    base.py                  # ITool ABC, ToolResult dataclass
    registry.py              # ToolRegistry — discover from builtins + project dir
```

No built-in tool implementations this phase. Agent-created tools go in `project_dir/tools/` and are discovered alongside builtins.

---

## 3. Core Types

### ToolResult

```python
@dataclass
class ToolResult:
    """What a tool execution produced."""
    outputs: dict[str, Any]       # Structured data (tables, stats, summaries)
    artifacts: list[str]          # Paths to output files (plots, CSVs)
    valid: bool = True            # Did the tool complete successfully?
    error: str | None = None      # Error message if valid=False
```

- `outputs` is `dict[str, Any]` because tools produce diverse data — profiling tables, correlation matrices, test statistics.
- `artifacts` maps to file paths for plots, saved tables, etc.
- `valid` flag allows tools to report failure without raising exceptions.
- `error` provides a reason when `valid=False`.

### ITool

```python
class ITool(ABC):
    """Interface for all analysis tools."""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def category(self) -> str: ...

    @abstractmethod
    def default_params(self) -> dict[str, Any]: ...

    @abstractmethod
    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult: ...
```

- `name()` — unique identifier (e.g. `"data_profiler"`).
- `description()` — human-readable summary for agents to understand what the tool does.
- `category()` — grouping label (e.g. `"exploration"`, `"statistical"`, `"visualization"`).
- `default_params()` — starting parameters agents can use or modify.
- `run(data, params)` — receives `DatasetView` from data loading, returns `ToolResult`.

---

## 4. Tool Registry

```python
class ToolRegistry:
    """Discover tools from builtins and project directory."""

    def register(self, tool: ITool) -> None: ...
    def get(self, name: str) -> ITool | None: ...
    def list_all(self) -> list[str]: ...
    def list_by_category(self, category: str) -> list[str]: ...

    def discover(self) -> None:
        """Discover built-in tools from src/urika/tools/ submodules."""

    def discover_project(self, tools_dir: Path) -> None:
        """Discover agent-created tools from a project's tools/ directory."""
```

- `discover()` scans `src/urika/tools/` using `pkgutil.iter_modules` + `get_tool()` factory convention — same pattern as MethodRegistry, ReaderRegistry, AgentRegistry.
- `discover_project(tools_dir)` scans a project's `tools/` directory using `importlib.util.spec_from_file_location` to load tools from arbitrary paths on disk.
- `list_by_category(category)` filters registered tools by their `category()` value.
- Both discovery methods call `register()`, so builtins and project tools are mixed in the same registry.

---

## 5. Agent-Created Tool Convention

Tools created by agents in `project_dir/tools/` must follow this pattern:

```python
# project_dir/tools/my_tool.py

class MyTool(ITool):
    def name(self) -> str: return "my_tool"
    def description(self) -> str: return "..."
    def category(self) -> str: return "exploration"
    def default_params(self) -> dict: return {}
    def run(self, data, params) -> ToolResult: ...

def get_tool() -> ITool:
    return MyTool()
```

The `get_tool()` factory function is required for discovery by `discover_project()`.

---

## 6. Integration Points

- **Task agents**: Discover available tools via ToolRegistry, call `run()`, use outputs for analysis decisions.
- **Tool Builder agent**: Creates tools in `project_dir/tools/`, following the convention above.
- **Project workspace**: Agent-created tools saved to `project_dir/tools/`, discovered via `discover_project()`.
- **Security**: Tool Builder agent has write access to `tools/` directory. Evaluator does not.
