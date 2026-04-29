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
    """Return a copy of *agent_env* with OAuth-related vars zeroed.

    Layer 3 of the safety net. Even if a user has
    ``CLAUDE_CODE_OAUTH_TOKEN`` or ``ANTHROPIC_AUTH_TOKEN`` set in the
    parent shell, Urika must not let the spawned ``claude`` subprocess
    authenticate via OAuth. We pass an explicit empty value (not just
    absence) so the subprocess overrides any inherited parent value.

    The input mapping is **not** mutated — a fresh ``dict`` is
    returned.
    """
    out = dict(agent_env or {})
    for var in _OAUTH_TOKEN_VARS:
        out[var] = ""
    return out
