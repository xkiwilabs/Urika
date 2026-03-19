# Tool & Method Reclassification Design

**Date:** 2026-03-20
**Status:** Approved

## Problem

The current distinction between "methods" and "tools" is wrong. Individual algorithms (linear_regression, random_forest, ANOVA, etc.) are classified as "methods" alongside actual tools (data_profiler, visualization). There's no principled difference — they're all individual building blocks.

A real "method" is a complete analytical pipeline that combines multiple tools: data profiling, feature selection, preprocessing, model fitting, hyperparameter tuning, evaluation. This is what the agent system should be creating.

## Design

### Tools — Building Blocks

All individual algorithms, tests, visualizers, and profilers are **tools**. They live in `src/urika/tools/`.

**Current tools (5):** data_profiler, correlation, hypothesis_tests, outlier_detection, visualization

**Moved from methods/ (8):** linear_regression, logistic_regression, random_forest, xgboost_regression, paired_t_test, descriptive_stats, one_way_anova, mann_whitney_u

**Interface:** `ITool` ABC unchanged. `ToolResult` gains optional `metrics: dict[str, float]` field (empty by default) so ML/stats tools can produce scoreable output.

**Discovery:** Built-in tools auto-discovered from `urika.tools.*`. Project-specific tools discovered from `project_dir/tools/`. Tool builder agent can create new tools, derive from existing ones, and `pip install` new packages.

**CLI:** `urika tools` lists all available tools (built-in + project-specific).

### Methods — Agent-Created Pipelines

A **method** is a complete analytical pipeline the agent writes as a Python script/module. It imports and combines tools into a full workflow. Methods are the core output of the agent system — what gets evaluated against success criteria.

**Package:** `src/urika/methods/` — repurposed, ships with zero built-in implementations.

- `base.py` — New `IMethod` ABC representing a pipeline, not a single algorithm
- `registry.py` — `MethodRegistry` discovers agent-created methods from `project_dir/methods/`
- Factory function: `get_method()`

**IMethod interface:**

```python
class IMethod(ABC):
    @abstractmethod
    def name(self) -> str: ...
    @abstractmethod
    def description(self) -> str: ...
    @abstractmethod
    def tools_used(self) -> list[str]: ...
    @abstractmethod
    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult: ...
```

**MethodResult** stays similar but represents pipeline output:

```python
@dataclass
class MethodResult:
    metrics: dict[str, float]
    artifacts: list[str] = field(default_factory=list)
    valid: bool = True
    error: str | None = None
```

**CLI:** `urika methods` repurposed to list agent-created methods per project (requires `--project` flag).

### Planning Agent — New Role

Currently the orchestrator goes straight from suggestion to task agent. The task agent designs AND implements the method, which is too much responsibility. A new **planning agent** sits between suggestion and task:

- **Input:** Research question, available tools, dataset profile, suggestion from last round
- **Output:** Structured method plan (preprocessing steps, tool selection, evaluation strategy, metrics to track)
- **Access:** Read-only. Can call literature agent for best practices.
- **Prompt variables:** `project_dir`, `experiment_id`, `experiment_dir`

### Updated Orchestrator Loop

**Project setup:** `Project Builder → Suggestion Agent` (seeds initial suggestions)

**Loop:**
```
Planning → Task → Evaluator → Suggestion → (repeat)
```

Every iteration has the same shape. No special first-iteration case.

**Support agents (called on-demand):**
- **Tool Builder** — called by task agent or evaluator when a needed tool doesn't exist
- **Literature Agent** — called by planner, task agent, or suggestion agent

```
┌─────────────────────────────────────────────────┐
│              Orchestrator Loop                   │
│                                                  │
│  ┌──────────┐    ┌──────┐    ┌───────────┐      │
│  │ Planning │───>│ Task │───>│ Evaluator │      │
│  └──────────┘    └──────┘    └───────────┘      │
│       ^                            │             │
│       │          ┌────────────┐    │             │
│       └──────────│ Suggestion │<───┘             │
│                  └────────────┘                  │
│                                                  │
│  Support agents (called on-demand):              │
│  ┌──────────────┐  ┌───────────────────┐        │
│  │ Tool Builder │  │ Literature Agent  │        │
│  └──────────────┘  └───────────────────┘        │
└─────────────────────────────────────────────────┘
```

### Project Builder Update

After interactive setup, the project builder calls the suggestion agent to seed initial suggestions. This means the first loop iteration starts with the planner reading existing suggestions, same as every subsequent iteration.

### What Changes

| Component | Change |
|-----------|--------|
| `src/urika/tools/base.py` | Add `metrics` field to `ToolResult` |
| `src/urika/tools/` | Add 8 modules moved from methods/ (interface changed to ITool) |
| `src/urika/methods/base.py` | Replace `IAnalysisMethod` with `IMethod` (pipeline interface) |
| `src/urika/methods/registry.py` | Update to discover project methods only (no built-ins) |
| `src/urika/methods/*.py` | Delete 8 algorithm implementations (moved to tools/) |
| `src/urika/agents/roles/` | Add `planning_agent.py` + prompt |
| `src/urika/orchestrator/loop.py` | Insert planning step, update flow |
| `src/urika/cli.py` | Update `methods` and `tools` commands |
| `tests/test_methods/` | Update tests for new IMethod interface |
| `tests/test_tools/` | Add tests for 8 moved modules |
| `README.md` | Update tools/methods sections |
| `CLAUDE.md` | Update module descriptions |
