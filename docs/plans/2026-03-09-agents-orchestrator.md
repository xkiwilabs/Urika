# Agent Roles & Orchestrator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement 4 agent roles (task agent, evaluator, suggestion agent, tool builder) and an orchestrator loop that runs experiments end-to-end by cycling through agents.

**Architecture:** Agent roles follow the existing echo pattern (module in `agents/roles/` with `get_role()` factory + markdown prompt). The orchestrator is a new `src/urika/orchestrator/` package with an async `run_experiment()` function that manages the deterministic loop with LLM decision points. Output parsing extracts RunRecords and suggestions from agent text.

**Tech Stack:** Existing agent infrastructure (AgentConfig, AgentRunner, ClaudeSDKRunner), session management, progress tracking, evaluation criteria

---

## Reference Files

Before starting, read these to understand the existing patterns:

- `src/urika/agents/config.py` — `AgentConfig`, `SecurityPolicy`, `AgentRole` dataclasses
- `src/urika/agents/runner.py` — `AgentRunner` ABC, `AgentResult` dataclass
- `src/urika/agents/prompt.py` — `load_prompt(path, variables)` with `{var}` substitution
- `src/urika/agents/roles/echo.py` — Echo agent role (follow this pattern exactly)
- `src/urika/agents/roles/prompts/echo_system.md` — Echo prompt (pattern for prompts)
- `tests/test_agents/test_echo_role.py` — Echo role tests (follow this pattern exactly)
- `src/urika/core/session.py` — `start_session()`, `update_turn()`, `complete_session()`, `fail_session()`, etc.
- `src/urika/core/progress.py` — `append_run()`, `load_progress()`, `get_best_run()`
- `src/urika/core/models.py` — `RunRecord`, `SessionState`
- `src/urika/evaluation/criteria.py` — `validate_criteria(metrics, criteria)`
- `docs/plans/2026-03-09-agents-orchestrator-design.md` — Approved design spec

---

### Task 1: Task Agent Role

**Files:**
- Create: `src/urika/agents/roles/task_agent.py`
- Create: `src/urika/agents/roles/prompts/task_agent_system.md`
- Create: `tests/test_agents/test_task_agent_role.py`

**Step 1: Write the failing tests**

Follow the exact same pattern as `tests/test_agents/test_echo_role.py`:

```python
"""Tests for the task agent role."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole
from urika.agents.registry import AgentRegistry
from urika.agents.roles.task_agent import get_role


class TestTaskAgentRole:
    def test_get_role_returns_agent_role(self) -> None:
        role = get_role()
        assert isinstance(role, AgentRole)
        assert role.name == "task_agent"

    def test_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert isinstance(config, AgentConfig)
        assert config.name == "task_agent"

    def test_config_has_write_and_bash_tools(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert "Read" in config.allowed_tools
        assert "Write" in config.allowed_tools
        assert "Bash" in config.allowed_tools
        assert "Glob" in config.allowed_tools
        assert "Grep" in config.allowed_tools

    def test_config_security_writable_experiment_dir(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        exp_dir = tmp_path / "experiments" / "exp-001-test"
        assert any(
            d.resolve() == exp_dir.resolve() for d in config.security.writable_dirs
        )

    def test_config_security_bash_restricted(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert config.security.is_bash_allowed("python script.py")
        assert config.security.is_bash_allowed("pip install numpy")
        assert not config.security.is_bash_allowed("rm -rf /")
        assert not config.security.is_bash_allowed("git push")

    def test_config_has_system_prompt(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert len(config.system_prompt) > 0
        assert str(tmp_path) in config.system_prompt

    def test_config_prompt_includes_experiment_id(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert "exp-001-test" in config.system_prompt

    def test_config_max_turns(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert config.max_turns == 25

    def test_discoverable_by_registry(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        assert "task_agent" in registry.list_all()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_task_agent_role.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'urika.agents.roles.task_agent'`

**Step 3: Write the system prompt**

Create `src/urika/agents/roles/prompts/task_agent_system.md`:

```markdown
# Task Agent

You are a research scientist working on the Urika analysis platform. Your job is to explore data, run analysis methods, and record your observations.

**Project directory:** {project_dir}
**Experiment:** {experiment_id}
**Experiment directory:** {experiment_dir}

## Your Responsibilities

1. Explore the dataset to understand its structure and contents
2. Run analysis methods using Python and the installed Urika methods
3. Record your observations and results
4. Write artifacts (plots, models) to `{experiment_dir}/artifacts/`

## Available Methods

Use Python to import and run methods:

```python
from urika.methods import MethodRegistry
from urika.data.loader import load_dataset

