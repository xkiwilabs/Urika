"""SecurityPolicy enforcement helpers shared across tools.

Mirrors the runtime checks in ``urika.agents.permission`` so adapters
that don't go through the Claude SDK's ``can_use_tool`` callback still
get the same enforcement.

These helpers are deliberately a small, conservative subset of the
``permission._bash_decision`` / ``_path_decision`` logic — they assume
the caller already knows which policy attribute (``writable_dirs`` vs
``readable_dirs``) applies, and they return a single deny-reason
string rather than a (bool, reason) pair.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from urika.agents.permission import SecurityPolicy


def enforce_bash(cmd: str, policy: SecurityPolicy) -> str | None:
    """Return None if ``cmd`` is allowed, else a human-readable reason.

    Matches ``permission._bash_decision`` semantics: reject shell
    metacharacters outright, apply blocklist first (always wins), then
    require the head token to match an entry in
    ``allowed_bash_prefixes`` (tokenised, NOT raw startswith).
    """
    try:
        tokens = shlex.split(cmd)
    except ValueError as exc:
        return f"unparseable command: {exc}"
    if not tokens:
        return "empty command"
    for tok in tokens:
        if any(ch in tok for ch in ";|&`$()<>"):
            return f"shell metacharacter rejected in token {tok!r}"
    for pat in policy.blocked_bash_patterns:
        if pat in cmd:
            return f"blocked pattern {pat!r}"
    if not policy.allowed_bash_prefixes:
        return "no bash prefixes whitelisted for this agent"
    head = tokens[0]
    for prefix in policy.allowed_bash_prefixes:
        try:
            head_tokens = shlex.split(prefix)
        except ValueError:
            continue
        if not head_tokens:
            continue
        if tokens[: len(head_tokens)] == head_tokens:
            return None
    return f"command {head!r} not in allowlist"


def enforce_path_write(
    path: str, policy: SecurityPolicy
) -> tuple[Path | None, str | None]:
    """Resolve ``path`` and check it's under a writable dir.

    Returns ``(resolved, error)``.
    """
    p = Path(path).expanduser().resolve(strict=False)
    for writable in policy.writable_dirs:
        try:
            resolved_dir = Path(writable).expanduser().resolve(strict=False)
            if p == resolved_dir or p.is_relative_to(resolved_dir):
                return p, None
        except (TypeError, ValueError):
            continue
    return None, f"path {p} not under any writable dir"


def enforce_path_read(
    path: str, policy: SecurityPolicy
) -> tuple[Path | None, str | None]:
    """Resolve ``path`` and check it's under a readable or writable dir.

    Writable dirs imply read access. Returns ``(resolved, error)``.
    """
    p = Path(path).expanduser().resolve(strict=False)
    candidates = list(policy.readable_dirs) + list(policy.writable_dirs)
    for d in candidates:
        try:
            resolved_dir = Path(d).expanduser().resolve(strict=False)
            if p == resolved_dir or p.is_relative_to(resolved_dir):
                return p, None
        except (TypeError, ValueError):
            continue
    return None, f"path {p} not under any readable dir"
