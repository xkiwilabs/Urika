# Agent Infrastructure Design

**Date**: 2026-03-06
**Status**: Approved
**Context**: Phase 3 of Urika — runtime-portable agent infrastructure with Claude Agent SDK adapter.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Architecture | Abstraction layer + swappable adapter | Urika defines its own interfaces. Claude Agent SDK is an implementation detail, swappable for custom runtime or Pi later. |
| Security model | SecurityPolicy → can_use_tool callback | Per-agent filesystem + command boundaries enforced via SDK's permission system. bypassPermissions + can_use_tool = full control. |
| Orchestration | Deterministic Python loop | Predictable, debuggable, testable. Orchestrator decides WHEN to run each agent; each agent uses LLM internally. |
| Communication | Filesystem JSON | Agents read/write JSON files at well-known paths. Simple, debuggable, resumable, no extra infrastructure. |
| Agent definition | Role modules with build_config() factories | Each agent is a module that returns an AgentConfig given project context. Prompts are markdown files. |
| Phase scope | Infrastructure + skeleton echo agent | Prove the pattern end-to-end. No real agent logic yet. |

---

## 2. Module Structure

```
src/urika/agents/
    __init__.py              # Public API exports
    config.py                # AgentConfig, SecurityPolicy, AgentRole dataclasses
    runner.py                # AgentRunner ABC + AgentResult
    registry.py              # AgentRegistry — discover/get agent definitions
    prompt.py                # Prompt loading from markdown files

    adapters/
        __init__.py
        claude_sdk.py        # ClaudeSDKRunner(AgentRunner) — the swappable adapter

    roles/                   # Agent role definitions (config + prompts)
        __init__.py
        echo.py              # Skeleton agent to prove the pattern
        prompts/
            echo_system.md   # Echo agent system prompt
```

**Key separation**: `config.py` and `runner.py` define Urika's interfaces (no SDK imports). `adapters/claude_sdk.py` is the only file that imports `claude_agent_sdk`. Everything else talks to Urika interfaces.

---

## 3. Core Interfaces

### AgentConfig

```python
@dataclass
class AgentConfig:
    """What an agent needs to run — runtime-agnostic."""
    name: str                           # e.g. "task_agent", "evaluator"
    system_prompt: str                  # The agent's full system prompt
    allowed_tools: list[str]            # Tools auto-approved (e.g. ["Read", "Write", "Bash"])
    disallowed_tools: list[str]         # Tools always denied
    security: SecurityPolicy            # Filesystem + command boundaries
    max_turns: int = 50                 # Turn limit
    model: str | None = None            # Model override (None = default)
    cwd: Path | None = None             # Working directory
```

### SecurityPolicy

```python
@dataclass
class SecurityPolicy:
    """Filesystem and command boundaries for an agent."""
    writable_dirs: list[Path]           # Dirs the agent can write to
    readable_dirs: list[Path]           # Dirs the agent can read (empty = read anything)
    allowed_bash_prefixes: list[str]    # e.g. ["python ", "pip ", "pytest "]
    blocked_bash_patterns: list[str]    # e.g. ["rm -rf", "git push"]

    def is_write_allowed(self, path: Path) -> bool:
        """Check if a file path is within any writable directory."""

    def is_bash_allowed(self, command: str) -> bool:
        """Check if a bash command is allowed by prefix rules and not blocked."""
```

### AgentRunner (ABC)

```python
class AgentRunner(ABC):
    """Run an agent and get results — implemented by adapters."""

    @abstractmethod
    async def run(self, config: AgentConfig, prompt: str) -> AgentResult:
        """Execute an agent with the given config and prompt."""
```

### AgentResult

```python
@dataclass
class AgentResult:
    """What an agent run produced."""
    success: bool                       # Did it complete without error?
    messages: list[dict]                # Raw messages from the agent
    text_output: str                    # Concatenated text output
    session_id: str                     # For resuming later
    num_turns: int
    duration_ms: int
    cost_usd: float | None = None
    error: str | None = None
```

### AgentRole

```python
@dataclass
class AgentRole:
    """Definition of an agent role — what it does and how to configure it."""
    name: str
    description: str
    build_config: Callable[..., AgentConfig]  # Factory: (project_dir, **kwargs) -> AgentConfig
```

---

## 4. Claude SDK Adapter

The adapter translates Urika's interfaces into Claude Agent SDK types.