# Discover available methods
registry = MethodRegistry()
registry.discover()
print(registry.list_all())

# Load data
view = load_dataset("{project_dir}/data/<file>")

# Run a method
method = registry.get("linear_regression")
result = method.run(view, {{"target": "column_name", "features": ["col1", "col2"]}})
print(result.metrics)
```

## Output Format

After each analysis run, output a JSON block with your results:

```json
{{
  "run_id": "run-001",
  "method": "linear_regression",
  "params": {{"target": "y", "features": ["x1", "x2"]}},
  "metrics": {{"r2": 0.85, "rmse": 0.12}},
  "hypothesis": "Linear model on x1, x2 predicts y",
  "observation": "Good fit with R2=0.85",
  "next_step": "Try random forest for comparison"
}}
```

## Constraints

- Only write files inside `{experiment_dir}/`
- Only run Python and pip commands
- Do NOT modify project configuration files
- Do NOT install packages outside the project environment
```

**Step 4: Write the implementation**

Create `src/urika/agents/roles/task_agent.py`:

```python
"""Task agent — explores data, runs methods, records observations."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.prompt import load_prompt

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="task_agent",
        description="Explores data, runs analysis methods, records observations",
        build_config=build_config,
    )


def build_config(project_dir: Path, *, experiment_id: str = "", **kwargs: object) -> AgentConfig:
    experiment_dir = project_dir / "experiments" / experiment_id
    return AgentConfig(
        name="task_agent",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "task_agent_system.md",
            variables={
                "project_dir": str(project_dir),
                "experiment_id": experiment_id,
                "experiment_dir": str(experiment_dir),
            },
        ),
        allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[experiment_dir],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=["python ", "pip "],
            blocked_bash_patterns=["rm -rf", "git push", "git reset"],
        ),
        max_turns=25,
        cwd=project_dir,
    )
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_agents/test_task_agent_role.py -v`
Expected: 9 PASSED

**Step 6: Lint and commit**

```bash
ruff check src/urika/agents/roles/task_agent.py tests/test_agents/test_task_agent_role.py
ruff format --check src/urika/agents/roles/task_agent.py tests/test_agents/test_task_agent_role.py
git add src/urika/agents/roles/task_agent.py src/urika/agents/roles/prompts/task_agent_system.md tests/test_agents/test_task_agent_role.py
git commit -m "feat: add task agent role"
```

---

### Task 2: Evaluator + Suggestion Agent + Tool Builder Roles

**Files:**
- Create: `src/urika/agents/roles/evaluator.py`
- Create: `src/urika/agents/roles/suggestion_agent.py`
- Create: `src/urika/agents/roles/tool_builder.py`
- Create: `src/urika/agents/roles/prompts/evaluator_system.md`
- Create: `src/urika/agents/roles/prompts/suggestion_agent_system.md`
- Create: `src/urika/agents/roles/prompts/tool_builder_system.md`
- Create: `tests/test_agents/test_evaluator_role.py`
- Create: `tests/test_agents/test_suggestion_agent_role.py`
- Create: `tests/test_agents/test_tool_builder_role.py`

**Step 1: Write the failing tests**

`tests/test_agents/test_evaluator_role.py`:

```python
"""Tests for the evaluator agent role."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole
from urika.agents.registry import AgentRegistry
from urika.agents.roles.evaluator import get_role


class TestEvaluatorRole:
    def test_get_role_returns_agent_role(self) -> None:
        role = get_role()
        assert isinstance(role, AgentRole)
        assert role.name == "evaluator"

    def test_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert isinstance(config, AgentConfig)
        assert config.name == "evaluator"

    def test_config_is_read_only(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert "Read" in config.allowed_tools
        assert "Glob" in config.allowed_tools
        assert "Grep" in config.allowed_tools
        assert "Write" not in config.allowed_tools
        assert "Bash" not in config.allowed_tools

    def test_config_security_no_write(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert config.security.writable_dirs == []

    def test_config_has_system_prompt(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert len(config.system_prompt) > 0
        assert "exp-001-test" in config.system_prompt

    def test_config_max_turns(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert config.max_turns == 10

    def test_discoverable_by_registry(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        assert "evaluator" in registry.list_all()
```

`tests/test_agents/test_suggestion_agent_role.py`:

