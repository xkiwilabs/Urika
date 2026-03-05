# Agent Infrastructure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build Urika's runtime-portable agent infrastructure with a Claude Agent SDK adapter and a skeleton echo agent to prove the pattern.

**Architecture:** Urika defines its own interfaces (`AgentConfig`, `SecurityPolicy`, `AgentRunner`, `AgentResult`) in `src/urika/agents/`. A swappable adapter in `agents/adapters/claude_sdk.py` translates these to the Claude Agent SDK. Agent roles are modules in `agents/roles/` with `get_role()` factories. The echo agent is a skeleton that proves the full pattern end-to-end.

**Tech Stack:** Python 3.11+, `claude-agent-sdk`, pytest, ruff

**Design doc:** `docs/plans/2026-03-06-agent-infrastructure-design.md`

---

### Task 1: Package Skeleton + Dependencies

Create the directory structure and add `claude-agent-sdk` as an optional dependency.

**Files:**
- Create: `src/urika/agents/__init__.py`
- Create: `src/urika/agents/adapters/__init__.py`
- Create: `src/urika/agents/roles/__init__.py`
- Create: `src/urika/agents/roles/prompts/` (directory)
- Create: `tests/test_agents/__init__.py`
- Modify: `pyproject.toml`

**Step 1: Create package directories and empty init files**

```python
# src/urika/agents/__init__.py
"""Agent infrastructure for Urika."""
```

```python
# src/urika/agents/adapters/__init__.py
```

```python
# src/urika/agents/roles/__init__.py
```

```python
# tests/test_agents/__init__.py
```

**Step 2: Update pyproject.toml to add claude-agent-sdk as optional dependency**

Add an `agents` optional dependency group. Do NOT add it to the core dependencies — the agent infrastructure should be optional since the evaluation/core modules don't need it.

In `pyproject.toml`, add under `[project.optional-dependencies]`:

```toml
agents = [
    "claude-agent-sdk>=0.1",
]
```

**Step 3: Verify the package structure**

Run: `python -c "import urika.agents; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add src/urika/agents/ tests/test_agents/ pyproject.toml
git commit -m "feat: agent infrastructure package skeleton"
```

---

### Task 2: SecurityPolicy

Build and test the `SecurityPolicy` dataclass — filesystem and command boundary checking. This has no SDK imports.

**Files:**
- Create: `src/urika/agents/config.py`
- Create: `tests/test_agents/test_config.py`

**Step 1: Write the failing tests**

```python
# tests/test_agents/test_config.py
"""Tests for agent configuration and security policy."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import SecurityPolicy


class TestSecurityPolicyWriteAllowed:
    """Test is_write_allowed() — checks file paths against writable dirs."""

    def test_write_within_writable_dir(self, tmp_path: Path) -> None:
        writable = tmp_path / "methods"
        writable.mkdir()
        policy = SecurityPolicy(
            writable_dirs=[writable],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_write_allowed(writable / "model.py") is True

    def test_write_to_writable_dir_itself(self, tmp_path: Path) -> None:
        writable = tmp_path / "methods"
        writable.mkdir()
        policy = SecurityPolicy(
            writable_dirs=[writable],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_write_allowed(writable) is True

    def test_write_outside_writable_dir_denied(self, tmp_path: Path) -> None:
        writable = tmp_path / "methods"
        writable.mkdir()
        policy = SecurityPolicy(
            writable_dirs=[writable],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_write_allowed(tmp_path / "evaluation" / "file.py") is False

    def test_write_denied_when_no_writable_dirs(self, tmp_path: Path) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_write_allowed(tmp_path / "anything.py") is False

    def test_write_nested_subdir_allowed(self, tmp_path: Path) -> None:
        writable = tmp_path / "results"
        writable.mkdir()
        policy = SecurityPolicy(
            writable_dirs=[writable],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_write_allowed(writable / "sessions" / "001" / "progress.json") is True

    def test_multiple_writable_dirs(self, tmp_path: Path) -> None:
        methods = tmp_path / "methods"
        results = tmp_path / "results"
        methods.mkdir()
        results.mkdir()
        policy = SecurityPolicy(
            writable_dirs=[methods, results],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_write_allowed(methods / "model.py") is True
        assert policy.is_write_allowed(results / "out.json") is True
        assert policy.is_write_allowed(tmp_path / "config" / "criteria.json") is False


class TestSecurityPolicyBashAllowed:
    """Test is_bash_allowed() — checks commands against prefixes and blocked patterns."""

    def test_allowed_prefix_matches(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=["python ", "pip "],
            blocked_bash_patterns=[],
        )
        assert policy.is_bash_allowed("python script.py") is True
        assert policy.is_bash_allowed("pip install numpy") is True

    def test_disallowed_prefix_denied(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=["python "],
            blocked_bash_patterns=[],
        )
        assert policy.is_bash_allowed("rm -rf /") is False

    def test_blocked_pattern_overrides_prefix(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=["python "],
            blocked_bash_patterns=["rm -rf"],
        )
        assert policy.is_bash_allowed("rm -rf /") is False

    def test_no_prefixes_allows_all_except_blocked(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=["rm -rf", "git push"],
        )
        assert policy.is_bash_allowed("ls -la") is True
        assert policy.is_bash_allowed("rm -rf /") is False
        assert policy.is_bash_allowed("git push --force") is False

    def test_empty_policy_allows_everything(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_bash_allowed("anything") is True

    def test_command_stripped_before_check(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=["python "],
            blocked_bash_patterns=[],
        )
        assert policy.is_bash_allowed("  python script.py  ") is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'urika.agents.config'`

