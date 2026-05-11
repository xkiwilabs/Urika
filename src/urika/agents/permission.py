"""SecurityPolicy enforcement via SDK ``can_use_tool`` callback.

Pre-v0.4 the ``SecurityPolicy`` fields on every agent role
(``writable_dirs`` / ``readable_dirs`` / ``allowed_bash_prefixes`` /
``blocked_bash_patterns``) were advisory only — declared but never
consumed at runtime. The only real sandbox was ``allowed_tools`` +
``cwd``. The orchestrator chat's ``allowed_bash_prefixes=["urika "]``
was paper: ``urika ; rm -rf /`` matched the prefix.

This module wires those fields into a real ``can_use_tool`` callback
that the ``claude-agent-sdk`` invokes before each tool dispatch.
Decisions:

- **Bash**: shlex-parse the command, reject shell metacharacters
  outright, apply ``blocked_bash_patterns`` (always wins), then
  match against ``allowed_bash_prefixes`` tokenised (not raw
  ``startswith``). Empty allowlist → deny all Bash.
- **Read / Glob / Grep**: resolve path (collapses ``..``, follows
  symlinks), require it to be inside one of ``readable_dirs``.
  ``_resolve_safe → None`` always denies (defense for hybrid-mode
  privacy).
- **Write / Edit / MultiEdit / NotebookEdit**: same path check
  against ``writable_dirs``.
- **Anything else**: default allow (covers ``WebFetch``, MCP tools,
  etc. — `allowed_tools` already filters them).

See ``dev/plans/2026-04-30-securitypolicy-enforcement.md`` for the
full design + decision table.
"""

from __future__ import annotations

import logging
import shlex
from pathlib import Path
from typing import Any

from urika.agents.config import SecurityPolicy

logger = logging.getLogger(__name__)


# Shell metacharacters that, if present in a Bash command, indicate a
# shellout chain we don't want to allow under any circumstances.
# Even a command whose head matches an allowed prefix can be dangerous
# when followed by `;` or `$(...)`.
_SHELL_METACHARS: tuple[str, ...] = (
    ";", "&&", "||", "|", "`", "$(", ">", ">>", "<", "&", "\n",
)


def _resolve_safe(raw: str, project_root: Path | None) -> Path | None:
    """Resolve *raw* to an absolute Path, defeating ``..`` and symlinks.

    Returns ``None`` when the path can't be resolved (OS errors or
    cycle detection) — callers MUST treat that as deny, never allow.
    """
    try:
        p = Path(raw).expanduser()
    except (TypeError, ValueError):
        return None
    if not p.is_absolute() and project_root is not None:
        p = project_root / p
    try:
        return p.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _path_in_any(path: Path, allowed: list[Path]) -> bool:
    """True iff *path* (already resolved) is inside any *allowed* dir."""
    for raw_dir in allowed:
        resolved_dir = _resolve_safe(str(raw_dir), None)
        if resolved_dir is None:
            continue
        try:
            if path == resolved_dir or path.is_relative_to(resolved_dir):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _bash_decision(cmd: str, policy: SecurityPolicy) -> tuple[bool, str]:
    """Decide whether to allow a Bash command. Returns ``(allow, reason)``.

    Reason is empty string when allowed; populated with a
    user-facing explanation when denied.
    """
    if not isinstance(cmd, str) or not cmd.strip():
        return False, "empty command"

    # 1. Reject shell metacharacters outright.
    for m in _SHELL_METACHARS:
        if m in cmd:
            return False, f"shell metacharacter {m!r} not allowed"

    # 2. Tokenize. If shlex can't parse it, reject (unbalanced quotes,
    # etc.) — same conservative stance as metachars.
    try:
        tokens = shlex.split(cmd)
    except ValueError as exc:
        return False, f"unparseable command: {exc}"
    if not tokens:
        return False, "empty command after tokenisation"

    # 3. Blocklist FIRST — even an allow-list-matching command is
    # denied if it matches a blocked pattern. Catches embedded-string
    # shellouts that try to invoke blocked commands.
    for pat in policy.blocked_bash_patterns:
        if pat in cmd:
            return False, f"blocked pattern {pat!r}"

    # 4. Empty allowlist → no Bash allowed at all.
    if not policy.allowed_bash_prefixes:
        return False, "no bash prefixes whitelisted for this agent"

    # 5. Match against tokenised prefix (NOT raw startswith).
    for prefix in policy.allowed_bash_prefixes:
        try:
            head_tokens = shlex.split(prefix)
        except ValueError:
            continue
        if not head_tokens:
            continue
        if tokens[: len(head_tokens)] == head_tokens:
            return True, ""

    return False, f"command {tokens[0]!r} not in allowlist"


def _path_decision(
    raw_path: str,
    allowed_dirs: list[Path],
    *,
    project_root: Path | None,
    op: str,
) -> tuple[bool, str]:
    """Decide whether *raw_path* may be read or written.

    *op* is a short verb like ``"read"`` or ``"write"`` for the deny
    message.
    """
    resolved = _resolve_safe(raw_path, project_root)
    if resolved is None:
        # Critical: unresolvable paths MUST deny. Pre-v0.4 a missing
        # `_resolve_safe` would have returned None and the surrounding
        # logic might allow by default — that's the bug pattern we
        # closed in v0.3.2 across other code paths and re-applied here.
        return False, f"cannot resolve path for {op}: {raw_path!r}"
    if not allowed_dirs:
        return False, f"no {op}able dirs configured for this agent"
    if _path_in_any(resolved, allowed_dirs):
        return True, ""
    return False, f"{op} path outside allowed dirs: {resolved}"