```python
"""Tests for the suggestion agent role."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole
from urika.agents.registry import AgentRegistry
from urika.agents.roles.suggestion_agent import get_role


class TestSuggestionAgentRole:
    def test_get_role_returns_agent_role(self) -> None:
        role = get_role()
        assert isinstance(role, AgentRole)
        assert role.name == "suggestion_agent"

    def test_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert isinstance(config, AgentConfig)
        assert config.name == "suggestion_agent"

    def test_config_is_read_only(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert "Read" in config.allowed_tools
        assert "Write" not in config.allowed_tools
        assert "Bash" not in config.allowed_tools

    def test_config_security_no_write(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert config.security.writable_dirs == []

    def test_config_has_system_prompt(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert len(config.system_prompt) > 0
        assert "exp-001-test" in config.system_prompt

    def test_config_max_turns(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001-test")
        assert config.max_turns == 10

    def test_discoverable_by_registry(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        assert "suggestion_agent" in registry.list_all()
```

`tests/test_agents/test_tool_builder_role.py`:

```python
"""Tests for the tool builder agent role."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole
from urika.agents.registry import AgentRegistry
from urika.agents.roles.tool_builder import get_role


class TestToolBuilderRole:
    def test_get_role_returns_agent_role(self) -> None:
        role = get_role()
        assert isinstance(role, AgentRole)
        assert role.name == "tool_builder"

    def test_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert isinstance(config, AgentConfig)
        assert config.name == "tool_builder"

    def test_config_has_write_and_bash_tools(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert "Read" in config.allowed_tools
        assert "Write" in config.allowed_tools
        assert "Bash" in config.allowed_tools

    def test_config_security_writable_tools_dir(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        tools_dir = tmp_path / "tools"
        assert any(
            d.resolve() == tools_dir.resolve() for d in config.security.writable_dirs
        )

    def test_config_security_bash_restricted(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert config.security.is_bash_allowed("python script.py")
        assert config.security.is_bash_allowed("pip install numpy")
        assert config.security.is_bash_allowed("pytest tests/")
        assert not config.security.is_bash_allowed("rm -rf /")

    def test_config_has_system_prompt(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert len(config.system_prompt) > 0
        assert str(tmp_path) in config.system_prompt

    def test_config_max_turns(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert config.max_turns == 15

    def test_discoverable_by_registry(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        assert "tool_builder" in registry.list_all()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_evaluator_role.py tests/test_agents/test_suggestion_agent_role.py tests/test_agents/test_tool_builder_role.py -v`
Expected: FAIL — ModuleNotFoundError for all three

**Step 3: Write the system prompts**

`src/urika/agents/roles/prompts/evaluator_system.md`:

```markdown
# Evaluator

You are a scientific reviewer on the Urika analysis platform. Your job is to objectively evaluate experiment results against success criteria.

**Project directory:** {project_dir}
**Experiment:** {experiment_id}
**Experiment directory:** {experiment_dir}

## Your Responsibilities

1. Read results from `{experiment_dir}/progress.json`
2. Read success criteria from `{project_dir}/config/success_criteria.json` (if it exists)
3. Score each run's metrics against the criteria
4. Determine whether success criteria have been met

## Output Format

Output a JSON block with your evaluation:

```json
{{
  "criteria_met": false,
  "best_metrics": {{"r2": 0.85, "rmse": 0.12}},
  "failures": ["r2: 0.85 < 0.90 (min)"],
  "summary": "Best model achieves R2=0.85 but criteria requires R2>=0.90"
}}
```

## Constraints

- You are READ-ONLY. Do NOT modify any files.
- Be objective — report metrics as they are.
- If no success criteria file exists, evaluate based on general quality.
```

`src/urika/agents/roles/prompts/suggestion_agent_system.md`:

```markdown
# Suggestion Agent

You are a research advisor on the Urika analysis platform. Your job is to analyze experiment results and propose next steps.

**Project directory:** {project_dir}
**Experiment:** {experiment_id}
**Experiment directory:** {experiment_dir}

## Your Responsibilities

1. Review results in `{experiment_dir}/progress.json`
2. Review the labbook in `{experiment_dir}/labbook/`
3. Analyze what has been tried and what worked
4. Propose 1-3 concrete next experiments with hypotheses

## Output Format

Output a JSON block with your suggestions:

```json
{{
  "suggestions": [
    {{
      "name": "feature-engineering",
      "hypothesis": "Adding interaction terms will improve R2 by 5%",
      "method": "linear_regression",
      "rationale": "Current model uses raw features only"
    }}
  ],
  "needs_tool": false,
  "tool_description": null
}}
```

Set `needs_tool` to `true` if the next step requires building a custom analysis tool. Describe what the tool should do in `tool_description`.

## Constraints

- You are READ-ONLY. Do NOT modify any files.
- Be specific — suggest concrete methods and parameters.
- Base suggestions on actual results, not speculation.
```