```python
class ClaudeSDKRunner(AgentRunner):
    """Runs agents via Claude Agent SDK. Swappable for custom runtime later."""

    async def run(self, config: AgentConfig, prompt: str) -> AgentResult:
        options = self._build_options(config)
        messages = []
        async for msg in query(prompt=prompt, options=options):
            messages.append(msg)
        return self._extract_result(messages)

    def _build_options(self, config: AgentConfig) -> ClaudeAgentOptions:
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

    def _make_permission_handler(self, policy: SecurityPolicy):
        """Convert SecurityPolicy into a can_use_tool callback."""
        async def handler(tool_name, input_data, context):
            if tool_name in ("Write", "Edit"):
                path = Path(input_data.get("file_path", ""))
                if not policy.is_write_allowed(path):
                    return PermissionResultDeny(message=f"Write to {path} not allowed")
            if tool_name == "Bash":
                cmd = input_data.get("command", "")
                if not policy.is_bash_allowed(cmd):
                    return PermissionResultDeny(message=f"Command not allowed: {cmd}")
            return PermissionResultAllow(updated_input=input_data)
        return handler

    def _extract_result(self, messages) -> AgentResult:
        """Parse SDK messages into AgentResult."""
        # Extract text from AssistantMessages, find ResultMessage for metadata
```

### Swappability

To swap runtimes later:
1. Create `adapters/custom_runtime.py` implementing `AgentRunner`
2. Change which runner the orchestrator instantiates
3. Everything else (configs, security policies, roles, prompts) stays the same

---

## 5. Agent Registry

```python
class AgentRegistry:
    """Discover and retrieve agent role definitions."""

    def register(self, role: AgentRole) -> None: ...
    def get(self, name: str) -> AgentRole | None: ...
    def list_all(self) -> list[str]: ...
    def discover(self) -> None:
        """Scan roles/ package for modules with get_role() function."""
```

Uses `pkgutil.iter_modules` to scan `roles/` — same pattern as `MetricRegistry`.

---

## 6. Agent Roles

Each role is a module in `roles/` that exports `get_role()`:

```python
# roles/echo.py — skeleton agent for testing
def get_role() -> AgentRole:
    return AgentRole(
        name="echo",
        description="Skeleton agent for testing infrastructure",
        build_config=build_config,
    )

def build_config(project_dir: Path, **kwargs) -> AgentConfig:
    return AgentConfig(
        name="echo",
        system_prompt=load_prompt("echo_system.md", {"project_dir": str(project_dir)}),
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

Future real agents (task_agent, evaluator, suggestion_agent, tool_builder) follow the same pattern with different permissions, tools, and prompts.

---

## 7. Prompt Loading

```python
def load_prompt(filename: str, variables: dict[str, str] | None = None) -> str:
    """Load a markdown prompt from roles/prompts/, with variable substitution."""
```

- Prompts stored as `.md` files in `roles/prompts/`
- Variables like `{project_dir}`, `{experiment_id}` substituted at load time
- Keeps prompts readable and editable as plain markdown

---

## 8. SecurityPolicy Behaviors

### Write checking

```python
def is_write_allowed(self, path: Path) -> bool:
    resolved = path.resolve()
    return any(
        resolved == d or resolved.is_relative_to(d)
        for d in self.writable_dirs
    )
```

### Bash checking

```python
def is_bash_allowed(self, command: str) -> bool:
    cmd = command.strip()
    # Check blocked patterns first
    for pattern in self.blocked_bash_patterns:
        if pattern in cmd:
            return False
    # If no allowed prefixes, allow everything not blocked
    if not self.allowed_bash_prefixes:
        return True
    # Otherwise, must match at least one prefix
    return any(cmd.startswith(prefix) for prefix in self.allowed_bash_prefixes)
```

### Planned agent security profiles

| Agent | Writable Dirs | Allowed Bash | Notes |
|-------|--------------|-------------|-------|
| Task Agent | methods/, results/sessions/<id>/ | python, pip, pytest | Can write code and results |
| Evaluator | (none — read-only) | python (evaluation scripts) | Cannot modify methods or criteria |
| Suggestion Agent | results/suggestions/ | (none) | Writes suggestions only |
| Tool Builder | tools/ | python, pip, pytest | Creates and tests tools |

---

## 9. Integration Points

- **Orchestrator** (future phase): Uses `AgentRegistry.get()` to find roles, `role.build_config(project_dir)` to configure, `runner.run(config, prompt)` to execute
- **Evaluation framework** (existing): Evaluator gets read-only SecurityPolicy
- **Progress tracking** (existing): Agents write to `progress.json` via their tools
- **Leaderboard** (existing): Evaluator calls `update_leaderboard()` — the runner doesn't know about this

---

## 10. Future: Real Agent Roles

NOT in this phase. After infrastructure is proven with the echo agent:

1. **Task Agent** — reads investigation config, explores data, writes methods, runs experiments
2. **Evaluator** — read-only scoring, validates criteria, updates leaderboard
3. **Suggestion Agent** — analyzes results, proposes next experiments
4. **Tool Builder** — creates project-specific tools
5. **Literature Agent** — searches papers, builds knowledge base
6. **Orchestrator** — deterministic loop coordinating all of the above
