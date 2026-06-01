"""Tests for ``urika.agents.tools.bash`` — shared Bash tool used by
non-Claude adapters.

The Claude adapter uses the SDK's built-in Bash and enforces
``SecurityPolicy`` via the ``can_use_tool`` callback. The OpenAI and
Google adapters do not get that for free, so this module wraps
``subprocess.run`` with ``SecurityPolicy`` enforcement that mirrors
``urika.agents.permission._bash_decision``.
"""

from __future__ import annotations

from pathlib import Path

from urika.agents.permission import SecurityPolicy
from urika.agents.tools.bash import bash


def _policy(
    *,
    writable: list[Path] | None = None,
    allowed_bash: list[str] | None = None,
) -> SecurityPolicy:
    return SecurityPolicy(
        writable_dirs=writable or [],
        readable_dirs=[],
        allowed_bash_prefixes=allowed_bash or [],
        blocked_bash_patterns=[],
    )


def test_bash_runs_allowed_command(tmp_path: Path):
    policy = _policy(allowed_bash=["echo"], writable=[tmp_path])
    result = bash("echo hello", security=policy, project_dir=tmp_path)
    assert result.ok is True
    assert result.output.strip() == "hello"
    assert result.exit_code == 0


def test_bash_rejects_unallowed_command(tmp_path: Path):
    policy = _policy(allowed_bash=["echo"], writable=[tmp_path])
    result = bash("rm -rf /", security=policy, project_dir=tmp_path)
    assert result.ok is False
    assert "not in allowlist" in (result.error or "")


def test_bash_rejects_shell_metachars(tmp_path: Path):
    policy = _policy(allowed_bash=["echo"], writable=[tmp_path])
    result = bash("echo hi; rm -rf /", security=policy, project_dir=tmp_path)
    assert result.ok is False
    assert "metacharacter" in (result.error or "")
