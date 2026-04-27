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


# ---------- No-`--json` regression guard ----------
#
# The CLI's tool-use callback (``_make_on_message`` in
# ``urika.cli._helpers``) is gated on ``not json_output``. When a spawn
# helper passes ``--json``, that callback becomes a no-op and nothing
# prints during the run — so the dashboard's SSE log stream stays
# silent until completion, defeating the unbuffering work above.
#
# These tests pin that no spawn helper passes ``--json`` so a future
# refactor can't reintroduce the silencing.


def _captured_argv(monkeypatch, spawn_callable, *args, **kwargs):
    """Invoke a spawn helper with subprocess.Popen captured."""
    import subprocess

    captured = {}

    class FakeProc:
        pid = 12345
        stdout = None

        def wait(self):
            return 0

    def fake_popen(cmd, **popen_kwargs):
        captured["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    spawn_callable(*args, **kwargs)
    return captured["cmd"]


def test_spawn_finalize_does_not_pass_json(monkeypatch, tmp_path):
    from urika.dashboard.runs import spawn_finalize

    cmd = _captured_argv(monkeypatch, spawn_finalize, "alpha", tmp_path)
    assert "--json" not in cmd, (
        "Adding --json silences the CLI's tool-use callback, defeating "
        "the SSE log stream. Don't reintroduce it here."
    )


def test_spawn_summarize_does_not_pass_json(monkeypatch, tmp_path):
    from urika.dashboard.runs import spawn_summarize

    cmd = _captured_argv(monkeypatch, spawn_summarize, "alpha", tmp_path)
    assert "--json" not in cmd


def test_spawn_report_does_not_pass_json(monkeypatch, tmp_path):
    from urika.dashboard.runs import spawn_report

    (tmp_path / "experiments" / "exp-001").mkdir(parents=True)
    cmd = _captured_argv(monkeypatch, spawn_report, "alpha", tmp_path, "exp-001")
    assert "--json" not in cmd


def test_spawn_evaluate_does_not_pass_json(monkeypatch, tmp_path):
    from urika.dashboard.runs import spawn_evaluate

    (tmp_path / "experiments" / "exp-001").mkdir(parents=True)
    cmd = _captured_argv(monkeypatch, spawn_evaluate, "alpha", tmp_path, "exp-001")
    assert "--json" not in cmd


def test_spawn_present_does_not_pass_json(monkeypatch, tmp_path):
    from urika.dashboard.runs import spawn_present

    (tmp_path / "experiments" / "exp-001").mkdir(parents=True)
    cmd = _captured_argv(monkeypatch, spawn_present, "alpha", tmp_path, "exp-001")
    assert "--json" not in cmd


def test_spawn_build_tool_does_not_pass_json(monkeypatch, tmp_path):
    from urika.dashboard.runs import spawn_build_tool

    cmd = _captured_argv(
        monkeypatch,
        spawn_build_tool,
        "alpha",
        tmp_path,
        instructions="build a tool",
    )
    assert "--json" not in cmd


def test_spawn_advisor_does_not_pass_json(monkeypatch, tmp_path):
    from urika.dashboard.runs import spawn_advisor

    cmd = _captured_argv(
        monkeypatch,
        spawn_advisor,
        "alpha",
        tmp_path,
        "what should I try next?",
    )
    assert "--json" not in cmd


def test_spawn_advisor_passes_question_as_positional(monkeypatch, tmp_path):
    """The CLI's ``urika advisor`` command takes the question as a
    positional argument; the spawn helper must pass it through so the
    subprocess never blocks waiting on the interactive prompt."""
    from urika.dashboard.runs import spawn_advisor

    cmd = _captured_argv(
        monkeypatch,
        spawn_advisor,
        "alpha",
        tmp_path,
        "what should I try next?",
    )
    assert "advisor" in cmd
    assert "alpha" in cmd
    assert "what should I try next?" in cmd


def test_spawn_advisor_blank_question_raises(tmp_path):
    """Defensive guard — empty/whitespace question must raise rather
    than spawning a CLI invocation that would block on stdin."""
    from urika.dashboard.runs import spawn_advisor
    import pytest

    with pytest.raises(ValueError, match="question is required"):
        spawn_advisor("alpha", tmp_path, "   ")