`src/urika/agents/roles/prompts/tool_builder_system.md`:

```markdown
# Tool Builder

You are a tool developer on the Urika analysis platform. Your job is to create project-specific analysis tools.

**Project directory:** {project_dir}
**Tools directory:** {tools_dir}

## Your Responsibilities

1. Create Python tools in `{tools_dir}/`
2. Each tool must implement the `ITool` interface
3. Each tool file must have a `get_tool()` factory function
4. Write tests and verify they pass

## Tool Template

```python
from urika.tools.base import ITool, ToolResult
from typing import Any

class MyTool(ITool):
    def name(self) -> str:
        return "my_tool"

    def description(self) -> str:
        return "What this tool does"

    def category(self) -> str:
        return "exploration"

    def default_params(self) -> dict[str, Any]:
        return {{}}

    def run(self, data, params: dict[str, Any]) -> ToolResult:
        # Implementation here
        return ToolResult(outputs={{}})

def get_tool() -> ITool:
    return MyTool()
```

## Constraints

- Only write files inside `{tools_dir}/`
- Only run Python, pip, and pytest commands
- Each tool MUST have a `get_tool()` factory function
- Test your tool before finishing
```

**Step 4: Write the implementations**

`src/urika/agents/roles/evaluator.py`:

```python
"""Evaluator agent — read-only scoring and criteria validation."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.prompt import load_prompt

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="evaluator",
        description="Scores results, validates against success criteria",
        build_config=build_config,
    )


def build_config(project_dir: Path, *, experiment_id: str = "", **kwargs: object) -> AgentConfig:
    experiment_dir = project_dir / "experiments" / experiment_id
    return AgentConfig(
        name="evaluator",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "evaluator_system.md",
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

`src/urika/agents/roles/suggestion_agent.py`:

```python
"""Suggestion agent — analyzes results, proposes next experiments."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.prompt import load_prompt

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="suggestion_agent",
        description="Analyzes results, proposes next experiments with hypotheses",
        build_config=build_config,
    )


def build_config(project_dir: Path, *, experiment_id: str = "", **kwargs: object) -> AgentConfig:
    experiment_dir = project_dir / "experiments" / experiment_id
    return AgentConfig(
        name="suggestion_agent",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "suggestion_agent_system.md",
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

`src/urika/agents/roles/tool_builder.py`:

```python
"""Tool builder agent — creates project-specific tools."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.prompt import load_prompt

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="tool_builder",
        description="Creates project-specific analysis tools",
        build_config=build_config,
    )


def build_config(project_dir: Path, **kwargs: object) -> AgentConfig:
    tools_dir = project_dir / "tools"
    return AgentConfig(
        name="tool_builder",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "tool_builder_system.md",
            variables={
                "project_dir": str(project_dir),
                "tools_dir": str(tools_dir),
            },
        ),
        allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[tools_dir],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=["python ", "pip ", "pytest "],
            blocked_bash_patterns=["rm -rf", "git push", "git reset"],
        ),
        max_turns=15,
        cwd=project_dir,
    )
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_agents/ -v`
Expected: All agent tests PASS

**Step 6: Lint and commit**

```bash
ruff check src/urika/agents/roles/ tests/test_agents/
ruff format --check src/urika/agents/roles/ tests/test_agents/
git add src/urika/agents/roles/evaluator.py src/urika/agents/roles/suggestion_agent.py src/urika/agents/roles/tool_builder.py src/urika/agents/roles/prompts/evaluator_system.md src/urika/agents/roles/prompts/suggestion_agent_system.md src/urika/agents/roles/prompts/tool_builder_system.md tests/test_agents/test_evaluator_role.py tests/test_agents/test_suggestion_agent_role.py tests/test_agents/test_tool_builder_role.py
git commit -m "feat: add evaluator, suggestion agent, and tool builder roles"
```

---

### Task 3: Output Parsing Module

**Files:**
- Create: `src/urika/orchestrator/__init__.py`
- Create: `src/urika/orchestrator/parsing.py`
- Create: `tests/test_orchestrator/__init__.py`
- Create: `tests/test_orchestrator/test_parsing.py`

**Step 1: Write the failing tests**

```python
"""Tests for orchestrator output parsing."""

from __future__ import annotations

from urika.orchestrator.parsing import parse_run_records, parse_evaluation, parse_suggestions