**Step 3: Write the implementation**

```python
# src/urika/agents/config.py
"""Agent configuration and security policy — runtime-agnostic."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class SecurityPolicy:
    """Filesystem and command boundaries for an agent.

    Determines what an agent is allowed to write and which bash commands
    it can execute. Used by the adapter layer to enforce boundaries.
    """

    writable_dirs: list[Path]
    readable_dirs: list[Path]
    allowed_bash_prefixes: list[str]
    blocked_bash_patterns: list[str]

    def is_write_allowed(self, path: Path) -> bool:
        """Check if a file path is within any writable directory."""
        resolved = path.resolve()
        return any(
            resolved == d.resolve() or _is_relative_to(resolved, d.resolve())
            for d in self.writable_dirs
        )

    def is_bash_allowed(self, command: str) -> bool:
        """Check if a bash command is allowed by prefix rules and not blocked."""
        cmd = command.strip()
        for pattern in self.blocked_bash_patterns:
            if pattern in cmd:
                return False
        if not self.allowed_bash_prefixes:
            return True
        return any(cmd.startswith(prefix) for prefix in self.allowed_bash_prefixes)


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Check if path is relative to parent (compatible helper)."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agents/test_config.py -v`
Expected: All 12 tests PASS

**Step 5: Commit**

```bash
git add src/urika/agents/config.py tests/test_agents/test_config.py
git commit -m "feat: SecurityPolicy with filesystem and command boundary checking"
```

---

### Task 3: AgentConfig, AgentRole, AgentResult

Add the remaining dataclasses to `config.py` and the runner ABC. These are Urika's runtime-agnostic interfaces.

**Files:**
- Modify: `src/urika/agents/config.py`
- Create: `src/urika/agents/runner.py`
- Modify: `tests/test_agents/test_config.py`
- Create: `tests/test_agents/test_runner.py`

**Step 1: Write the failing tests for AgentConfig and AgentRole**

Append to `tests/test_agents/test_config.py`:

```python
from urika.agents.config import AgentConfig, AgentRole


class TestAgentConfig:
    """Test the AgentConfig dataclass."""

    def test_create_with_required_fields(self, tmp_path: Path) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        config = AgentConfig(
            name="test_agent",
            system_prompt="You are a test agent.",
            allowed_tools=["Read", "Glob"],
            disallowed_tools=[],
            security=policy,
        )
        assert config.name == "test_agent"
        assert config.max_turns == 50
        assert config.model is None
        assert config.cwd is None

    def test_create_with_all_fields(self, tmp_path: Path) -> None:
        policy = SecurityPolicy(
            writable_dirs=[tmp_path],
            readable_dirs=[tmp_path],
            allowed_bash_prefixes=["python "],
            blocked_bash_patterns=[],
        )
        config = AgentConfig(
            name="worker",
            system_prompt="Work prompt",
            allowed_tools=["Read", "Write", "Bash"],
            disallowed_tools=["Edit"],
            security=policy,
            max_turns=10,
            model="sonnet",
            cwd=tmp_path,
        )
        assert config.max_turns == 10
        assert config.model == "sonnet"
        assert config.cwd == tmp_path


class TestAgentRole:
    """Test the AgentRole dataclass."""

    def test_create_role(self) -> None:
        def build(project_dir: Path, **kwargs: object) -> AgentConfig:
            return AgentConfig(
                name="test",
                system_prompt="prompt",
                allowed_tools=[],
                disallowed_tools=[],
                security=SecurityPolicy(
                    writable_dirs=[],
                    readable_dirs=[],
                    allowed_bash_prefixes=[],
                    blocked_bash_patterns=[],
                ),
            )

        role = AgentRole(
            name="test",
            description="A test role",
            build_config=build,
        )
        assert role.name == "test"
        assert role.description == "A test role"

    def test_build_config_callable(self, tmp_path: Path) -> None:
        def build(project_dir: Path, **kwargs: object) -> AgentConfig:
            return AgentConfig(
                name="worker",
                system_prompt=f"Working in {project_dir}",
                allowed_tools=["Read"],
                disallowed_tools=[],
                security=SecurityPolicy(
                    writable_dirs=[project_dir / "methods"],
                    readable_dirs=[project_dir],
                    allowed_bash_prefixes=[],
                    blocked_bash_patterns=[],
                ),
            )

        role = AgentRole(name="worker", description="Worker", build_config=build)
        config = role.build_config(tmp_path)
        assert config.name == "worker"
        assert f"{tmp_path}" in config.system_prompt
```

**Step 2: Write the failing tests for AgentRunner and AgentResult**

```python
# tests/test_agents/test_runner.py
"""Tests for AgentRunner ABC and AgentResult."""

from __future__ import annotations

import pytest

from urika.agents.runner import AgentResult, AgentRunner


class TestAgentResult:
    """Test the AgentResult dataclass."""

    def test_successful_result(self) -> None:
        result = AgentResult(
            success=True,
            messages=[{"type": "text", "content": "Hello"}],
            text_output="Hello",
            session_id="session-001",
            num_turns=3,
            duration_ms=1500,
        )
        assert result.success is True
        assert result.cost_usd is None
        assert result.error is None

    def test_failed_result(self) -> None:
        result = AgentResult(
            success=False,
            messages=[],
            text_output="",
            session_id="session-002",
            num_turns=0,
            duration_ms=100,
            error="Connection failed",
        )
        assert result.success is False
        assert result.error == "Connection failed"


class TestAgentRunnerABC:
    """Test that AgentRunner cannot be instantiated directly."""

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            AgentRunner()  # type: ignore[abstract]
```

**Step 3: Run tests to verify they fail**

Run: `pytest tests/test_agents/ -v`
Expected: FAIL — missing `AgentConfig`, `AgentRole`, `AgentRunner`, `AgentResult`

**Step 4: Add AgentConfig and AgentRole to config.py**

Append to `src/urika/agents/config.py`:

```python
@dataclass
class AgentConfig:
    """What an agent needs to run — runtime-agnostic.

    This is Urika's own interface. The adapter layer translates it
    to whatever the runtime expects (e.g. ClaudeAgentOptions).
    """

    name: str
    system_prompt: str
    allowed_tools: list[str]
    disallowed_tools: list[str]
    security: SecurityPolicy
    max_turns: int = 50
    model: str | None = None
    cwd: Path | None = None


@dataclass
class AgentRole:
    """Definition of an agent role — what it does and how to configure it.

    Each role has a build_config factory that takes project context and
    returns a fully configured AgentConfig.
    """

    name: str
    description: str
    build_config: Callable[..., AgentConfig]
```

**Step 5: Create runner.py with AgentRunner and AgentResult**

