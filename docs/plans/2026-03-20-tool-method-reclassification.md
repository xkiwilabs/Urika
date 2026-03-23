# Tool & Method Reclassification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reclassify all individual algorithms as tools, repurpose methods/ for agent-created pipelines, add planning agent, update orchestrator loop.

**Architecture:** All 8 algorithm modules move from `src/urika/methods/` to `src/urika/tools/`. The methods package is repurposed with a new `IMethod` ABC representing complete analytical pipelines (agent-created, zero built-ins). A new planning agent is added to the orchestrator loop: `planning → task → evaluator → suggestion`. The project builder seeds initial suggestions via the suggestion agent.

**Tech Stack:** Python, dataclasses, ABC, Click CLI, pytest

---

### Task 1: Add `metrics` field to `ToolResult`

**Files:**
- Modify: `src/urika/tools/base.py:13-20`
- Modify: `tests/test_tools/test_base.py`

**Step 1: Update the test for ToolResult to expect optional metrics field**

Add to `tests/test_tools/test_base.py` in the `TestToolResult` class:

```python
def test_create_with_metrics(self) -> None:
    result = ToolResult(
        outputs={"r2": 0.9},
        metrics={"r2": 0.9, "rmse": 0.1},
    )
    assert result.metrics == {"r2": 0.9, "rmse": 0.1}

def test_metrics_default_empty(self) -> None:
    result = ToolResult(outputs={"a": 1})
    assert result.metrics == {}
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools/test_base.py -v`
Expected: FAIL — `ToolResult` has no `metrics` field

**Step 3: Add `metrics` field to `ToolResult`**

In `src/urika/tools/base.py`, modify the `ToolResult` dataclass:

```python
@dataclass
class ToolResult:
    """What a tool execution produced."""

    outputs: dict[str, Any]
    artifacts: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    valid: bool = True
    error: str | None = None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tools/test_base.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/urika/tools/base.py tests/test_tools/test_base.py
git commit -m "feat: add optional metrics field to ToolResult"
```

---

### Task 2: Move 8 algorithm modules from methods/ to tools/

Each of the 8 modules needs: (a) change interface from `IAnalysisMethod`/`MethodResult` to `ITool`/`ToolResult`, (b) rename factory from `get_method()` to `get_tool()`, (c) change return type to `ToolResult` using both `outputs` and `metrics`, (d) move file, (e) move test file and update imports.

**Files:**
- Move: `src/urika/methods/linear_regression.py` → `src/urika/tools/linear_regression.py`
- Move: `src/urika/methods/logistic_regression.py` → `src/urika/tools/logistic_regression.py`
- Move: `src/urika/methods/random_forest.py` → `src/urika/tools/random_forest.py`
- Move: `src/urika/methods/xgboost_regression.py` → `src/urika/tools/xgboost_regression.py`
- Move: `src/urika/methods/paired_t_test.py` → `src/urika/tools/paired_t_test.py`
- Move: `src/urika/methods/descriptive_stats.py` → `src/urika/tools/descriptive_stats.py`
- Move: `src/urika/methods/one_way_anova.py` → `src/urika/tools/one_way_anova.py`
- Move: `src/urika/methods/mann_whitney_u.py` → `src/urika/tools/mann_whitney_u.py`
- Move: `tests/test_methods/test_linear_regression.py` → `tests/test_tools/test_linear_regression.py` (and same for all 8)
- Delete: `tests/test_methods/test_linear_regression.py` (and same for all 8)

**Step 1: For each module, apply the conversion pattern**

The conversion follows this pattern (using `linear_regression.py` as the example):

1. Change import from `from urika.methods.base import IAnalysisMethod, MethodResult` to `from urika.tools.base import ITool, ToolResult`
2. Change class to extend `ITool` instead of `IAnalysisMethod`
3. Change `run()` return type from `MethodResult` to `ToolResult`
4. Change all `return MethodResult(metrics={...})` to `return ToolResult(outputs={}, metrics={...})` — keep the metrics, add empty outputs dict
5. For error returns: change `return MethodResult(metrics={}, valid=False, error=...)` to `return ToolResult(outputs={}, valid=False, error=...)`
6. Change factory from `def get_method() -> IAnalysisMethod:` to `def get_tool() -> ITool:`
7. Move the file from `src/urika/methods/` to `src/urika/tools/`