class TestParseRunRecords:
    def test_extracts_single_run(self) -> None:
        text = '''I ran the analysis.

```json
{
  "run_id": "run-001",
  "method": "linear_regression",
  "params": {"target": "y"},
  "metrics": {"r2": 0.85},
  "hypothesis": "Linear fit",
  "observation": "Good fit",
  "next_step": "Try RF"
}
```

Done.'''
        records = parse_run_records(text)
        assert len(records) == 1
        assert records[0].run_id == "run-001"
        assert records[0].method == "linear_regression"
        assert records[0].metrics == {"r2": 0.85}

    def test_extracts_multiple_runs(self) -> None:
        text = '''First run:
```json
{"run_id": "run-001", "method": "lr", "params": {}, "metrics": {"r2": 0.5}, "hypothesis": "H1", "observation": "O1", "next_step": "N1"}
```
Second run:
```json
{"run_id": "run-002", "method": "rf", "params": {}, "metrics": {"r2": 0.7}, "hypothesis": "H2", "observation": "O2", "next_step": "N2"}
```'''
        records = parse_run_records(text)
        assert len(records) == 2
        assert records[0].run_id == "run-001"
        assert records[1].run_id == "run-002"

    def test_ignores_non_run_json(self) -> None:
        text = '''Here is some config:
```json
{"name": "test", "value": 42}
```'''
        records = parse_run_records(text)
        assert len(records) == 0

    def test_empty_text(self) -> None:
        records = parse_run_records("")
        assert records == []

    def test_no_json_blocks(self) -> None:
        records = parse_run_records("Just some text without JSON.")
        assert records == []

    def test_malformed_json_skipped(self) -> None:
        text = '''```json
{"run_id": "run-001", "method": "lr", INVALID
```'''
        records = parse_run_records(text)
        assert records == []


class TestParseEvaluation:
    def test_extracts_evaluation(self) -> None:
        text = '''My evaluation:
```json
{
  "criteria_met": false,
  "best_metrics": {"r2": 0.85},
  "failures": ["r2: 0.85 < 0.90 (min)"],
  "summary": "Not meeting criteria"
}
```'''
        result = parse_evaluation(text)
        assert result is not None
        assert result["criteria_met"] is False
        assert result["best_metrics"]["r2"] == 0.85

    def test_returns_none_when_no_evaluation(self) -> None:
        result = parse_evaluation("No JSON here.")
        assert result is None

    def test_returns_none_for_non_evaluation_json(self) -> None:
        text = '''```json
{"run_id": "run-001", "method": "lr"}
```'''
        result = parse_evaluation(text)
        assert result is None


class TestParseSuggestions:
    def test_extracts_suggestions(self) -> None:
        text = '''My suggestions:
```json
{
  "suggestions": [
    {"name": "try-rf", "hypothesis": "RF will improve R2", "method": "random_forest", "rationale": "Nonlinear patterns"}
  ],
  "needs_tool": false,
  "tool_description": null
}
```'''
        result = parse_suggestions(text)
        assert result is not None
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["name"] == "try-rf"
        assert result["needs_tool"] is False

    def test_returns_none_when_no_suggestions(self) -> None:
        result = parse_suggestions("No JSON here.")
        assert result is None

    def test_detects_tool_needed(self) -> None:
        text = '''```json
{
  "suggestions": [],
  "needs_tool": true,
  "tool_description": "Build a custom feature extractor"
}
```'''
        result = parse_suggestions(text)
        assert result is not None
        assert result["needs_tool"] is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator/test_parsing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'urika.orchestrator'`

**Step 3: Write the implementation**

Create `src/urika/orchestrator/__init__.py` (empty for now, populated in Task 5).

Create `tests/test_orchestrator/__init__.py` (empty).

Create `src/urika/orchestrator/parsing.py`:

```python
"""Parse structured output from agent text responses."""

from __future__ import annotations

import json
import re
from typing import Any

from urika.core.models import RunRecord


def _extract_json_blocks(text: str) -> list[dict[str, Any]]:
    """Extract all JSON blocks from markdown-formatted text."""
    pattern = r"```json\s*\n(.*?)\n\s*```"
    blocks: list[dict[str, Any]] = []
    for match in re.finditer(pattern, text, re.DOTALL):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                blocks.append(data)
        except json.JSONDecodeError:
            continue
    return blocks


def parse_run_records(text: str) -> list[RunRecord]:
    """Extract RunRecords from agent output text."""
    records: list[RunRecord] = []
    for block in _extract_json_blocks(text):
        if "run_id" not in block or "method" not in block or "metrics" not in block:
            continue
        records.append(
            RunRecord(
                run_id=block["run_id"],
                method=block["method"],
                params=block.get("params", {}),
                metrics=block["metrics"],
                hypothesis=block.get("hypothesis", ""),
                observation=block.get("observation", ""),
                next_step=block.get("next_step", ""),
                artifacts=block.get("artifacts", []),
            )
        )
    return records