```python
# src/urika/agents/runner.py
"""Agent runner interface and result types — runtime-agnostic."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from urika.agents.config import AgentConfig


@dataclass
class AgentResult:
    """What an agent run produced."""

    success: bool
    messages: list[dict[str, Any]]
    text_output: str
    session_id: str
    num_turns: int
    duration_ms: int
    cost_usd: float | None = None
    error: str | None = None


class AgentRunner(ABC):
    """Run an agent and get results — implemented by adapters."""

    @abstractmethod
    async def run(self, config: AgentConfig, prompt: str) -> AgentResult:
        """Execute an agent with the given config and prompt."""
        ...
```

**Step 6: Run tests to verify they pass**

Run: `pytest tests/test_agents/ -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add src/urika/agents/config.py src/urika/agents/runner.py tests/test_agents/test_config.py tests/test_agents/test_runner.py
git commit -m "feat: AgentConfig, AgentRole, AgentRunner ABC, AgentResult"
```

---

### Task 4: Prompt Loading

Load markdown prompts from files with variable substitution.

**Files:**
- Create: `src/urika/agents/prompt.py`
- Create: `tests/test_agents/test_prompt.py`

**Step 1: Write the failing tests**

```python
# tests/test_agents/test_prompt.py
"""Tests for prompt loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.prompt import load_prompt


class TestLoadPrompt:
    """Test load_prompt() — loads markdown files with variable substitution."""

    def test_load_simple_prompt(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("You are a helpful assistant.")
        result = load_prompt(prompt_file)
        assert result == "You are a helpful assistant."

    def test_load_with_variables(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("Working in {project_dir} on {experiment_id}.")
        result = load_prompt(
            prompt_file, variables={"project_dir": "/tmp/proj", "experiment_id": "exp-001"}
        )
        assert result == "Working in /tmp/proj on exp-001."

    def test_load_with_no_variables_leaves_placeholders(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("Working in {project_dir}.")
        result = load_prompt(prompt_file)
        assert result == "Working in {project_dir}."

    def test_load_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_prompt(tmp_path / "nonexistent.md")

    def test_load_multiline_prompt(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("# Title\n\nParagraph one.\n\nParagraph two.\n")
        result = load_prompt(prompt_file)
        assert "# Title" in result
        assert "Paragraph two." in result

    def test_partial_variable_substitution(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("Project: {project_dir}, Mode: {mode}.")
        result = load_prompt(prompt_file, variables={"project_dir": "/tmp/proj"})
        assert result == "Project: /tmp/proj, Mode: {mode}."
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# src/urika/agents/prompt.py
"""Prompt loading from markdown files with variable substitution."""

from __future__ import annotations

import string
from pathlib import Path


def load_prompt(
    path: Path,
    variables: dict[str, str] | None = None,
) -> str:
    """Load a markdown prompt file, optionally substituting variables.

    Variables use Python's {name} format. Unmatched placeholders are
    left as-is (safe partial substitution).

    Args:
        path: Path to the .md prompt file.
        variables: Optional dict of {name: value} substitutions.

    Returns:
        The prompt text with variables substituted.

    Raises:
        FileNotFoundError: If the prompt file doesn't exist.
    """
    if not path.exists():
        msg = f"Prompt file not found: {path}"
        raise FileNotFoundError(msg)

    text = path.read_text()

    if variables:
        template = string.Template(text)
        # Use safe_substitute-style approach with str.format_map
        text = text.format_map(_SafeDict(variables))

    return text


class _SafeDict(dict):  # type: ignore[type-arg]
    """Dict that returns the key as {key} for missing keys."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agents/test_prompt.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add src/urika/agents/prompt.py tests/test_agents/test_prompt.py
git commit -m "feat: prompt loading with safe variable substitution"
```

---

### Task 5: Agent Registry

Auto-discover agent roles from `roles/` submodules — same pattern as `MetricRegistry`.

**Files:**
- Create: `src/urika/agents/registry.py`
- Create: `tests/test_agents/test_registry.py`

**Step 1: Write the failing tests**

