"""Compliance helpers for Anthropic Consumer Terms §3.7.

Urika depends on the Claude Agent SDK. Anthropic's Consumer Terms (§3.7)
and the April 2026 Agent SDK clarification prohibit using a Claude
Pro/Max subscription to authenticate the Agent SDK. Urika enforces this
via three layers of defense:

1. CLI startup warning (``cli/_base.py``) when ``ANTHROPIC_API_KEY`` is
   unset — soft, non-blocking, runs for every command.
2. Pre-spawn refusal in the SDK adapter (``require_api_key`` in this
   module) — raises :class:`APIKeyRequiredError` before any Claude Code
   subprocess is spawned for an Anthropic-cloud-bound agent.
3. OAuth env scrubbing (``scrub_oauth_env`` in this module) — zeroes
   ``CLAUDE_CODE_OAUTH_TOKEN`` and ``ANTHROPIC_AUTH_TOKEN`` in the
   environment passed to the spawned subprocess so Claude Code cannot
   silently fall back to subscription OAuth even if those vars exist in
   the parent shell.

The pre-spawn check is exempt for:

- Agents with ``ANTHROPIC_BASE_URL`` set in their env (going to a
  private inference endpoint such as Ollama, vLLM, or a self-hosted
  proxy — not Anthropic's cloud).
- Models whose name does not start with ``claude`` (a future
  multi-provider runtime would route them to a different SDK).
"""

from __future__ import annotations

import os
from typing import Mapping


_OAUTH_TOKEN_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")

# Set by Claude Code itself (CLI / VS Code extension / IDE integration)
# in any terminal it owns. The bundled `claude` CLI that the Agent SDK
# spawns refuses to launch when it detects these — "Claude Code cannot
# be launched inside another Claude Code session" → exit 1. Urika is
# spawning its own agent worker, not a nested user-interactive session,
# so we zero these in the env passed to ClaudeAgentOptions.
_NESTED_SESSION_VARS = (
    "CLAUDECODE",
    "CLAUDE_CODE_SSE_PORT",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
)


class APIKeyRequiredError(RuntimeError):
    """Raised when Urika needs an ``ANTHROPIC_API_KEY`` but none is set."""


def has_api_key(agent_env: Mapping[str, str] | None = None) -> bool:
    """Return ``True`` iff ``ANTHROPIC_API_KEY`` is available somewhere usable.

    Checks both the per-agent ``env`` overlay (which the SDK passes to
    the spawned subprocess) and the current process environment (which
    the subprocess inherits when a key is not set in the overlay).
    """
    if agent_env and agent_env.get("ANTHROPIC_API_KEY"):
        return True
    return bool(os.environ.get("ANTHROPIC_API_KEY", ""))


def is_anthropic_cloud_call(
    model: str | None, agent_env: Mapping[str, str] | None
) -> bool:
    """Return ``True`` when an agent invocation will hit api.anthropic.com.

    Returns ``False`` for:

    - Custom endpoints (``ANTHROPIC_BASE_URL`` is set in ``agent_env``)
      → going to a private inference server.
    - Models that don't start with ``claude`` → routed to a
      non-Anthropic provider (future multi-provider runtime).
    """
    env = agent_env or {}
    if env.get("ANTHROPIC_BASE_URL"):
        return False
    if model and not model.lower().startswith("claude"):
        return False
    return True


def require_api_key(
    model: str | None, agent_env: Mapping[str, str] | None
) -> None:
    """Raise :class:`APIKeyRequiredError` if a cloud-bound call has no key.

    Layer 2 of the safety net — called by the SDK adapter before each
    subprocess spawn. Layer 1 (CLI warning) is in ``cli/_base.py``.
    Layer 3 (env scrubbing) is :func:`scrub_oauth_env`.
    """
    if not is_anthropic_cloud_call(model, agent_env):
        return
    if has_api_key(agent_env):
        return
    raise APIKeyRequiredError(
        "ANTHROPIC_API_KEY is not set, and this agent is configured to "
        "call api.anthropic.com. Urika refuses to authenticate the "
        "Claude Agent SDK via a Pro/Max subscription per Anthropic's "
        "Consumer Terms §3.7 and the April 2026 Agent SDK clarification.\n"
        "\n"
        "Fix:\n"
        "  (a) Run `urika config api-key` for interactive setup, or\n"
        "      `export ANTHROPIC_API_KEY=sk-ant-...`.\n"
        "  (b) Configure a private endpoint (set ANTHROPIC_BASE_URL on\n"
        "      the agent or switch the project to mode=private)."
    )


def scrub_oauth_env(agent_env: Mapping[str, str] | None) -> dict[str, str]:
    """Return a copy of *agent_env* with parent-session leakage zeroed.

    Two classes of vars get blanked when not already set:

    1. OAuth tokens (``CLAUDE_CODE_OAUTH_TOKEN``, ``ANTHROPIC_AUTH_TOKEN``)
       — Urika must not let the spawned ``claude`` subprocess authenticate
       via a Pro/Max OAuth token leaked from the parent shell
       (Anthropic Consumer Terms §3.7).
    2. Claude Code session markers (``CLAUDECODE``, ``CLAUDE_CODE_SSE_PORT``,
       ``CLAUDE_CODE_ENTRYPOINT``, ``CLAUDE_CODE_EXECPATH``) — set when
       Urika itself is launched from a terminal owned by the Claude Code
       CLI / IDE extension. The bundled CLI the Agent SDK spawns refuses
       to launch nested when it sees these and exits 1. Urika's agents
       are workers, not user-interactive sessions, so the markers don't
       apply to them.

    Empty strings (not absence) are written so the spawned subprocess
    overrides any value it would otherwise inherit from ``os.environ``
    via the SDK's ``{**os.environ, **options.env}`` merge — but only
    when the var isn't already deliberately set in *agent_env*.

    The deliberate-set carve-out is necessary because
    ``ANTHROPIC_AUTH_TOKEN`` is the legitimate auth header for non-
    Anthropic OpenAI-compatible endpoints (vLLM / LiteLLM / OpenRouter
    expect ``Authorization: Bearer <token>``, which the bundled CLI
    sends when ``ANTHROPIC_AUTH_TOKEN`` is set). The privacy-mode
    endpoint builder in ``urika.agents.config.build_agent_env_for_endpoint``
    sets it deliberately for those endpoints; unconditionally
    blanking it here would break private-mode auth for every non-
    Anthropic endpoint with a Bearer-token auth header.

    The input mapping is **not** mutated — a fresh ``dict`` is
    returned.
    """
    out = dict(agent_env or {})
    # CLAUDE_CODE_OAUTH_TOKEN has no legitimate use in a Urika-spawned
    # subprocess — always zero it. ANTHROPIC_AUTH_TOKEN is the standard
    # Bearer-auth header for OpenAI-compatible private endpoints and
    # MUST be preserved when deliberately set; only blank it when
    # absent (to block parent-shell leakage).
    out["CLAUDE_CODE_OAUTH_TOKEN"] = ""
    out.setdefault("ANTHROPIC_AUTH_TOKEN", "")
    for var in _NESTED_SESSION_VARS:
        out[var] = ""
    return out
