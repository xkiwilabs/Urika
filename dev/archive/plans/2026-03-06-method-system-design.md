# Method System Design

**Date**: 2026-03-06
**Status**: Approved
**Context**: Phase 5 of Urika — method infrastructure for analysis methods.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Phase scope | Infrastructure only — no built-in methods | Prove the pattern. Agents write methods as Python files. |
| Interface style | Single `run()` method | Works for all analysis types (ML, stats tests, factor analysis). Simpler than fit/predict split. |
| State management | Stateless — params passed per-call | No `set_params`/`get_params`. Safer, simpler, no hidden state. |
| Discovery | Package builtins + project `methods/` dir | MethodRegistry discovers from both `src/urika/methods/` (shipped) and `project_dir/methods/` (agent-created). |
| Result structure | Metrics + artifacts only | MethodResult has `metrics: dict[str, float]` and `artifacts: list[str]`. Structured outputs (predictions, coefficients) saved as artifact files. Simple and serializable. |

---

## 2. Module Structure

```
src/urika/methods/
    __init__.py              # Public API exports
    base.py                  # IAnalysisMethod ABC, MethodResult dataclass
    registry.py              # MethodRegistry — discover from builtins + project dir
```

No built-in method implementations this phase. Agent-created methods go in `project_dir/methods/` and are discovered alongside builtins.

---

## 3. Core Types

### MethodResult

```python
@dataclass
class MethodResult:
    """What a method run produced."""
    metrics: dict[str, float]     # Computed metric values (r2, rmse, etc.)
    artifacts: list[str]          # Paths to output files (plots, CSVs, models)
    valid: bool = True            # Did the method complete successfully?
    error: str | None = None      # Error message if valid=False
```

- `metrics` maps directly to `RunRecord.metrics` — what the evaluation framework scores.
- `artifacts` maps to `RunRecord.artifacts` — file paths for plots, saved models, etc.
- `valid` flag allows methods to report failure without raising exceptions.
- `error` provides a reason when `valid=False`.

### IAnalysisMethod

```python
class IAnalysisMethod(ABC):
    """Interface for all analysis methods."""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def category(self) -> str: ...

    @abstractmethod
    def default_params(self) -> dict[str, Any]: ...

    @abstractmethod
    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult: ...
```

- `name()` — unique identifier (e.g. `"linear_regression"`).
- `description()` — human-readable summary for agents to understand what the method does.
- `category()` — grouping label (e.g. `"regression"`, `"classification"`, `"statistical_test"`).
- `default_params()` — starting parameters agents can use or modify.
- `run(data, params)` — receives `DatasetView` from data loading, returns `MethodResult`.

---

## 4. Method Registry

```python
class MethodRegistry:
    """Discover methods from builtins and project directory."""

    def register(self, method: IAnalysisMethod) -> None: ...
    def get(self, name: str) -> IAnalysisMethod | None: ...
    def list_all(self) -> list[str]: ...
    def list_by_category(self, category: str) -> list[str]: ...

    def discover(self) -> None:
        """Discover built-in methods from src/urika/methods/ submodules."""

    def discover_project(self, methods_dir: Path) -> None:
        """Discover agent-created methods from a project's methods/ directory."""
```

- `discover()` scans `src/urika/methods/` using `pkgutil.iter_modules` + `get_method()` factory convention — same pattern as MetricRegistry, AgentRegistry, ReaderRegistry.
- `discover_project(methods_dir)` scans a project's `methods/` directory using `importlib.util.spec_from_file_location` to load methods from arbitrary paths on disk.
- `list_by_category(category)` filters registered methods by their `category()` value.
- Both discovery methods call `register()`, so builtins and project methods are mixed in the same registry.

---

## 5. Integration Points

- **RunRecord**: `method` field stores method name, `params` stores parameters, `metrics` stores MethodResult.metrics.
- **Evaluation**: MethodResult.metrics are scored against success_criteria.json via `validate_criteria()`.
- **Leaderboard**: Methods ranked by primary_metric using method name from RunRecord.
- **Data loading**: Methods receive `DatasetView` — DataFrame with profiling summary.
- **Agents**: Task agents discover available methods via MethodRegistry, configure params, call `run()`, record results in progress.json.
- **Project workspace**: Agent-created methods saved to `project_dir/methods/`, discovered via `discover_project()`.

---

## 6. Agent-Created Method Convention

Methods created by agents in `project_dir/methods/` must follow this pattern:

```python
# project_dir/methods/my_method.py

class MyMethod(IAnalysisMethod):
    def name(self) -> str: return "my_method"
    def description(self) -> str: return "..."
    def category(self) -> str: return "regression"
    def default_params(self) -> dict: return {}
    def run(self, data, params) -> MethodResult: ...

def get_method() -> IAnalysisMethod:
    return MyMethod()
```

The `get_method()` factory function is required for discovery by `discover_project()`.