```python
# tests/test_agents/test_registry.py
"""Tests for AgentRegistry."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.registry import AgentRegistry


def _make_role(name: str) -> AgentRole:
    """Helper to create a simple AgentRole for testing."""

    def build(project_dir: Path, **kwargs: object) -> AgentConfig:
        return AgentConfig(
            name=name,
            system_prompt=f"You are {name}.",
            allowed_tools=[],
            disallowed_tools=[],
            security=SecurityPolicy(
                writable_dirs=[],
                readable_dirs=[],
                allowed_bash_prefixes=[],
                blocked_bash_patterns=[],
            ),
        )

    return AgentRole(name=name, description=f"{name} agent", build_config=build)


class TestAgentRegistry:
    """Test the AgentRegistry."""

    def test_register_and_get(self) -> None:
        registry = AgentRegistry()
        role = _make_role("worker")
        registry.register(role)
        assert registry.get("worker") is role

    def test_get_nonexistent_returns_none(self) -> None:
        registry = AgentRegistry()
        assert registry.get("nonexistent") is None

    def test_list_all_sorted(self) -> None:
        registry = AgentRegistry()
        registry.register(_make_role("worker"))
        registry.register(_make_role("evaluator"))
        assert registry.list_all() == ["evaluator", "worker"]

    def test_list_all_empty(self) -> None:
        registry = AgentRegistry()
        assert registry.list_all() == []

    def test_discover_finds_echo_role(self) -> None:
        """discover() should find the echo agent in roles/."""
        registry = AgentRegistry()
        registry.discover()
        names = registry.list_all()
        assert "echo" in names

    def test_register_overwrites_same_name(self) -> None:
        registry = AgentRegistry()
        role1 = _make_role("agent")
        role2 = _make_role("agent")
        registry.register(role1)
        registry.register(role2)
        assert registry.get("agent") is role2
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError`

Note: `test_discover_finds_echo_role` will fail until Task 6 (echo agent) is complete. That's expected — it will be verified after Task 6.

**Step 3: Write the implementation**

```python
# src/urika/agents/registry.py
"""Agent registry with auto-discovery."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from urika.agents.config import AgentRole


class AgentRegistry:
    """Registry for agent role definitions with auto-discovery."""

    def __init__(self) -> None:
        self._roles: dict[str, AgentRole] = {}

    def register(self, role: AgentRole) -> None:
        """Register an agent role by its name."""
        self._roles[role.name] = role

    def get(self, name: str) -> AgentRole | None:
        """Get a role by name, or None if not found."""
        return self._roles.get(name)

    def list_all(self) -> list[str]:
        """Return a sorted list of all registered role names."""
        return sorted(self._roles.keys())

    def discover(self) -> None:
        """Auto-discover agent roles from roles/ submodules.

        Scans the urika.agents.roles package for modules that have a
        get_role() function returning an AgentRole.
        """
        import urika.agents.roles as roles_pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(roles_pkg.__path__):
            module = importlib.import_module(f"urika.agents.roles.{modname}")
            get_role = getattr(module, "get_role", None)
            if callable(get_role):
                role = get_role()
                if isinstance(role, AgentRole):
                    self._roles[role.name] = role
```

**Step 4: Run tests (expect most to pass, one may fail pending echo agent)**

Run: `pytest tests/test_agents/test_registry.py -v -k "not discover_finds_echo"`
Expected: 5 of 5 selected tests PASS

**Step 5: Commit**

```bash
git add src/urika/agents/registry.py tests/test_agents/test_registry.py
git commit -m "feat: AgentRegistry with auto-discovery of roles"
```

---

### Task 6: Echo Agent Role + Prompt

Create the skeleton echo agent that proves the full pattern: registry discovers it, `build_config()` returns an AgentConfig, prompt is loaded from markdown.

**Files:**
- Create: `src/urika/agents/roles/echo.py`
- Create: `src/urika/agents/roles/prompts/echo_system.md`
- Create: `tests/test_agents/test_echo_role.py`

**Step 1: Write the failing tests**

