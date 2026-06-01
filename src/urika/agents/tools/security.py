"""SecurityPolicy enforcement helpers shared across tools.

Thin wrappers over ``urika.agents.permission._bash_decision`` /
``_path_decision`` — those are the v0.4 single source of truth for
SDK-side ``can_use_tool`` enforcement, and the v0.7.0 design
(``dev/plans/2026-06-01-v0.7.0-design.md``) requires the OpenAI /
Google function-tool layer to use the *same* logic so the two
surfaces can't drift.

The wrappers translate the underlying ``(bool, str)`` return shape
into the tools-layer-friendly shapes:

- ``enforce_bash`` returns ``None`` on allow, the deny reason on
  deny.
- ``enforce_path_read`` / ``enforce_path_write`` return
  ``(resolved_path | None, error | None)``.

If a new check is added to ``permission._bash_decision`` (e.g. a
new metachar), it propagates here automatically. Parity is also
pinned by ``tests/test_agents/test_tools_security_parity.py``.
"""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import SecurityPolicy
from urika.agents.permission import (
    _bash_decision,
    _path_decision,
    _resolve_safe,
)


def enforce_bash(cmd: str, policy: SecurityPolicy) -> str | None:
    """Return ``None`` if ``cmd`` is allowed, else a deny reason.

    Delegates to ``permission._bash_decision`` so the metachar
    blocklist (including ``\\n``, ``&&``, ``||``, ``$(``, etc.),
    the blocklist-first ordering, and the tokenised-prefix
    allowlist match are all single-source-of-truth.
    """
    allow, reason = _bash_decision(cmd, policy)
    return None if allow else reason


def enforce_path_write(
    path: str, policy: SecurityPolicy
) -> tuple[Path | None, str | None]:
    """Resolve ``path`` and check it's under a writable dir.

    Returns ``(resolved, error)``. Delegates to
    ``permission._path_decision`` for the allow/deny check and to
    ``_resolve_safe`` for the resolved-path value (so symlink /
    ``..`` collapse semantics match what the SDK callback sees).
    """
    allow, reason = _path_decision(
        path, policy.writable_dirs, project_root=None, op="write"
    )
    if not allow:
        return None, reason
    return _resolve_safe(path, None), None


def enforce_path_read(
    path: str, policy: SecurityPolicy
) -> tuple[Path | None, str | None]:
    """Resolve ``path`` and check it's under a readable or writable dir.

    Writable dirs imply read access. Returns ``(resolved, error)``.
    Delegates to ``permission._path_decision`` against the combined
    list — same as the SDK callback's read-tool branch in
    ``permission._decide``.
    """
    allow, reason = _path_decision(
        path,
        list(policy.readable_dirs) + list(policy.writable_dirs),
        project_root=None,
        op="read",
    )
    if not allow:
        return None, reason
    return _resolve_safe(path, None), None
