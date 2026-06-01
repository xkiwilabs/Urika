"""Parity tests pinning ``tools.security.enforce_*`` to the same
decisions as ``permission._bash_decision`` / ``_path_decision``.

The design spec for v0.7.0 (``dev/plans/2026-06-01-v0.7.0-design.md``,
"Tool layer — urika.agents.tools") requires a single source of truth
for security enforcement so the Claude SDK ``can_use_tool`` callback
and the OpenAI/Google function-tool wrappers can never drift apart.
These tests parametrize a canonical set of inputs and assert both
layers agree (allow ↔ ``enforce_bash`` returns None; deny ↔ returns
a reason string). Adding a future check to ``permission`` without
updating the tools layer (or vice versa) must fail loudly here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.config import SecurityPolicy
from urika.agents.permission import _bash_decision, _path_decision
from urika.agents.tools.security import (
    enforce_bash,
    enforce_path_read,
    enforce_path_write,
)


def _policy(
    *,
    writable: list[Path] | None = None,
    readable: list[Path] | None = None,
    allowed_bash: list[str] | None = None,
    blocked: list[str] | None = None,
) -> SecurityPolicy:
    return SecurityPolicy(
        writable_dirs=writable or [],
        readable_dirs=readable or [],
        allowed_bash_prefixes=allowed_bash or [],
        blocked_bash_patterns=blocked or [],
    )


@pytest.mark.parametrize(
    "cmd",
    [
        # Allowed: head matches allowlist, no metachars
        "echo hello",
        "echo 'hello world'",
        # Disallowed: head not in allowlist
        "rm -rf /",
        # Metachar-injected: semicolon
        "echo hi; rm -rf /",
        # Newline-injected (Issue 1): tokenises across lines, head OK
        "echo ok\nrm -rf /tmp/x",
        # $( ... ) command substitution
        "echo $(whoami)",
        # Pipe
        "echo a | cat",
        # Logical-AND
        "echo a && rm -rf /",
        # Logical-OR
        "echo a || rm -rf /",
        # Redirect
        "echo a > /tmp/foo",
        # Backtick
        "echo `id`",
        # Unparseable (unbalanced quotes)
        "echo 'unbalanced",
        # Empty
        "",
        "   ",
    ],
)
def test_tools_security_bash_matches_permission_decision(cmd: str):
    """``enforce_bash`` and ``_bash_decision`` must agree on every input."""
    policy = _policy(allowed_bash=["echo"])
    perm_allow, perm_reason = _bash_decision(cmd, policy)
    tools_reason = enforce_bash(cmd, policy)
    tools_allow = tools_reason is None
    assert perm_allow == tools_allow, (
        f"divergence for cmd={cmd!r}: "
        f"permission={perm_allow} ({perm_reason!r}) "
        f"vs tools={tools_allow} ({tools_reason!r})"
    )


def test_tools_security_bash_blocklist_always_wins():
    """Blocklist denies even when the head is in the allowlist."""
    policy = _policy(allowed_bash=["echo"], blocked=["rm"])
    cmd = "echo rm me"  # 'rm' substring is blocked even though head is 'echo'
    perm_allow, _ = _bash_decision(cmd, policy)
    tools_reason = enforce_bash(cmd, policy)
    assert perm_allow is False
    assert tools_reason is not None


def test_tools_security_bash_empty_allowlist_denies():
    policy = _policy(allowed_bash=[])
    perm_allow, _ = _bash_decision("echo hi", policy)
    tools_reason = enforce_bash("echo hi", policy)
    assert perm_allow is False
    assert tools_reason is not None


def test_tools_security_path_write_matches_permission(tmp_path: Path):
    policy = _policy(writable=[tmp_path])
    # Inside
    p_inside = tmp_path / "a.txt"
    perm_allow, _ = _path_decision(
        str(p_inside), policy.writable_dirs, project_root=None, op="write"
    )
    resolved, err = enforce_path_write(str(p_inside), policy)
    assert perm_allow is True
    assert err is None and resolved is not None

    # Outside
    outside = "/etc/passwd"
    perm_allow_out, _ = _path_decision(
        outside, policy.writable_dirs, project_root=None, op="write"
    )
    resolved_out, err_out = enforce_path_write(outside, policy)
    assert perm_allow_out is False
    assert err_out is not None and resolved_out is None


def test_tools_security_path_read_matches_permission(tmp_path: Path):
    """Read accepts both ``readable_dirs`` and ``writable_dirs`` (writable
    implies readable). Parity must hold across both surfaces."""
    readable = tmp_path / "ro"
    writable = tmp_path / "rw"
    readable.mkdir()
    writable.mkdir()
    policy = _policy(readable=[readable], writable=[writable])

    # Inside readable
    p_ro = readable / "a.txt"
    perm_allow_ro, _ = _path_decision(
        str(p_ro),
        list(policy.readable_dirs) + list(policy.writable_dirs),
        project_root=None,
        op="read",
    )
    _resolved_ro, err_ro = enforce_path_read(str(p_ro), policy)
    assert perm_allow_ro is True
    assert err_ro is None

    # Inside writable (writable implies readable)
    p_rw = writable / "a.txt"
    perm_allow_rw, _ = _path_decision(
        str(p_rw),
        list(policy.readable_dirs) + list(policy.writable_dirs),
        project_root=None,
        op="read",
    )
    _resolved_rw, err_rw = enforce_path_read(str(p_rw), policy)
    assert perm_allow_rw is True
    assert err_rw is None

    # Outside both
    outside = "/etc/passwd"
    perm_allow_out, _ = _path_decision(
        outside,
        list(policy.readable_dirs) + list(policy.writable_dirs),
        project_root=None,
        op="read",
    )
    _resolved_out, err_out = enforce_path_read(outside, policy)
    assert perm_allow_out is False
    assert err_out is not None