```python
# tests/test_agents/test_echo_role.py
"""Tests for the echo agent role."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.registry import AgentRegistry
from urika.agents.roles.echo import get_role


class TestEchoRole:
    """Test the echo skeleton agent."""

    def test_get_role_returns_agent_role(self) -> None:
        role = get_role()
        assert isinstance(role, AgentRole)
        assert role.name == "echo"

    def test_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert isinstance(config, AgentConfig)
        assert config.name == "echo"

    def test_config_has_read_only_tools(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert "Read" in config.allowed_tools
        assert "Glob" in config.allowed_tools
        assert "Grep" in config.allowed_tools
        assert "Write" not in config.allowed_tools
        assert "Bash" not in config.allowed_tools

    def test_config_security_is_read_only(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert config.security.writable_dirs == []

    def test_config_has_system_prompt(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert len(config.system_prompt) > 0
        assert "echo" in config.system_prompt.lower()

    def test_config_prompt_includes_project_dir(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert str(tmp_path) in config.system_prompt

    def test_config_max_turns_is_low(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert config.max_turns <= 10

    def test_discoverable_by_registry(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        assert "echo" in registry.list_all()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_echo_role.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Create the echo system prompt**

```markdown
# Echo Agent

You are a skeleton test agent for the Urika platform. Your purpose is to verify that the agent infrastructure works correctly.

**Project directory:** {project_dir}

## Instructions

1. Read the project directory to understand its structure
2. Report what you found in a brief summary
3. Do NOT modify any files — you are read-only

You are a simple echo agent for testing. Report what you see and stop.
```

Save to: `src/urika/agents/roles/prompts/echo_system.md`

**Step 4: Create the echo role module**

```python
# src/urika/agents/roles/echo.py
"""Echo agent — skeleton role for testing the agent infrastructure."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.prompt import load_prompt

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    """Return the echo agent role definition."""
    return AgentRole(
        name="echo",
        description="Skeleton agent for testing infrastructure",
        build_config=build_config,
    )


def build_config(project_dir: Path, **kwargs: object) -> AgentConfig:
    """Build an AgentConfig for the echo agent."""
    return AgentConfig(
        name="echo",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "echo_system.md",
            variables={"project_dir": str(project_dir)},
        ),
        allowed_tools=["Read", "Glob", "Grep"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        ),
        max_turns=5,
    )
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_agents/test_echo_role.py -v`
Expected: All 8 tests PASS

**Step 6: Also run the registry discover test that was waiting for this**

Run: `pytest tests/test_agents/test_registry.py::TestAgentRegistry::test_discover_finds_echo_role -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/urika/agents/roles/echo.py src/urika/agents/roles/prompts/echo_system.md tests/test_agents/test_echo_role.py
git commit -m "feat: echo skeleton agent — proves role + registry + prompt pattern"
```

---

### Task 7: Claude SDK Adapter

Build `ClaudeSDKRunner` — translates Urika interfaces to Claude Agent SDK. Since the SDK requires a running Claude Code process, unit tests mock the SDK calls.

**Files:**
- Create: `src/urika/agents/adapters/claude_sdk.py`
- Create: `tests/test_agents/test_claude_sdk_adapter.py`

**Step 1: Write the failing tests**

```python
# tests/test_agents/test_claude_sdk_adapter.py
"""Tests for the Claude Agent SDK adapter.

These tests verify the translation logic without requiring a running
Claude Code instance. SDK calls are mocked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
from urika.agents.config import AgentConfig, SecurityPolicy
from urika.agents.runner import AgentResult


@pytest.fixture
def read_only_config(tmp_path: Path) -> AgentConfig:
    """A read-only agent config for testing."""
    return AgentConfig(
        name="test_agent",
        system_prompt="You are a test agent.",
        allowed_tools=["Read", "Glob"],
        disallowed_tools=["Bash"],
        security=SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[tmp_path],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        ),
        max_turns=5,
        cwd=tmp_path,
    )


@pytest.fixture
def writer_config(tmp_path: Path) -> AgentConfig:
    """A config that allows writing to a specific directory."""
    writable = tmp_path / "methods"
    writable.mkdir()
    return AgentConfig(
        name="writer_agent",
        system_prompt="You can write.",
        allowed_tools=["Read", "Write", "Bash"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[writable],
            readable_dirs=[tmp_path],
            allowed_bash_prefixes=["python "],
            blocked_bash_patterns=["rm -rf"],
        ),
        max_turns=10,
        cwd=tmp_path,
    )


