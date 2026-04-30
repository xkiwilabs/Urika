# Contributing an Agent Runtime Adapter

Urika ships with one agent backend (Anthropic's Claude Agent SDK)
but the runtime is structured around a provider-agnostic
``AgentRunner`` ABC. To add another backend (OpenAI Agents SDK,
Google ADK, Pi, LiteLLM, your own internal LLM gateway), implement
``AgentRunner`` and register it via Python entry points. No core
changes required.

## 1. Subclass `AgentRunner`

```python
from typing import Any, Callable

from urika.agents.runner import AgentRunner, AgentResult
from urika.agents.config import AgentConfig


class OpenAIRunner(AgentRunner):
    @classmethod
    def required_env(cls) -> tuple[str, ...]:
        return ("OPENAI_API_KEY",)

    @classmethod
    def supported_tools(cls) -> frozenset[str]:
        # Translate Urika's canonical tool vocabulary into your
        # provider's primitives. See "Tool vocabulary" below.
        return frozenset({"Read", "Write", "Edit", "Glob", "Grep"})

    async def run(
        self,
        config: AgentConfig,
        prompt: str,
        *,
        on_message: Callable[..., Any] | None = None,
    ) -> AgentResult:
        # Translate AgentConfig into your provider's options shape,
        # stream messages back, accumulate cost / tokens, return
        # AgentResult.
        ...
```

## 2. Register the entry point

In your package's `pyproject.toml`:

```toml
[project.entry-points."urika.runners"]
openai = "my_pkg.runners:OpenAIRunner"
```

Once installed (`pip install my-urika-openai-adapter`),
`urika config` and `get_runner("openai")` will see your runner
automatically.

## 3. Tool vocabulary

Urika's agent prompts reference these canonical tool names:

| Name | Semantic |
|---|---|
| `Read` | Read a file from disk; returns text content |
| `Write` | Write a new file from disk |
| `Edit` | Surgical edit of an existing file (find/replace, line edit) |
| `MultiEdit` | Batch of edits applied atomically |
| `NotebookEdit` | Edit a Jupyter notebook by cell |
| `Glob` | Match a glob pattern under a directory |
| `Grep` | Regex / literal search across files |
| `Bash` | Execute a shell command (subject to SecurityPolicy) |
| `WebFetch` | Fetch a URL |
| `WebSearch` | Search the web |

Your adapter should map these to your provider's tool primitives.
Unsupported tools should be either:

- Translated to a closest equivalent (e.g. "Bash" → OpenAI Code
  Interpreter), or
- Omitted from `supported_tools()` so callers can choose a
  different backend for roles that need them.

## 4. SecurityPolicy enforcement

`AgentConfig.security` carries the agent role's
`writable_dirs` / `readable_dirs` / `allowed_bash_prefixes` /
`blocked_bash_patterns`. Your adapter is responsible for enforcing
these — typically by wiring a permission callback into your SDK's
equivalent of Claude's `can_use_tool`. The reference
implementation lives in `urika/agents/permission.py`; reuse the
`_decide` pure function:

```python
from urika.agents.permission import _decide

allow, reason = _decide(tool_name, tool_input, config.security, config.cwd)
```

If your provider doesn't have a permission callback at all, you
must enforce in your tool dispatcher.

## 5. Endpoint binding

`AgentConfig.env` carries Urika's privacy / hybrid-mode endpoint
overrides. Look for the keys your provider recognises
(`OPENAI_BASE_URL`, `OPENAI_API_KEY`, etc.). The Claude adapter
uses `ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY` and scrubs
OAuth/session-marker vars via `urika.core.compliance.scrub_oauth_env`
— other providers can ignore that scrub helper but should apply
their own equivalent (zero out any OAuth-style envs that could
let the SDK auth via subscription instead of the metered API).

## 6. Cost / token accounting

Set `AgentResult.tokens_in`, `tokens_out`, `cost_usd`, and
`model`. Urika's `core.usage` aggregates these per-project.
Multi-`ResultMessage` streams should accumulate (not overwrite) —
the reference Claude adapter at
`urika/agents/adapters/claude_sdk.py` shows the pattern, including
how to handle cache-token fields when present.

## 7. Error categories

Set `AgentResult.error_category` to one of: `"rate_limit"`,
`"auth"`, `"billing"`, `"transient"`, `"config"`, or `""`. The
orchestrator loop's `_PAUSABLE_ERRORS` set treats `rate_limit` /
`billing` / `transient` / `config` as resumable; others fail the
experiment.

The reference classifier `urika.agents.adapters.claude_sdk._classify_error`
shows the regex patterns; adapt for your provider's error strings.

## 8. Testing

Mirror `tests/test_agents/test_claude_sdk_adapter.py`:

- `_build_options` (or your equivalent) maps `AgentConfig` fields
  correctly.
- Token / cost accumulation across multi-`ResultMessage` streams.
- Error classification round-trip through `_classify_error`.
- Permission callback integrates with the SDK.

Plus an integration-style test that exercises the actual SDK with
a mocked transport (record-replay or HTTP fixture).

## 9. Wire into the CLI / dashboard

Once the adapter is registered:

- The CLI wizard (`urika config`) and the dashboard's Models tab
  surface it as a backend option.
- Per-project / per-mode `[runtime].backend` setting selects it.
- Future: per-agent backend overrides (`runtime.modes.<mode>.models.<agent>.backend`)
  — landing in v0.5 once a second adapter actually ships.

## Reference

- `src/urika/agents/runner.py` — ABC + factory
- `src/urika/agents/config.py` — `AgentConfig`, `SecurityPolicy`
- `src/urika/agents/adapters/claude_sdk.py` — reference implementation
- `src/urika/agents/permission.py` — permission decisions
- `src/urika/core/compliance.py` — OAuth / session env scrubbing
  (Anthropic-specific; other providers bring their own)
