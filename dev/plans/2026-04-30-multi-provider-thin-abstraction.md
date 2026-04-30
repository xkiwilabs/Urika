# Multi-Provider Thin Abstraction — v0.4

**Status:** active (design)
**Date:** 2026-04-30
**Track:** 3
**Effort:** ~3 dev-days
**See also:** `2026-04-10-agent-runtime-abstraction-design.md`,
`2026-04-10-agent-runtime-implementation.md`,
`2026-04-24-release-polish.md` Phase 7 (LiteLLM alternative).

## Goal

Make the agent-runtime seam real enough that an external contributor
(or future-us in v0.5) can write an OpenAI / ADK / Pi adapter without
modifying core. Keep Claude as the only working provider in v0.4 — the
end-to-end second adapter is a v0.5 stretch.

## Current state — ~60% real

The scaffolding is in place: clean `AgentRunner` ABC + `AgentResult`
dataclass, factory `get_runner(backend=...)` that raises `ValueError`
with install-instructions for non-Claude, `runtime.backend` plumbed
through `RuntimeConfig`, message callback (`_make_on_message`) already
duck-typed. Three concrete things make it not yet shippable as a
contract:

1. `build_agent_env_for_endpoint` in `agents/config.py:320,327,329,332`
   writes `ANTHROPIC_*` env-var keys directly. Other adapters need
   their own keys.
2. The compliance layer (`urika.core.compliance`) is Anthropic-specific
   (Consumer Terms §3.7; scrubs `CLAUDE_CODE_*` and `ANTHROPIC_*`
   tokens) but is called from a shared layer rather than the adapter.
3. Tool-name vocabulary is Claude Code's (`Bash`, `Read`, `Write`,
   `Edit`, `Glob`, `Grep`). Other providers need a translation table or
   a capability-primitive abstraction.

Plus: `runtime.backend` is plumbed in `RuntimeConfig` but
`get_runner()` is **never called with it** from production
callsites (~7 files all call `get_runner()` with no args). The
multi-provider switch is plumbed in config but not in code.

## Changes

### 1. Move endpoint env-var construction into the adapter (~1d)

Refactor `build_agent_env_for_endpoint` to return a generic
`EndpointBinding(base_url, api_key, extra_env)`. Let
`ClaudeSDKRunner._build_options` translate that into `ANTHROPIC_*`
keys. A future `OpenAIRunner` translates the same binding to
`OPENAI_API_KEY` / `OPENAI_BASE_URL`.

### 2. Plumb `runtime.backend` everywhere `get_runner()` is called (~0.5d)

Update ~7 callsites: `orchestrator/chat.py:80`, `repl/helpers.py:78`,
`cli/agents_finalize.py:82`, `rpc/methods.py:182,308`,
`cli/run_planning.py:189,438`, `repl/main.py:225`. All currently call
`get_runner()` with no args. Should be
`get_runner(runtime_config.backend)`.

### 3. Make compliance check adapter-private (~0.25d)

`require_api_key()` should be called from `ClaudeSDKRunner.run`, not
from a shared layer. Other adapters bring their own auth check.
Already the right shape — just rename `is_anthropic_cloud_call` →
`_is_anthropic_cloud_call` and keep it adapter-private.

### 4. Add an entry-point hook for adapters (~0.25d)

`pyproject.toml`:

```toml
[project.entry-points."urika.runners"]
claude = "urika.agents.adapters.claude_sdk:ClaudeSDKRunner"
```

Then `get_runner()` looks up entry points after the explicit `claude`
short-circuit:

```python
def get_runner(backend: str = "claude") -> AgentRunner:
    if backend == "claude":
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
        return ClaudeSDKRunner()
    for ep in entry_points(group="urika.runners"):
        if ep.name == backend:
            return ep.load()()
    raise ValueError(
        f"Backend '{backend}' not installed. "
        f"Try: pip install urika[{backend}]"
    )
```

### 5. `AgentRunner` capability metadata (~0.25d)

Add classmethods to `AgentRunner`:

```python
@classmethod
def required_env(cls) -> tuple[str, ...]:
    return ()

@classmethod
def supported_tools(cls) -> frozenset[str]:
    """Canonical tool names this adapter implements."""
    return frozenset()
```

Document the canonical tool vocabulary (`Bash`, `Read`, `Write`,
`Edit`, `Glob`, `Grep`) so adapter authors know what to translate.

### 6. `docs/contributing-an-adapter.md` (~0.5d)

A one-page guide showing: (a) subclass `AgentRunner`, (b) register an
entry point, (c) translate `AgentConfig.allowed_tools` to provider
primitives, (d) handle the `EndpointBinding`.

### 7. Tests (~0.5d)

Cross-interface invariant: `get_runner(backend)` factory dispatch.
Adapter `_build_options` produces the right env keys for the
adapter's provider only. No new SDK is exercised — just the seam.

## Out of scope for v0.4

A second working adapter end-to-end. Pre-work for that:

- Most-mature non-Anthropic candidate: **OpenAI Agents SDK** (pure
  Python, no CLI subprocess, has Code Interpreter to cover the `Bash`
  gap for `task_agent`).
- Alternative path: **LiteLLM** wraps everything but loses
  agent-loop primitives (tool-use streaming protocol differs).
- Tool-vocabulary cleanup is the actual blocker for end-to-end —
  every role's system prompt explicitly references "Bash" and shell
  commands. v0.4 thin abstraction documents the canonical set; v0.5
  thick adapter translates.

Estimate for the v0.5 thick scope: ~6-7 dev-days.

## Files

- `src/urika/agents/runner.py` (factory + ABC)
- `src/urika/agents/config.py` (`build_agent_env_for_endpoint`,
  `EndpointBinding` new)
- `src/urika/agents/adapters/claude_sdk.py` (move compliance call,
  read `EndpointBinding`)
- `src/urika/core/compliance.py` (rename / scope)
- ~7 `get_runner()` callsites (see §2)
- `pyproject.toml` (entry-points + extras)
- `docs/contributing-an-adapter.md` (new)
- `tests/test_agents/test_runner.py` (factory dispatch tests)