def make_can_use_tool(
    policy: SecurityPolicy,
    project_root: Path | None,
    max_method_seconds: int | None = None,
):
    """Build a ``can_use_tool`` async callback bound to *policy*.

    The returned coroutine accepts ``(tool_name, tool_input,
    context)`` per the ``claude-agent-sdk`` ``CanUseTool`` protocol
    and returns ``PermissionResultAllow()`` (optionally with
    ``updated_input`` to clamp the request) or
    ``PermissionResultDeny(message=...)``.

    The factory is split out so ``ClaudeSDKRunner._build_options``
    can ``functools.partial`` the policy + project_root + cap in
    once per agent invocation.

    *max_method_seconds* (v0.4.1): when set, every Bash tool call
    has its ``timeout`` field clamped to ``max_method_seconds *
    1000`` ms before the SDK dispatches it. An agent that asks for
    a longer timeout sees its request silently capped; an agent
    that doesn't specify a timeout gets the cap as default. This
    upper-bound prevents a runaway training script from wedging an
    experiment for hours. ``None`` = no cap (use whatever the CLI
    defaults to, currently ~10 min).
    """
    # Lazy import — keep the SDK out of import time so unit tests of
    # this module can mock the result classes if they want.
    from claude_agent_sdk import (
        PermissionResultAllow,
        PermissionResultDeny,
    )

    cap_ms = max_method_seconds * 1000 if max_method_seconds else None

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context,  # noqa: ANN001 — SDK-typed
    ):
        decision, reason = _decide(
            tool_name, tool_input, policy, project_root
        )
        if not decision:
            # Surface the reason to the agent so it can adapt its next
            # action ("use Write tool instead of `python -c`", "split
            # into two Bash calls"). Pre-v0.4 the agent saw nothing.
            logger.info(
                "permission_check denied %s: %s (input=%r)",
                tool_name,
                reason,
                tool_input,
            )
            return PermissionResultDeny(message=reason)

        # Allow-with-clamp path: only Bash currently has a timeout
        # field worth capping. Other tools fall through to a plain
        # allow.
        if tool_name == "Bash" and cap_ms is not None:
            existing = tool_input.get("timeout")
            try:
                existing_ms = int(existing) if existing is not None else None
            except (TypeError, ValueError):
                existing_ms = None
            if existing_ms is None or existing_ms > cap_ms:
                # Two cases: the agent didn't ask for a timeout (we
                # set ours as default), or asked for one bigger than
                # our cap (we clamp). Smaller-than-cap requests pass
                # through unchanged so the agent can still ask for
                # short timeouts on quick checks.
                return PermissionResultAllow(
                    updated_input={**tool_input, "timeout": cap_ms},
                )

        return PermissionResultAllow()

    return can_use_tool


# Tool families for routing. Internal implementation detail —
# kept at module scope so unit tests can grep against it.
_READABLE_TOOLS = {"Read", "Glob", "Grep"}
_WRITABLE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# Tools that let an agent step *outside* this callback's reach and so
# must never be permitted, regardless of ``allowed_tools``:
#
# - ``Task`` / ``Agent``: spawn a sub-agent that runs with its own
#   (un-sandboxed) tool config — the sub-agent's tool calls do NOT
#   come back through this ``can_use_tool``. An agent that can't write
#   project-root ``methods.json`` directly could otherwise delegate
#   the write to a sub-agent. Observed in the wild (v0.4.3): a
#   task_agent spawned an ``Agent`` that overwrote ``methods.json``
#   with a record missing ``name``, crashing ``register_method``.
# - ``ToolSearch``: loads arbitrary deferred tool schemas (incl. MCP
#   tools) on demand. The loaded tool calls still hit this callback,
#   but allowing dynamic expansion of the toolset under a security
#   policy is a footgun — deny it; agents that need a tool should
#   have it in ``allowed_tools`` up front.
#
# These are also added to ``disallowed_tools`` at the SDK layer
# (see ``ClaudeSDKRunner._build_options``); this denylist is the
# belt to that suspenders — it holds even if a CLI version ignores
# ``disallowed_tools`` for built-ins.
_SANDBOX_ESCAPING_TOOLS = frozenset({"Task", "Agent", "ToolSearch"})


def _decide(
    tool_name: str,
    tool_input: dict[str, Any],
    policy: SecurityPolicy,
    project_root: Path | None,
) -> tuple[bool, str]:
    """Pure-function decision splitter — exposed for unit tests."""
    if tool_name in _SANDBOX_ESCAPING_TOOLS:
        return False, (
            f"{tool_name} is not permitted under a security policy "
            "(it would run outside the sandbox) — do the work directly "
            "with the tools you already have"
        )

    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return _bash_decision(cmd, policy)

    if tool_name in _READABLE_TOOLS:
        path = (
            tool_input.get("file_path")
            or tool_input.get("path")
            or tool_input.get("pattern")
            or ""
        )
        if not path:
            return True, ""  # No path to gate — let the SDK reject.
        return _path_decision(
            str(path), policy.readable_dirs, project_root=project_root, op="read"
        )

    if tool_name in _WRITABLE_TOOLS:
        path = (
            tool_input.get("file_path")
            or tool_input.get("notebook_path")
            or ""
        )
        if not path:
            return True, ""
        return _path_decision(
            str(path), policy.writable_dirs, project_root=project_root, op="write"
        )

    # Default-allow for everything else (WebFetch, WebSearch, MCP tools,
    # TodoWrite, etc.). ``allowed_tools`` already filters them at the
    # SDK layer — this callback is just the policy enforcer.
    return True, ""
