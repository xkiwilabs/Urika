"""Compliance and auth-hygiene helpers for Urika's Anthropic adapter.

Urika depends on the Claude Agent SDK and supports two Anthropic auth
modes (configured via ``[anthropic] auth`` in ``~/.urika/settings.toml``
or ``urika config anthropic --mode ...``):

* ``api_key`` (default) — Urika calls ``api.anthropic.com`` using a
  standard ``ANTHROPIC_API_KEY``.  This is the original mode and stays
  the default so existing users are never silently upgraded.
* ``subscription`` — opt-in since June 15 2026, when Anthropic's
  billing overhaul made Agent SDK workloads on Pro/Max subscriptions
  generally available.  Agent SDK usage draws from a separate monthly
  Agent credit pool ($20 Pro / $100 Max-5x / $200 Max-20x, no
  rollover); requests stop when the pool is exhausted unless overage
  billing is enabled at API rates.  (Historical note: prior to June 15
  2026, Anthropic's Consumer Terms §3.7 and the April 2026 Agent SDK
  clarification prohibited this path; Anthropic's May 13 2026
  announcement legalised it from that date onward.)

Urika enforces auth via three layers of defense:

1. CLI startup warning (``cli/_base.py``) when ``ANTHROPIC_API_KEY`` is
   unset — soft, non-blocking, runs for every command. Suppressed in
   subscription mode (OAuth tokens are the legitimate auth carrier there)
   and when the user sets ``URIKA_ACK_API_KEY_REQUIRED``.
2. Pre-spawn refusal in the SDK adapter (``require_api_key`` in this
   module) — raises :class:`APIKeyRequiredError` before any Claude Code
   subprocess is spawned for an Anthropic-cloud-bound agent. In
   subscription mode this branch returns silently; the bundled CLI
   will pick up its stored OAuth token from ``claude login``.
3. OAuth env scrubbing (``scrub_oauth_env`` in this module) — **billing
   hygiene** in ``api_key`` mode: zeroes ``CLAUDE_CODE_OAUTH_TOKEN`` and
   related vars in the environment passed to the spawned subprocess so
   a stray parent-shell OAuth token cannot silently route charges to
   the user's subscription credit pool.  (In subscription mode the
   OAuth-token family is the legitimate auth carrier and is preserved;
   nested-session markers are always zeroed regardless of mode.)

The pre-spawn check is exempt for:

- Agents with ``ANTHROPIC_BASE_URL`` set in their env (going to a
  private inference endpoint such as Ollama, vLLM, or a self-hosted
  proxy — not Anthropic's cloud).
- Models whose name does not start with ``claude`` (routed to a
  non-Anthropic provider via the multi-provider runtime).
- Users in ``subscription`` auth mode.
"""

from __future__ import annotations

import os
from typing import Mapping


# OAuth-class env vars: anything that can authenticate the spawned
# ``claude`` subprocess against api.anthropic.com via a Pro/Max
# subscription.  In ``api_key`` mode (billing hygiene) ANY of these
# leaking into the spawned env would let the subprocess silently route
# charges to the user's subscription credit pool.  (Historical provenance:
# pre-June-15-2026, leaking these also violated Anthropic Consumer Terms
# §3.7; the billing-hygiene rationale is now the operative one.)
#
# Pre-v0.4.2 this constant was defined but never referenced — only
# ``CLAUDE_CODE_OAUTH_TOKEN`` and ``ANTHROPIC_AUTH_TOKEN`` were
# blanked, hardcoded inline in ``scrub_oauth_env``. The refresh
# token in particular survived, defeating the access-token blank.
_OAUTH_TOKEN_VARS = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
    "CLAUDE_CODE_OAUTH_CLIENT_ID",
    "CLAUDE_CODE_SESSION_ACCESS_TOKEN",
    "CLAUDE_CODE_SDK_HAS_OAUTH_REFRESH",
    "CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR",
    "ANTHROPIC_IDENTITY_TOKEN",
    "ANTHROPIC_IDENTITY_TOKEN_FILE",
    # ANTHROPIC_AUTH_TOKEN is treated specially — see scrub_oauth_env.
)

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
    # Session-identity markers added in newer Claude Code versions —
    # also nested-launch tripwires.
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_SESSION_KIND",
    "CLAUDE_CODE_SESSION_NAME",
    "CLAUDE_CODE_SESSION_LOG",
    "CLAUDE_CODE_REMOTE_SESSION_ID",
    "CLAUDE_CODE_RESUME_FROM_SESSION",
    "CLAUDE_CODE_TMUX_SESSION",
    "CLAUDE_CODE_AGENT",
    "CLAUDE_CODE_ACTION",
)


class APIKeyRequiredError(RuntimeError):
    """Raised when Urika needs an ``ANTHROPIC_API_KEY`` but none is set."""


def _get_anthropic_auth_preference() -> str:
    """Return the user's Anthropic auth mode preference.

    Reads ``[anthropic].auth`` from ``~/.urika/settings.toml``
    (resolved through ``URIKA_HOME`` so tests can redirect it). Returns
    ``"api_key"`` (the safe default) when no settings file exists, when
    the section is missing, when the value is not a recognised mode,
    or when the settings loader itself raises.

    Valid return values:

    - ``"api_key"`` (default) — pre-v0.7.0 behaviour: require
      ``ANTHROPIC_API_KEY`` for cloud-bound calls, scrub OAuth tokens
      from the spawned subprocess env.
    - ``"subscription"`` — opt-in, post-June-15-2026: relax the
      pre-spawn check, preserve OAuth tokens for the bundled CLI to
      use via ``claude login``.

    Isolated into a tiny helper so the rest of the module — and tests
    — can monkeypatch a single seam.
    """
    try:
        from urika.core.settings import load_settings

        data = load_settings()
    except Exception:
        return "api_key"
    section = data.get("anthropic") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        return "api_key"
    auth = section.get("auth", "api_key")
    if auth not in ("api_key", "subscription"):
        return "api_key"
    return auth


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


