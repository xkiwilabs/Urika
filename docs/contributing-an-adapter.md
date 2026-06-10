# Contributing an Agent Runtime Adapter

Urika ships three agent backends as of v0.7.0 — Anthropic's
**Claude Agent SDK**, the **OpenAI Agents SDK**, and Google's
**Agent Development Kit (ADK)** — and the runtime is structured
around a provider-agnostic ``AgentRunner`` ABC. To add another
backend (Pi, LiteLLM-as-a-target, your own internal LLM gateway,
a not-yet-supported provider), implement ``AgentRunner`` and
register it through the model-prefix router. No core changes
required.

**Worked examples.** The three first-party adapters live at
``src/urika/agents/adapters/``:

- ``claude_sdk.py`` — the original reference adapter. Uses the
  Claude Agent SDK's native tool surface, ``can_use_tool``
  permission callback, and ANTHROPIC_*  env vars.
- ``openai_agents.py`` — wires the shared
  ``urika.agents.tools`` layer (Bash / Read / Write / Grep / Glob /
  Edit) into the OpenAI Agents SDK's tool registry and calls
  ``urika.agents.pricing.cost_for()`` for per-call cost.
- ``google_adk.py`` — same shape against Google's ADK.

If you're writing a new third-party adapter, ``openai_agents.py``
and ``google_adk.py`` are the better templates — they reuse the
shared tool layer (so you don't re-implement Bash + filesystem
security) and the shared pricing table (so the leaderboard /
``urika usage`` / dashboard usage page show your provider's
numbers in the same shape as Anthropic / OpenAI / Google).

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

## 2. Wire into the model-prefix router

As of v0.7.0, Urika routes by **model prefix**, not by a
per-project provider setting. ``urika.agents.runner_registry.runner_for(model)``
inspects the model string and returns the matching adapter
instance:

```python
# src/urika/agents/runner_registry.py (excerpt)
def runner_for(model: str) -> AgentRunner:
    if model.startswith("claude-"):
        return ClaudeSDKRunner()
    if model.startswith(("gpt-", "o3", "o4", "o5")):
        return OpenAIAgentsRunner()
    if model.startswith("gemini-"):
        return GoogleADKRunner()
    raise UnknownModelError(f"no adapter for model {model!r}")
```

To register a new adapter, pick a model-name prefix nobody else
uses (``pi-``, ``mistral-``, ``llama-``, ...) and add a clause to
``runner_for``. Lazy-import your adapter module inside the clause
so an uninstalled optional dependency doesn't break collection
for users who don't need it (see how ``OpenAIAgentsRunner`` and
``GoogleADKRunner`` are imported lazily today).

For a fully out-of-tree adapter — one shipped in a separate
``pip install``-able package — the recommended pattern is to
monkeypatch ``runner_for`` from your package's import-time setup,
or contribute the prefix clause upstream. There is no entry-point
auto-discovery as of v0.7.0; upstream contribution is preferred
because the prefix space is small and conflicts would be
silent.

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

### Reuse the shared tools layer (recommended)

As of v0.7.0, ``urika.agents.tools`` ships **provider-agnostic**
implementations of six of the canonical tools (Bash / Read /
Write / Grep / Glob / Edit), each pre-wired to the existing
``SecurityPolicy`` enforcement. The OpenAI and Google adapters
both consume this layer instead of re-implementing tool
semantics per provider:

```python
from urika.agents.tools import (
    bash_tool,    # subject to SecurityPolicy.allowed_bash_prefixes
    read_tool,    # subject to SecurityPolicy.readable_dirs
    write_tool,   # subject to SecurityPolicy.writable_dirs
    grep_tool,
    glob_tool,
    edit_tool,
)
```

Each tool exposes a ``call(config: AgentConfig, **kwargs) ->
ToolResult`` async function with the canonical ``ToolResult``
shape (``ok`` / ``output`` / ``error`` / ``exit_code``). All
permission checks happen inside the tool — your adapter just
registers the wrapper with the provider's tool registry and the
SecurityPolicy enforcement is automatic. See
``openai_agents.OpenAIAgentsRunner._build_tools`` for the
worked pattern.

You only need to reach for the ``permission._decide`` pure
function (section 4) if your provider has its own tool
implementations and you're wrapping them with a permission
callback rather than substituting the shared tool wrappers.

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
OAuth/session-marker vars via `urika.core.compliance.scrub_oauth_env`.
If your adapter's function tools spawn local subprocesses (a Bash
tool), build their environment with
`urika.core.compliance.scrub_oauth_env_for_subprocess(config.env)` —
see the shared-plumbing section below.

## 6. Cost / token accounting

Set `AgentResult.tokens_in`, `tokens_out`, `cost_usd`, and
`model`. Urika's `core.usage` aggregates these per-project.
Multi-`ResultMessage` streams should accumulate (not overwrite) —
the reference Claude adapter at
`urika/agents/adapters/claude_sdk.py` shows the pattern, including
how to handle cache-token fields when present.

Use ``urika.agents.pricing.cost_for(model, tokens_in, tokens_out)``
for the per-call dollar cost — this is the single source of truth
that all first-party adapters share, and is what the leaderboard
/ ``urika usage`` / dashboard usage page read. Add your model
rates to ``PRICES`` in ``src/urika/agents/pricing.py`` (rates are
``$/1M tokens`` as a ``(input_rate, output_rate)`` tuple). Models
absent from the table return ``0.0``, which is the right thing
for free local-endpoint usage but the wrong thing for a paid
provider you forgot to register.