class TestClaudeSDKRunnerBuildOptions:
    """Test that _build_options correctly translates AgentConfig."""

    def test_maps_basic_fields(self, read_only_config: AgentConfig) -> None:
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.system_prompt == "You are a test agent."
        assert options.allowed_tools == ["Read", "Glob"]
        assert options.disallowed_tools == ["Bash"]
        assert options.max_turns == 5
        assert options.permission_mode == "bypassPermissions"

    def test_maps_cwd(self, read_only_config: AgentConfig, tmp_path: Path) -> None:
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.cwd == str(tmp_path)

    def test_maps_model(self, read_only_config: AgentConfig) -> None:
        read_only_config.model = "sonnet"
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.model == "sonnet"

    def test_none_cwd_when_not_set(self, read_only_config: AgentConfig) -> None:
        read_only_config.cwd = None
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.cwd is None

    def test_has_can_use_tool(self, read_only_config: AgentConfig) -> None:
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.can_use_tool is not None


class TestClaudeSDKRunnerPermissionHandler:
    """Test the SecurityPolicy → can_use_tool translation."""

    @pytest.mark.asyncio
    async def test_read_only_denies_write(
        self, read_only_config: AgentConfig, tmp_path: Path
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(read_only_config.security)
        result = await handler(
            "Write", {"file_path": str(tmp_path / "evil.py")}, None
        )
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_writer_allows_write_in_writable_dir(
        self, writer_config: AgentConfig, tmp_path: Path
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(writer_config.security)
        result = await handler(
            "Write",
            {"file_path": str(tmp_path / "methods" / "model.py")},
            None,
        )
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_writer_denies_write_outside_writable(
        self, writer_config: AgentConfig, tmp_path: Path
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(writer_config.security)
        result = await handler(
            "Write",
            {"file_path": str(tmp_path / "evaluation" / "file.py")},
            None,
        )
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_bash_allowed_by_prefix(
        self, writer_config: AgentConfig
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(writer_config.security)
        result = await handler("Bash", {"command": "python script.py"}, None)
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_bash_denied_by_blocked_pattern(
        self, writer_config: AgentConfig
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(writer_config.security)
        result = await handler("Bash", {"command": "rm -rf /"}, None)
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_bash_denied_by_prefix_mismatch(
        self, writer_config: AgentConfig
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(writer_config.security)
        result = await handler("Bash", {"command": "curl evil.com"}, None)
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_read_tool_always_allowed(
        self, read_only_config: AgentConfig
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(read_only_config.security)
        result = await handler("Read", {"file_path": "/any/path"}, None)
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_edit_checked_like_write(
        self, read_only_config: AgentConfig, tmp_path: Path
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(read_only_config.security)
        result = await handler(
            "Edit", {"file_path": str(tmp_path / "file.py")}, None
        )
        assert result.behavior == "deny"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_claude_sdk_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Install test dependency**

Run: `pip install pytest-asyncio`

Also add to `pyproject.toml` dev dependencies:

```toml
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.1",
]
```

**Step 4: Write the implementation**

```python
# src/urika/agents/adapters/claude_sdk.py
"""Claude Agent SDK adapter — translates Urika interfaces to SDK types.

This is the only module that imports claude_agent_sdk. Swap this adapter
to change the runtime (e.g. custom runtime, Pi SDK).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

from urika.agents.config import AgentConfig, SecurityPolicy
from urika.agents.runner import AgentResult, AgentRunner


class ClaudeSDKRunner(AgentRunner):
    """Runs agents via Claude Agent SDK."""

    async def run(self, config: AgentConfig, prompt: str) -> AgentResult:
        """Execute an agent and return structured results."""
        options = self._build_options(config)
        messages: list[dict[str, Any]] = []
        text_parts: list[str] = []
        session_id = ""
        num_turns = 0
        duration_ms = 0
        cost_usd: float | None = None
        is_error = False

        async for msg in query(prompt=prompt, options=options):
            messages.append(_message_to_dict(msg))
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                session_id = msg.session_id
                num_turns = msg.num_turns
                duration_ms = msg.duration_ms
                cost_usd = msg.total_cost_usd
                is_error = msg.is_error

        return AgentResult(
            success=not is_error,
            messages=messages,
            text_output="\n".join(text_parts),
            session_id=session_id,
            num_turns=num_turns,
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            error="Agent reported error" if is_error else None,
        )

    def _build_options(self, config: AgentConfig) -> ClaudeAgentOptions:
        """Translate AgentConfig to ClaudeAgentOptions."""
        return ClaudeAgentOptions(
            system_prompt=config.system_prompt,
            allowed_tools=config.allowed_tools,
            disallowed_tools=config.disallowed_tools,
            can_use_tool=self._make_permission_handler(config.security),
            max_turns=config.max_turns,
            model=config.model,
            cwd=str(config.cwd) if config.cwd else None,
            permission_mode="bypassPermissions",
        )

    def _make_permission_handler(self, policy: SecurityPolicy) -> Any:
        """Convert SecurityPolicy into a can_use_tool callback."""

        async def handler(
            tool_name: str, input_data: dict[str, Any], context: Any
        ) -> PermissionResultAllow | PermissionResultDeny:
            if tool_name in ("Write", "Edit"):
                file_path = input_data.get("file_path", "")
                if file_path and not policy.is_write_allowed(Path(file_path)):
                    return PermissionResultDeny(
                        message=f"Write to {file_path} not allowed by security policy"
                    )
            if tool_name == "Bash":
                cmd = input_data.get("command", "")
                if cmd and not policy.is_bash_allowed(cmd):
                    return PermissionResultDeny(
                        message=f"Command not allowed by security policy: {cmd}"
                    )
            return PermissionResultAllow(updated_input=input_data)

        return handler


def _message_to_dict(msg: Any) -> dict[str, Any]:
    """Convert an SDK message to a plain dict for storage."""
    if isinstance(msg, ResultMessage):
        return {
            "type": "result",
            "session_id": msg.session_id,
            "num_turns": msg.num_turns,
            "duration_ms": msg.duration_ms,
            "is_error": msg.is_error,
            "cost_usd": msg.total_cost_usd,
        }
    if isinstance(msg, AssistantMessage):
        content = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                content.append({"type": "text", "text": block.text})
            else:
                content.append({"type": "unknown"})
        return {"type": "assistant", "content": content, "model": msg.model}
    return {"type": "other", "raw": str(msg)}
```

**Step 5: Run tests**

Run: `pytest tests/test_agents/test_claude_sdk_adapter.py -v`
Expected: All tests PASS (the permission handler tests don't need a running Claude process — they test the callback directly)

Note: If `claude-agent-sdk` is not installed, the import will fail. Install it first:
Run: `pip install claude-agent-sdk`

**Step 6: Commit**

```bash
git add src/urika/agents/adapters/claude_sdk.py tests/test_agents/test_claude_sdk_adapter.py pyproject.toml
git commit -m "feat: Claude Agent SDK adapter with SecurityPolicy enforcement"
```

---

### Task 8: Public API Exports + Full Test Suite Verification

Wire up `__init__.py` exports and verify the full test suite.

**Files:**
- Modify: `src/urika/agents/__init__.py`

**Step 1: Update the public API exports**

```python
# src/urika/agents/__init__.py
"""Agent infrastructure for Urika.

Core interfaces (runtime-agnostic):
    AgentConfig, SecurityPolicy, AgentRole — agent configuration
    AgentRunner, AgentResult — agent execution

Adapters (swappable runtimes):
    ClaudeSDKRunner — Claude Agent SDK adapter

Registry:
    AgentRegistry — discover and retrieve agent roles
"""

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.prompt import load_prompt
from urika.agents.registry import AgentRegistry
from urika.agents.runner import AgentResult, AgentRunner

__all__ = [
    "AgentConfig",
    "AgentResult",
    "AgentRole",
    "AgentRegistry",
    "AgentRunner",
    "SecurityPolicy",
    "load_prompt",
]
```

Note: `ClaudeSDKRunner` is intentionally NOT in `__all__` — it's an implementation detail imported explicitly when needed.

**Step 2: Run the full test suite**

Run: `pytest -v`
Expected: All tests PASS (132 existing + new agent tests)

**Step 3: Run linting**

Run: `ruff check src/ tests/`
Expected: No errors

Run: `ruff format src/ tests/`
Expected: Files formatted or already clean

**Step 4: Commit**

```bash
git add src/urika/agents/__init__.py
git commit -m "feat: agent infrastructure public API + verify all tests pass"
```