def parse_evaluation(text: str) -> dict[str, Any] | None:
    """Extract evaluation result from evaluator agent output."""
    for block in _extract_json_blocks(text):
        if "criteria_met" in block:
            return block
    return None


def parse_suggestions(text: str) -> dict[str, Any] | None:
    """Extract suggestions from suggestion agent output."""
    for block in _extract_json_blocks(text):
        if "suggestions" in block:
            return block
    return None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator/test_parsing.py -v`
Expected: 12 PASSED

**Step 5: Lint and commit**

```bash
ruff check src/urika/orchestrator/ tests/test_orchestrator/
ruff format --check src/urika/orchestrator/ tests/test_orchestrator/
git add src/urika/orchestrator/__init__.py src/urika/orchestrator/parsing.py tests/test_orchestrator/__init__.py tests/test_orchestrator/test_parsing.py
git commit -m "feat: add orchestrator output parsing"
```

---

### Task 4: Orchestrator Loop

**Files:**
- Create: `src/urika/orchestrator/loop.py`
- Create: `tests/test_orchestrator/test_loop.py`

**Step 1: Write the failing tests**

These tests use a `FakeRunner` that returns canned results to test loop logic without the SDK.

```python
"""Tests for the orchestrator loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.core.experiment import create_experiment
from urika.core.models import RunRecord
from urika.core.progress import load_progress
from urika.core.session import load_session
from urika.core.workspace import create_project_workspace
from urika.core.models import ProjectConfig
from urika.orchestrator.loop import run_experiment


class FakeRunner(AgentRunner):
    """Returns canned responses for each agent role."""

    def __init__(self, responses: dict[str, list[str]]) -> None:
        self._responses = responses
        self._call_counts: dict[str, int] = {}

    async def run(self, config: AgentConfig, prompt: str) -> AgentResult:
        role = config.name
        self._call_counts[role] = self._call_counts.get(role, 0) + 1
        idx = self._call_counts[role] - 1
        texts = self._responses.get(role, [""])
        text = texts[idx] if idx < len(texts) else texts[-1]
        return AgentResult(
            success=True,
            messages=[],
            text_output=text,
            session_id=f"session-{role}-{idx}",
            num_turns=1,
            duration_ms=100,
        )

    @property
    def call_counts(self) -> dict[str, int]:
        return dict(self._call_counts)


def _setup_project(tmp_path: Path) -> tuple[Path, str]:
    """Create a project with one experiment for testing."""
    config = ProjectConfig(
        name="test-proj",
        question="Does X predict Y?",
        mode="exploratory",
        data_paths=[],
    )
    project_dir = tmp_path / "test-proj"
    create_project_workspace(project_dir, config)
    exp = create_experiment(project_dir, name="baseline", hypothesis="Linear is enough")
    return project_dir, exp.experiment_id


_TASK_OUTPUT = '''```json
{"run_id": "run-001", "method": "linear_regression", "params": {"target": "y"}, "metrics": {"r2": 0.85}, "hypothesis": "Linear fit", "observation": "Good", "next_step": "Try RF"}
```'''

_EVAL_CRITERIA_MET = '''```json
{"criteria_met": true, "best_metrics": {"r2": 0.85}, "failures": [], "summary": "Criteria met"}
```'''

_EVAL_CRITERIA_NOT_MET = '''```json
{"criteria_met": false, "best_metrics": {"r2": 0.5}, "failures": ["r2 too low"], "summary": "Not met"}
```'''

_SUGGESTION = '''```json
{"suggestions": [{"name": "try-rf", "hypothesis": "RF better", "method": "random_forest", "rationale": "Nonlinear"}], "needs_tool": false, "tool_description": null}
```'''


class TestRunExperiment:
    @pytest.mark.asyncio
    async def test_completes_when_criteria_met(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner({
            "task_agent": [_TASK_OUTPUT],
            "evaluator": [_EVAL_CRITERIA_MET],
            "suggestion_agent": [_SUGGESTION],
        })
        result = await run_experiment(project_dir, exp_id, runner, max_turns=5)
        assert result["status"] == "completed"
        assert result["turns"] >= 1

    @pytest.mark.asyncio
    async def test_stops_at_max_turns(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner({
            "task_agent": [_TASK_OUTPUT],
            "evaluator": [_EVAL_CRITERIA_NOT_MET],
            "suggestion_agent": [_SUGGESTION],
        })
        result = await run_experiment(project_dir, exp_id, runner, max_turns=2)
        assert result["turns"] <= 2

    @pytest.mark.asyncio
    async def test_records_runs_to_progress(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner({
            "task_agent": [_TASK_OUTPUT],
            "evaluator": [_EVAL_CRITERIA_MET],
            "suggestion_agent": [_SUGGESTION],
        })
        await run_experiment(project_dir, exp_id, runner, max_turns=5)
        progress = load_progress(project_dir, exp_id)
        assert len(progress["runs"]) >= 1
        assert progress["runs"][0]["method"] == "linear_regression"

    @pytest.mark.asyncio
    async def test_session_state_updated(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner({
            "task_agent": [_TASK_OUTPUT],
            "evaluator": [_EVAL_CRITERIA_MET],
            "suggestion_agent": [_SUGGESTION],
        })
        await run_experiment(project_dir, exp_id, runner, max_turns=5)
        session = load_session(project_dir, exp_id)
        assert session is not None
        assert session.status in ("completed", "failed")

    @pytest.mark.asyncio
    async def test_handles_runner_error(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)

        class ErrorRunner(AgentRunner):
            async def run(self, config: AgentConfig, prompt: str) -> AgentResult:
                return AgentResult(
                    success=False, messages=[], text_output="",
                    session_id="", num_turns=0, duration_ms=0,
                    error="SDK error",
                )

        result = await run_experiment(project_dir, exp_id, ErrorRunner(), max_turns=5)
        assert result["status"] == "failed"
        session = load_session(project_dir, exp_id)
        assert session is not None
        assert session.status == "failed"

    @pytest.mark.asyncio
    async def test_calls_agents_in_order(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner({
            "task_agent": [_TASK_OUTPUT],
            "evaluator": [_EVAL_CRITERIA_MET],
            "suggestion_agent": [_SUGGESTION],
        })
        await run_experiment(project_dir, exp_id, runner, max_turns=1)
        assert runner.call_counts.get("task_agent", 0) >= 1
        assert runner.call_counts.get("evaluator", 0) >= 1

    @pytest.mark.asyncio
    async def test_multiple_turns(self, tmp_path: Path) -> None:
        """Two turns of not-met, then met on third."""
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner({
            "task_agent": [_TASK_OUTPUT],
            "evaluator": [_EVAL_CRITERIA_NOT_MET, _EVAL_CRITERIA_NOT_MET, _EVAL_CRITERIA_MET],
            "suggestion_agent": [_SUGGESTION],
        })
        result = await run_experiment(project_dir, exp_id, runner, max_turns=10)
        assert result["status"] == "completed"
        assert result["turns"] == 3
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator/test_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'urika.orchestrator.loop'`

**Step 3: Write the implementation**

Create `src/urika/orchestrator/loop.py`:

```python
"""Orchestrator loop — runs experiments by cycling through agents."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from urika.agents.config import AgentRole
from urika.agents.registry import AgentRegistry
from urika.agents.runner import AgentRunner
from urika.core.progress import append_run
from urika.core.session import (
    complete_session,
    fail_session,
    record_agent_session,
    start_session,
    update_turn,
)
from urika.orchestrator.parsing import parse_evaluation, parse_run_records, parse_suggestions

