"""Tests for the small helpers in ``src/urika/dashboard/runs.py``.

These cover the env + base-command builders that every spawn_* function
uses. We don't try to spawn a real subprocess here — the assertions are
pure value checks on the helpers' return values.

The unbuffering bits matter: without ``-u`` and ``PYTHONUNBUFFERED=1``,
a piped child stdout is block-buffered (~8KB) and the SSE drainer
thread sees nothing until the child exits. These tests pin the helpers
that fix that, so a future refactor can't regress it silently.
"""

from __future__ import annotations

import sys

from urika.dashboard.runs import _build_env, _python_cmd


def test_build_env_default_unbuffered_no_tee_unset():
    env = _build_env()
    assert env.get("PYTHONUNBUFFERED") == "1"
    assert "URIKA_NO_TEE" not in env


def test_build_env_with_no_tee_sets_both():
    env = _build_env(no_tee=True)
    assert env.get("PYTHONUNBUFFERED") == "1"
    assert env.get("URIKA_NO_TEE") == "1"


def test_python_cmd_default_uses_sys_executable_with_unbuffered_flag():
    cmd = _python_cmd(None)
    assert cmd == [sys.executable, "-u", "-m", "urika"]


def test_python_cmd_respects_explicit_executable():
    cmd = _python_cmd("/opt/venv/bin/python")
    assert cmd == ["/opt/venv/bin/python", "-u", "-m", "urika"]