For the corresponding test file:
1. Change all imports from `urika.methods.*` to `urika.tools.*`
2. Change all `MethodResult` references to `ToolResult`
3. Change `result.metrics` assertions — these stay the same since `ToolResult` now has `metrics`
4. Move from `tests/test_methods/` to `tests/test_tools/`

**Step 2: Move all 8 modules and test files, applying the pattern**

Do all 8 at once — they're independent. Use `git mv` for moves.

**Step 3: Run all tests**

Run: `pytest tests/test_tools/ -v`
Expected: All existing tool tests PASS + all 8 migrated tests PASS

**Step 4: Delete the old method module files (if git mv didn't handle it)**

Ensure `src/urika/methods/` has only `__init__.py`, `base.py`, and `registry.py` remaining.

**Step 5: Commit**

```bash
git add -A src/urika/methods/ src/urika/tools/ tests/test_methods/ tests/test_tools/
git commit -m "refactor: move 8 algorithm modules from methods/ to tools/"
```

---

### Task 3: Repurpose methods/ package with new IMethod ABC

Replace `IAnalysisMethod` (single algorithm interface) with `IMethod` (complete pipeline interface). Update registry to discover only from project directories (no built-in discovery needed since there are zero built-in methods).

**Files:**
- Rewrite: `src/urika/methods/base.py`
- Modify: `src/urika/methods/registry.py`
- Modify: `src/urika/methods/__init__.py`
- Rewrite: `tests/test_methods/test_base.py`
- Modify: `tests/test_methods/test_registry.py`
- Modify: `tests/test_methods/test_public_api.py`

**Step 1: Rewrite `src/urika/methods/base.py`**

```python
"""Base method interface and result type.

A method is a complete analytical pipeline — the core output of the agent
system.  Methods combine multiple tools into an end-to-end workflow
(preprocessing, modelling, evaluation) and are created by agents, not
shipped as built-ins.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from urika.data.models import DatasetView


@dataclass
class MethodResult:
    """What a method pipeline produced."""

    metrics: dict[str, float]
    artifacts: list[str] = field(default_factory=list)
    valid: bool = True
    error: str | None = None


class IMethod(ABC):
    """Interface for agent-created analytical pipelines.

    Unlike tools (individual building blocks), a method represents a
    complete analysis pipeline: data preparation, feature engineering,
    model fitting, hyperparameter tuning, and evaluation.
    """

    @abstractmethod
    def name(self) -> str:
        """Return the unique name of this method."""
        ...

    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description of the pipeline."""
        ...

    @abstractmethod
    def tools_used(self) -> list[str]:
        """Return names of tools this method uses."""
        ...

    @abstractmethod
    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult:
        """Execute the full pipeline on data with given parameters."""
        ...
```

**Step 2: Update `src/urika/methods/registry.py`**

- Change import from `IAnalysisMethod` to `IMethod`
- Remove `discover()` method (no built-in methods to discover)
- Keep `discover_project()` — this is how agent-created methods are found
- Update type references from `IAnalysisMethod` to `IMethod`
- Update factory function name from `get_method` to `get_method` (stays the same)

```python
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
```

**Step 3: Update `src/urika/methods/__init__.py`**

```python
"""Analysis method infrastructure — agent-created pipelines."""

from urika.methods.base import IMethod, MethodResult
from urika.methods.registry import MethodRegistry

__all__ = ["IMethod", "MethodRegistry", "MethodResult"]
```

**Step 4: Rewrite tests**

Rewrite `tests/test_methods/test_base.py` to test `IMethod` instead of `IAnalysisMethod`. The new `IMethod` has `tools_used()` instead of `category()` and `default_params()`.

Rewrite `tests/test_methods/test_registry.py` to remove `test_discover_finds_builtin_methods` (no built-ins), update fake method class to implement `IMethod`, update project discovery tests to use `IMethod`.

Rewrite `tests/test_methods/test_public_api.py` to import `IMethod` instead of `IAnalysisMethod`.

**Step 5: Run tests**

Run: `pytest tests/test_methods/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/urika/methods/ tests/test_methods/
git commit -m "refactor: repurpose methods/ for agent-created pipelines with IMethod ABC"
```

---

### Task 4: Update CLI — merge methods into tools command

**Files:**
- Modify: `src/urika/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Update the `methods` CLI command**

Change the `methods` command to list agent-created methods per project (requires `--project`). It should use the new `IMethod`-based `MethodRegistry` which only discovers from project directories.

```python
@cli.command()
@click.argument("project")
def methods(project: str) -> None:
    """List agent-created methods in a project."""
    from urika.methods import MethodRegistry

    project_path, _config = _resolve_project(project)
    registry = MethodRegistry()
    registry.discover_project(project_path / "methods")

    names = registry.list_all()
    if not names:
        click.echo("No methods created yet.")
        return

    for name in names:
        method = registry.get(name)
        if method is not None:
            tools = ", ".join(method.tools_used())
            click.echo(f"  {method.name()}  [{tools}]  {method.description()}")
```

**Step 2: Remove the old `MethodRegistry` import from the top of cli.py**

The top-level import `from urika.methods import MethodRegistry` should be removed since it's now lazy-imported inside the command.

**Step 3: Update the `tools` command**

The tools command needs no structural changes — it already uses `ToolRegistry.discover()`. The 8 migrated modules will be auto-discovered. But the test for builtin discovery (`test_discover_finds_builtin_methods` equivalent in tool registry tests) should now find 13 tools instead of 5.

**Step 4: Update CLI tests**

Update any test in `tests/test_cli.py` that references the old `methods` command signature. The `methods` command now takes a project argument and uses `IMethod`.

**Step 5: Run tests**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/urika/cli.py tests/test_cli.py
git commit -m "refactor: update CLI methods/tools commands for reclassification"
```

---

### Task 5: Add planning agent role

**Files:**
- Create: `src/urika/agents/roles/planning_agent.py`
- Create: `src/urika/agents/roles/prompts/planning_agent_system.md`
- Test: `tests/test_agents/test_roles.py` (add to existing tests)

**Step 1: Create planning agent prompt**

Create `src/urika/agents/roles/prompts/planning_agent_system.md`:

```markdown
# Planning Agent

You are a research methodology planner for the Urika analysis platform. Your role is strictly read-only: you design analytical pipelines but never modify files or run commands.

**Project directory:** {project_dir}
**Experiment ID:** {experiment_id}
**Experiment directory:** {experiment_dir}

## Your Mission

Design a complete analytical method (pipeline) for experiment `{experiment_id}` based on the research question, available tools, and suggestions from the previous round.

## Instructions

1. **Read** the project configuration at `{project_dir}/urika.toml` to understand the research question and success criteria.
2. **Read** the progress file at `{experiment_dir}/progress.json` to review previous methods and their results.
3. **Review** available tools by reading the project's tools directory and built-in tool documentation.
4. **Design** a complete method pipeline covering:
   - Data preprocessing (handling missing values, encoding, scaling)
   - Feature selection/engineering strategy
   - Model/analysis approach and which tools to use
   - Evaluation strategy (train/test split, cross-validation scheme)
   - Hyperparameter tuning approach (if applicable)
   - Metrics to track and success thresholds

## Output Format

Produce a single JSON block with your method plan:

```json
{{
  "method_name": "descriptive_name_for_this_approach",
  "description": "Brief description of the overall pipeline",
  "steps": [
    {{
      "step": 1,
      "action": "description of what to do",
      "tool": "tool_name_if_applicable",
      "params": {{}}
    }}
  ],
  "evaluation": {{
    "strategy": "e.g. 10-fold cross-validation",
    "metrics": ["metric_name"],
    "success_threshold": {{}}
  }},
  "needs_tool": false,
  "tool_description": "",
  "needs_literature": false,
  "literature_query": ""
}}
```

Set `needs_tool` to `true` if the plan requires a tool that doesn't exist yet, and describe it.
Set `needs_literature` to `true` if you need research literature to inform the plan.

## Rules

- Do NOT modify any files.
- Do NOT run any bash commands.
- Be specific about which tools to use and with what parameters.
- Design methods that are executable — every step must be actionable.
- Consider what has been tried before and avoid repeating failed approaches.
```

**Step 2: Create the planning agent role module**

Create `src/urika/agents/roles/planning_agent.py` following the same pattern as `evaluator.py`:

```python
"""Planning agent — designs analytical method pipelines."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.prompt import load_prompt

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="planning_agent",
        description="Designs complete analytical method pipelines",
        build_config=build_config,
    )


def build_config(
    project_dir: Path, *, experiment_id: str = "", **kwargs: object
) -> AgentConfig:
    experiment_dir = project_dir / "experiments" / experiment_id
    return AgentConfig(
        name="planning_agent",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "planning_agent_system.md",
            variables={
                "project_dir": str(project_dir),
                "experiment_id": experiment_id,
                "experiment_dir": str(experiment_dir),
            },
        ),
        allowed_tools=["Read", "Glob", "Grep"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        ),
        max_turns=10,
        cwd=project_dir,
    )
```

**Step 3: Add test for planning agent discovery**

In the existing agent role tests, add a test that `planning_agent` is discoverable by the registry.

**Step 4: Run tests**

Run: `pytest tests/test_agents/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/urika/agents/roles/planning_agent.py src/urika/agents/roles/prompts/planning_agent_system.md tests/test_agents/
git commit -m "feat: add planning agent role for method pipeline design"
```

---

### Task 6: Update orchestrator loop

Insert the planning agent step before the task agent. Update flow to: `planning → task → evaluator → suggestion`. Add `parse_method_plan()` to parsing.

**Files:**
- Modify: `src/urika/orchestrator/loop.py`
- Modify: `src/urika/orchestrator/parsing.py`
- Modify: `tests/test_orchestrator/test_loop.py`
- Modify: `tests/test_orchestrator/test_parsing.py`

**Step 1: Add `parse_method_plan` to parsing.py**

Add a new parsing function to `src/urika/orchestrator/parsing.py`:

```python
def parse_method_plan(text: str) -> dict[str, Any] | None:
    """Extract the first JSON block containing a 'method_name' and 'steps' key."""
    blocks = _extract_json_blocks(text)
    for block in blocks:
        if "method_name" in block and "steps" in block:
            return block
    return None
```

**Step 2: Update orchestrator loop**

In `src/urika/orchestrator/loop.py`, restructure the per-turn loop body:

1. **Planning agent** (new) — takes suggestions from previous round (or initial prompt), outputs method plan. If plan says `needs_tool`, call tool_builder. If plan says `needs_literature`, call literature_agent.
2. **Task agent** — takes the method plan as prompt, implements and runs the method.
3. **Evaluator** — scores the results.
4. **Suggestion agent** — proposes next direction based on evaluation.

The key change is the prompt flow:
- Before: `task_prompt` built from suggestions → fed to task_agent
- After: suggestions → fed to planning_agent → plan output → fed to task_agent

```python
# --- planning_agent ---
plan_role = registry.get("planning_agent")
if plan_role is not None:
    plan_config = plan_role.build_config(
        project_dir=project_dir, experiment_id=experiment_id
    )
    plan_result = await runner.run(plan_config, task_prompt)

    if not plan_result.success:
        fail_session(
            project_dir,
            experiment_id,
            error=plan_result.error or "planning_agent failed",
        )
        return {
            "status": "failed",
            "error": plan_result.error or "planning_agent failed",
            "turns": turn,
        }

    method_plan = parse_method_plan(plan_result.text_output)

    # Handle planning agent's tool/literature requests
    if method_plan and method_plan.get("needs_tool"):
        tool_role = registry.get("tool_builder")
        if tool_role is not None:
            tool_config = tool_role.build_config(project_dir=project_dir)
            await runner.run(tool_config, json.dumps(method_plan))

    if method_plan and method_plan.get("needs_literature"):
        lit_role = registry.get("literature_agent")
        if lit_role is not None:
            lit_config = lit_role.build_config(project_dir=project_dir)
            lit_result = await runner.run(
                lit_config, method_plan.get("literature_query", "")
            )
            if lit_result.success and lit_result.text_output:
                # Append literature context to the plan
                plan_result_text = (
                    lit_result.text_output + "\n\n" + plan_result.text_output
                )
            else:
                plan_result_text = plan_result.text_output
    else:
        plan_result_text = plan_result.text_output

    # Feed plan to task agent
    task_input = plan_result_text
else:
    task_input = task_prompt

# --- task_agent --- (now uses task_input instead of task_prompt)
```

Also move the suggestion agent's tool_builder and literature_agent support OUT of the suggestion section — those are now handled by the planning agent. The suggestion agent just outputs strategic direction. The suggestion output becomes the input to the next round's planning agent.

**Step 3: Update the post-suggestion logic**

After the suggestion agent runs, its output becomes the next round's `task_prompt` (which feeds into the planning agent):

```python
suggestions = parse_suggestions(suggest_result.text_output)
if suggestions:
    task_prompt = json.dumps(suggestions)
else:
    task_prompt = "Continue the experiment with a different approach."
```

Remove the old `needs_tool` and `needs_literature` handling from the suggestion section — those are now handled by the planning agent.

**Step 4: Add tests**

Add tests to `tests/test_orchestrator/test_loop.py`:
- `test_planning_agent_called_before_task_agent` — verify planning agent runs and its output feeds into task agent
- `test_planning_agent_not_found_falls_through` — if no planning agent registered, task agent gets suggestions directly

Add test to `tests/test_orchestrator/test_parsing.py`:
- `test_parse_method_plan_valid`
- `test_parse_method_plan_missing_keys`
- `test_parse_method_plan_no_blocks`

**Step 5: Run tests**

Run: `pytest tests/test_orchestrator/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/urika/orchestrator/ tests/test_orchestrator/
git commit -m "feat: insert planning agent into orchestrator loop"
```

---

### Task 7: Update integration tests, README, and CLAUDE.md

**Files:**
- Modify: `tests/test_integration.py`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `tests/test_tools/test_registry.py` — update discovery test to expect 13 tools

**Step 1: Update tool registry test**

In `tests/test_tools/test_registry.py`, the `test_discover_finds_builtin_tools` test should now expect 13 tools (5 original + 8 migrated). Update the assertions.

**Step 2: Update integration test**

In `tests/test_integration.py`, the smoke test references `urika methods` — update for new signature (now requires a project argument). Also update any mock patches that reference `urika.methods`.

**Step 3: Update README.md**

- Remove the "Built-in Methods" table (8 algorithms)
- Move those 8 into the "Built-in Tools" table (now 13 tools)
- Add a new "Methods" section explaining methods are agent-created pipelines
- Update the "How It Works" section to show the new loop: planning → task → evaluator → suggestion
- Update the agent list to include planning agent

**Step 4: Update CLAUDE.md**

- Update `src/urika/methods/` description to reflect pipeline-only, no built-ins
- Update `src/urika/tools/` to list all 13 tools
- Update CLI commands list (methods command now takes project argument)
- Update agent roles to include planning agent
- Update project status line

**Step 5: Run full test suite**

Run: `pytest -v`
Expected: ALL PASS

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`
Expected: Clean

**Step 6: Commit**

```bash
git add tests/ README.md CLAUDE.md
git commit -m "docs: update tests, README, CLAUDE.md for reclassification"
```