For subscription-mode auth (no per-call $ cost) — see how the
Anthropic adapter handles the ``[anthropic] auth = "subscription"``
toggle. ``cost_usd`` is set to ``0.0`` and an
``AgentResult.usage["mode"] = "subscription"`` annotation lets
the usage page render "credits used" instead of "$0.00 (looks
broken)".

## 7. Error categories

Set `AgentResult.error_category` to one of: `"rate_limit"`,
`"auth"`, `"billing"`, `"transient"`, `"config"`, or `""`. The
orchestrator loop's `_PAUSABLE_ERRORS` set treats `rate_limit` /
`billing` / `transient` / `config` as resumable; others fail the
experiment.

Use the shared classifier — don't write your own regexes:

```python
from urika.agents.error_classify import classify_error

error_category = classify_error(str(exc))
```

`classify_error` returns one of `"rate_limit"`, `"auth"`,
`"billing"`, `"transient"`, `"config"`, or `"unknown"` (extracted
verbatim from the Claude adapter in v0.8.0 so all adapters classify
identically). If your provider has error strings the shared patterns
miss, extend `src/urika/agents/error_classify.py` rather than
forking the logic per adapter.

## 8. Shared plumbing: timeouts and env hygiene

Three shared contracts keep adapter behavior uniform; new adapters
must use them rather than inventing their own knobs.
`src/urika/agents/adapters/openai_agents.py` is the reference
implementation for all three.

**Stream timeout** — wrap your SDK's streaming iteration so a hung
stream fails as `transient` instead of blocking the orchestrator
forever:

```python
from urika.agents.adapters._common import agent_stream_timeout

timeout = agent_stream_timeout()  # seconds of allowed stream silence
```

The value is read at call time from the `URIKA_AGENT_STREAM_TIMEOUT`
env var (default `600`; an invalid value silently falls back to 600
so a bad setting can't crash the adapter at runtime).

**Bash tool timeout** — if your adapter wires the shared Bash tool
(or its own equivalent), cap each command with:

```python
from urika.agents.adapters._common import bash_timeout_seconds

timeout = bash_timeout_seconds(config.max_method_seconds)  # cap, else 600
```

This is how the project's `max_method_seconds` setting reaches your
provider's execution loop.

**Subprocess env hygiene** — any function tool that spawns a local
subprocess must build its environment with:

```python
from urika.core.compliance import scrub_oauth_env_for_subprocess

env = scrub_oauth_env_for_subprocess(config.env)
```

This overlays `os.environ` with the agent's env and scrubs
OAuth-token and Claude-Code-session-marker vars per the user's
Anthropic auth mode (billing hygiene in `api_key` mode; the token
family is preserved in `subscription` mode). Using the shared helper
means the merge semantics can't drift between adapters.

## 9. Testing

Mirror `tests/test_agents/test_claude_sdk_adapter.py`:

- `_build_options` (or your equivalent) maps `AgentConfig` fields
  correctly.
- Token / cost accumulation across multi-`ResultMessage` streams.
- Error classification round-trip through `classify_error`.
- Permission callback integrates with the SDK.

Plus an integration-style test that exercises the actual SDK with
a mocked transport (record-replay or HTTP fixture), AND a
real-imports structural test that imports the actual SDK (no mocks)
and pins the attribute/signature surface your adapter relies on —
see `tests/test_agents/test_openai_agents_real_imports.py`. Mock-based
unit tests can't catch SDK signature drift; the v0.7.0 smoke
iterations caught several such bugs post-merge that a structural
test would have failed in CI.

## 10. Wire into the CLI / dashboard

Once the adapter is wired into ``runner_for()``:

- ``urika config <provider> --mode <api_key|subscription>`` is the
  per-provider auth-setup surface. See ``urika config anthropic``,
  ``urika config openai``, and ``urika config google`` for the
  existing three.
- The dashboard's Models tab Provider filter surfaces the new
  provider once ``recommended_models_for(<provider>)`` returns a
  ``{"reasoning": ..., "execution": ...}`` pair. Add the row to
  ``_RECOMMENDED_BY_PROVIDER`` in
  ``src/urika/core/recommended_models.py``.
- Per-project per-agent model overrides in ``[runtime.models]``
  route automatically — the orchestrator calls ``runner_for(model)``
  on each agent invocation, so as long as your prefix clause is
  registered, the existing config schema picks up your provider
  with zero changes.

## Reference

- `src/urika/agents/runner.py` — ABC
- `src/urika/agents/runner_registry.py` — `runner_for()` model-prefix routing
- `src/urika/agents/config.py` — `AgentConfig`, `SecurityPolicy`
- `src/urika/agents/tools/` — shared Bash / Read / Write / Grep / Glob / Edit layer
- `src/urika/agents/pricing.py` — shared `cost_for()` + `PRICES` table
- `src/urika/agents/error_classify.py` — shared `classify_error()` categories
- `src/urika/agents/adapters/_common.py` — shared `agent_stream_timeout()` + `bash_timeout_seconds()`
- `src/urika/agents/adapters/claude_sdk.py` — Anthropic reference adapter
- `src/urika/agents/adapters/openai_agents.py` — OpenAI reference adapter
- `src/urika/agents/adapters/google_adk.py` — Google reference adapter
- `src/urika/agents/permission.py` — permission decisions
- `src/urika/core/recommended_models.py` — per-provider recommended defaults
- `src/urika/core/compliance.py` — OAuth / session env scrubbing,
  incl. `scrub_oauth_env_for_subprocess()` for bash-spawning tools
