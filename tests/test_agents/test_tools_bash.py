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


def test_bash_rejects_newline_injection(tmp_path: Path):
    """A literal newline in the command is a shell separator on both
    POSIX and Windows. ``shlex.split`` happily tokenises across lines,
    so the head can match the allowlist while the second line runs an
    arbitrary command. ``enforce_bash`` must reject newline outright,
    matching ``permission._bash_decision``'s metachar list.
    """
    policy = _policy(allowed_bash=["echo"], writable=[tmp_path])
    result = bash("echo ok\nrm -rf /tmp/x", security=policy, project_dir=tmp_path)
    assert result.ok is False
    assert "metacharacter" in (result.error or "")


def test_bash_truncates_huge_stdout(tmp_path: Path, monkeypatch):
    """A runaway command that produces >32 KB of stdout must have its
    output bounded before flowing into ``ToolResult.output`` — otherwise
    the LLM context fills up with a single tool result.

    Monkeypatch ``subprocess.run`` so the test doesn't rely on argv
    lengths the OS may refuse (Windows cmd has ~8 KB argv limit).
    """
    import subprocess

    class _FakeCompleted:
        returncode = 0
        stdout = "x" * 100_000
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _FakeCompleted())

    policy = _policy(
        allowed_bash=["echo"],
        writable=[tmp_path],
    )
    result = bash("echo placeholder", security=policy, project_dir=tmp_path)
    assert result.ok is True
    # Result must be capped at ~32 KB plus the truncation marker.
    assert len(result.output) < 40_000
    assert "truncated" in result.output


def test_bash_env_override(tmp_path: Path):
    """``env`` kwarg threads through to the subprocess — a custom env
    var set in ``env`` is visible to the command.
    """
    import os

    policy = _policy(allowed_bash=["printenv", "echo"], writable=[tmp_path])
    custom_env = {**os.environ, "URIKA_TEST_VAR": "scrubbed-env-works"}
    result = bash(
        "printenv URIKA_TEST_VAR",
        security=policy,
        project_dir=tmp_path,
        env=custom_env,
    )
    assert result.ok is True, result.error
    assert result.output.strip() == "scrubbed-env-works"


def test_bash_env_none_inherits(tmp_path: Path, monkeypatch):
    """When ``env=None`` (the default), the subprocess inherits the
    current process environment — pre-existing behaviour unchanged.
    """
    monkeypatch.setenv("URIKA_INHERIT_TEST", "inherited-value")
    policy = _policy(allowed_bash=["printenv"], writable=[tmp_path])
    result = bash(
        "printenv URIKA_INHERIT_TEST",
        security=policy,
        project_dir=tmp_path,
    )
    assert result.ok is True, result.error
    assert result.output.strip() == "inherited-value"