logger = logging.getLogger(__name__)


async def run_experiment(
    project_dir: Path,
    experiment_id: str,
    runner: AgentRunner,
    *,
    max_turns: int = 50,
) -> dict[str, Any]:
    """Run an experiment by cycling task → evaluator → suggestion agents.

    Returns a dict with 'status', 'turns', and 'error' (if failed).
    """
    registry = AgentRegistry()
    registry.discover()

    task_role = registry.get("task_agent")
    evaluator_role = registry.get("evaluator")
    suggestion_role = registry.get("suggestion_agent")
    tool_builder_role = registry.get("tool_builder")

    if not all([task_role, evaluator_role, suggestion_role]):
        return {"status": "failed", "turns": 0, "error": "Required agent roles not found"}

    start_session(project_dir, experiment_id, max_turns=max_turns)

    task_prompt = "Begin exploring the dataset and run initial analyses."
    turns_completed = 0

    try:
        for turn in range(max_turns):
            # 1. Task agent
            task_config = task_role.build_config(project_dir, experiment_id=experiment_id)
            task_result = await runner.run(task_config, task_prompt)

            if not task_result.success:
                fail_session(project_dir, experiment_id, error=task_result.error or "Task agent failed")
                return {"status": "failed", "turns": turns_completed, "error": task_result.error}

            record_agent_session(project_dir, experiment_id, "task_agent", task_result.session_id)

            # Parse and record runs
            run_records = parse_run_records(task_result.text_output)
            for record in run_records:
                append_run(project_dir, experiment_id, record)

            # 2. Evaluator
            eval_config = evaluator_role.build_config(project_dir, experiment_id=experiment_id)
            eval_result = await runner.run(eval_config, "Evaluate the experiment results.")

            if not eval_result.success:
                fail_session(project_dir, experiment_id, error=eval_result.error or "Evaluator failed")
                return {"status": "failed", "turns": turns_completed, "error": eval_result.error}

            record_agent_session(project_dir, experiment_id, "evaluator", eval_result.session_id)

            evaluation = parse_evaluation(eval_result.text_output)
            turns_completed = turn + 1
            update_turn(project_dir, experiment_id)

            # Check if criteria met
            if evaluation and evaluation.get("criteria_met"):
                complete_session(project_dir, experiment_id)
                return {"status": "completed", "turns": turns_completed, "error": None}

            # 3. Suggestion agent
            suggestion_config = suggestion_role.build_config(project_dir, experiment_id=experiment_id)
            suggestion_result = await runner.run(suggestion_config, "Suggest next experiments.")

            if suggestion_result.success:
                record_agent_session(project_dir, experiment_id, "suggestion_agent", suggestion_result.session_id)
                suggestions = parse_suggestions(suggestion_result.text_output)

                # 4. Tool builder (on demand)
                if suggestions and suggestions.get("needs_tool") and tool_builder_role:
                    tool_desc = suggestions.get("tool_description", "Build a custom tool")
                    tb_config = tool_builder_role.build_config(project_dir)
                    tb_result = await runner.run(tb_config, tool_desc)
                    if tb_result.success:
                        record_agent_session(project_dir, experiment_id, "tool_builder", tb_result.session_id)

                # Build next prompt from suggestions
                if suggestions and suggestions.get("suggestions"):
                    items = suggestions["suggestions"]
                    task_prompt = "Based on previous results, try these approaches:\n"
                    for s in items:
                        task_prompt += f"- {s.get('name', 'unnamed')}: {s.get('hypothesis', '')}\n"
                else:
                    task_prompt = "Continue exploring and try different approaches."

        # Reached max turns
        complete_session(project_dir, experiment_id)
        return {"status": "completed", "turns": turns_completed, "error": None}

    except Exception as exc:
        fail_session(project_dir, experiment_id, error=str(exc))
        return {"status": "failed", "turns": turns_completed, "error": str(exc)}
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator/test_loop.py -v`
Expected: 7 PASSED

**Step 5: Lint and commit**

```bash
ruff check src/urika/orchestrator/loop.py tests/test_orchestrator/test_loop.py
ruff format --check src/urika/orchestrator/loop.py tests/test_orchestrator/test_loop.py
git add src/urika/orchestrator/loop.py tests/test_orchestrator/test_loop.py
git commit -m "feat: add orchestrator loop"
```

---

### Task 5: Public API Exports

**Files:**
- Modify: `src/urika/orchestrator/__init__.py`

**Step 1: Write the failing test**

Create `tests/test_orchestrator/test_public_api.py`:

```python
"""Tests for orchestrator public API."""