def require_api_key(model: str | None, agent_env: Mapping[str, str] | None) -> None:
    """Raise :class:`APIKeyRequiredError` if a cloud-bound call has no key.

    Layer 2 of the safety net — called by the SDK adapter before each
    subprocess spawn. Layer 1 (CLI warning) is in ``cli/_base.py``.
    Layer 3 (env scrubbing) is :func:`scrub_oauth_env`.

    Three short-circuits, in order:

    1. Not an Anthropic-cloud call (private endpoint or non-claude
       model) → return.
    2. User opted into ``subscription`` auth mode → return; the
       bundled CLI will authenticate via the OAuth token stored
       by ``claude login``.
    3. API key already present in agent env or process env → return.

    Anything else → raise ``APIKeyRequiredError`` with an actionable
    fix message.
    """
    if not is_anthropic_cloud_call(model, agent_env):
        return
    if _get_anthropic_auth_preference() == "subscription":
        return
    if has_api_key(agent_env):
        return
    raise APIKeyRequiredError(
        "ANTHROPIC_API_KEY is not set, and this agent is configured to "
        "call api.anthropic.com. Urika is in `api_key` auth mode "
        "(the default), which requires an API key.\n"
        "\n"
        "Fix — pick one:\n"
        "  (a) Run `urika config api-key` for interactive setup, or\n"
        "      `export ANTHROPIC_API_KEY=sk-ant-...`.\n"
        "  (b) Switch to subscription auth: `urika config anthropic "
        "--mode subscription`.\n"
        "      Note: since June 15 2026, Agent SDK workloads on a "
        "Pro/Max subscription\n"
        "      draw from a separate monthly Agent credit pool "
        "($20-$200 by plan, no\n"
        "      rollover); requests stop when it runs out unless "
        "overage billing is enabled.\n"
        "  (c) Configure a private endpoint (set ANTHROPIC_BASE_URL on "
        "the agent or\n"
        "      switch the project to mode=private)."
    )


def scrub_oauth_env_for_subprocess(
    config_env: Mapping[str, str] | None,
) -> dict[str, str]:
    """Full subprocess environment: ``os.environ`` overlaid with the
    agent's env, then scrubbed.

    Shared by adapters whose function tools spawn local subprocesses
    (OpenAI / Google bash wrappers) so the merge semantics can't drift
    between adapters. The Claude adapter doesn't use this — its SDK
    subprocess env is built separately and scrubbed via
    :func:`scrub_oauth_env`.
    """
    return scrub_oauth_env({**os.environ, **(config_env or {})})


def scrub_oauth_env(agent_env: Mapping[str, str] | None) -> dict[str, str]:
    """Return a copy of *agent_env* with parent-session leakage zeroed.

    Two classes of vars get blanked when not already set:

    1. OAuth tokens (``CLAUDE_CODE_OAUTH_TOKEN``, ``ANTHROPIC_AUTH_TOKEN``)
       — **billing hygiene** in ``api_key`` mode (default): prevents a
       stray parent-shell OAuth token from silently routing charges to
       the user's subscription credit pool via the spawned subprocess.
       (Historical note: prior to June 15 2026, leaking these also
       violated Anthropic Consumer Terms §3.7.)  In ``subscription``
       mode (opt-in) the OAuth-token family is the legitimate auth
       carrier and is preserved verbatim.
    2. Claude Code session markers (``CLAUDECODE``, ``CLAUDE_CODE_SSE_PORT``,
       ``CLAUDE_CODE_ENTRYPOINT``, ``CLAUDE_CODE_EXECPATH``) — set when
       Urika itself is launched from a terminal owned by the Claude Code
       CLI / IDE extension. The bundled CLI the Agent SDK spawns refuses
       to launch nested when it sees these and exits 1. Urika's agents
       are workers, not user-interactive sessions, so the markers don't
       apply to them. Always zeroed regardless of auth mode — nested-
       launch refusal is independent of subscription vs. api-key auth.

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
    subscription_mode = _get_anthropic_auth_preference() == "subscription"
    # OAuth/identity tokens: billing hygiene in api_key mode (default) —
    # zero them so a parent-shell OAuth token cannot silently route
    # charges to the user's subscription credit pool. In subscription
    # mode they ARE the auth carrier the bundled CLI needs; preserve
    # verbatim. ANTHROPIC_AUTH_TOKEN is the standard Bearer-auth header
    # for OpenAI-compatible private endpoints and MUST be preserved when
    # deliberately set in api_key mode too; only blank-on-absent there.
    if not subscription_mode:
        for var in _OAUTH_TOKEN_VARS:
            out[var] = ""
        out.setdefault("ANTHROPIC_AUTH_TOKEN", "")
    # Nested-session markers are zeroed regardless of auth mode — the
    # bundled CLI's nested-launch refusal trips on these whether the
    # user is using an api key or an OAuth subscription token.
    for var in _NESTED_SESSION_VARS:
        out[var] = ""
    return out