from __future__ import annotations


class TestOrchestratorPublicAPI:
    def test_run_experiment_importable(self) -> None:
        from urika.orchestrator import run_experiment
        assert callable(run_experiment)

    def test_parse_run_records_importable(self) -> None:
        from urika.orchestrator import parse_run_records
        assert callable(parse_run_records)

    def test_parse_evaluation_importable(self) -> None:
        from urika.orchestrator import parse_evaluation
        assert callable(parse_evaluation)

    def test_parse_suggestions_importable(self) -> None:
        from urika.orchestrator import parse_suggestions
        assert callable(parse_suggestions)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator/test_public_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_experiment'`

**Step 3: Write the implementation**

Update `src/urika/orchestrator/__init__.py`:

```python
"""Orchestrator — runs experiments by cycling through agents."""

from urika.orchestrator.loop import run_experiment
from urika.orchestrator.parsing import parse_evaluation, parse_run_records, parse_suggestions

__all__ = [
    "parse_evaluation",
    "parse_run_records",
    "parse_suggestions",
    "run_experiment",
]
```

**Step 4: Run all tests**

Run: `pytest -v`
Expected: All tests pass

**Step 5: Lint and commit**

```bash
ruff check src/urika/orchestrator/__init__.py
ruff format --check src/urika/orchestrator/__init__.py
git add src/urika/orchestrator/__init__.py tests/test_orchestrator/test_public_api.py
git commit -m "feat: add orchestrator public API exports"
```
