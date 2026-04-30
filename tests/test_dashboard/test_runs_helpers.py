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
    """Invoke a spawn helper with subprocess.Popen captured.

    The dashboard now detaches subprocesses (stdout goes straight to a
    file, no pipe), so ``FakeProc.stdout`` is irrelevant — the spawn
    helper never reads from it. We still expose ``wait()`` because the
    reaper thread calls it; returning immediately lets the reaper exit
    promptly so it cleans up the lock file before the test finishes.
    """
    import subprocess

    captured = {}

    class FakeProc:
        pid = 12345

        def wait(self):
            return 0

    def fake_popen(cmd, **popen_kwargs):
        captured["cmd"] = cmd
        captured["popen_kwargs"] = popen_kwargs
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


def test_spawn_experiment_run_advisor_first_appends_flag(monkeypatch, tmp_path):
    """When the dashboard's "Ask advisor first" checkbox is on, the spawn
    helper must append ``--advisor-first`` to the CLI command so the
    spawned ``urika run`` runs the advisor before the orchestrator loop.
    """
    from urika.dashboard.runs import spawn_experiment_run

    (tmp_path / "experiments" / "exp-001").mkdir(parents=True)
    cmd = _captured_argv(
        monkeypatch,
        spawn_experiment_run,
        "alpha",
        tmp_path,
        "exp-001",
        advisor_first=True,
    )
    assert "--advisor-first" in cmd


def test_spawn_experiment_run_advisor_first_omitted_when_false(monkeypatch, tmp_path):
    """When the checkbox is off (the default), the spawn helper must NOT
    pass ``--advisor-first`` so the CLI skips the pre-loop advisor pass.
    """
    from urika.dashboard.runs import spawn_experiment_run

    (tmp_path / "experiments" / "exp-001").mkdir(parents=True)
    cmd = _captured_argv(
        monkeypatch,
        spawn_experiment_run,
        "alpha",
        tmp_path,
        "exp-001",
    )
    assert "--advisor-first" not in cmd


# ---------- Detached-spawn invariants ----------
#
# The whole point of ``_spawn_detached`` is that the child outlives
# the dashboard. Two structural invariants make that work:
#   1. The child's stdout/stderr write directly to the log file
#      (NOT a pipe through the dashboard) — so SIGPIPE on dashboard
#      exit can't kill the child.
#   2. The child runs in its own session/process group — so a
#      Ctrl+C in the dashboard's terminal doesn't propagate to the
#      child via the controlling-terminal signal path.
#
# These tests pin both invariants so a future refactor can't silently
# regress them.


def test_spawn_detached_uses_start_new_session_and_no_pipe(monkeypatch, tmp_path):
    import subprocess
    import sys as _sys

    from urika.dashboard.runs import spawn_finalize

    captured = {}

    class FakeProc:
        pid = 99001

        def wait(self):
            return 0

    def fake_popen(cmd, **popen_kwargs):
        captured["cmd"] = cmd
        captured["popen_kwargs"] = popen_kwargs
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    spawn_finalize("alpha", tmp_path)

    kw = captured["popen_kwargs"]
    # stdout must be a real file object, NOT subprocess.PIPE — that's
    # how the child survives our exit (no pipe → no SIGPIPE).
    assert kw["stdout"] is not subprocess.PIPE
    assert hasattr(kw["stdout"], "fileno"), (
        "stdout must be a file-like object with a fileno (the open log file), "
        "not a pipe; the child must write directly to disk"
    )
    assert kw["stderr"] == subprocess.STDOUT
    assert kw["stdin"] == subprocess.DEVNULL
    assert kw.get("close_fds") is True

    # Session/process-group isolation, platform-conditional.
    if _sys.platform == "win32":
        assert kw.get("creationflags", 0) & subprocess.CREATE_NEW_PROCESS_GROUP
        assert "start_new_session" not in kw
    else:
        assert kw.get("start_new_session") is True


def test_spawn_writes_lock_with_pid(monkeypatch, tmp_path):
    """After spawn, the lock file should contain the child's PID.

    Used by ``_is_active_run_lock`` and the active-ops banner to
    detect running operations across dashboard restarts.
    """
    import subprocess

    from urika.dashboard.runs import spawn_finalize

    class FakeProc:
        pid = 424242

        def wait(self):
            # Block briefly so the test can assert the lock exists
            # with the PID before the reaper thread removes it.
            import time

            time.sleep(0.5)
            return 0

    def fake_popen(cmd, **popen_kwargs):
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    spawn_finalize("alpha", tmp_path)

    lock_path = tmp_path / "projectbook" / ".finalize.lock"
    assert lock_path.is_file()
    assert lock_path.read_text(encoding="utf-8") == "424242"


def test_reaper_removes_lock_when_child_exits(monkeypatch, tmp_path):
    """The reaper daemon thread must unlink the lock once ``proc.wait()``
    returns, so SSE tailers can detect completion and the active-ops
    banner stops reporting the operation."""
    import subprocess

    from urika.dashboard.runs import _DAEMON_THREADS, spawn_finalize

    class FakeProc:
        pid = 77777

        def wait(self):
            return 0  # exits immediately

    def fake_popen(cmd, **popen_kwargs):
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    # Snapshot before spawn so we can identify the new reaper thread.
    before = list(_DAEMON_THREADS)
    spawn_finalize("alpha", tmp_path)
    new_threads = [t for t in _DAEMON_THREADS if t not in before]
    assert new_threads, "spawn should register a reaper thread"
    new_threads[-1].join(timeout=5.0)

    lock_path = tmp_path / "projectbook" / ".finalize.lock"
    assert not lock_path.exists(), (
        "reaper must unlink the lock once the child exits, so SSE tailers "
        "and the active-ops banner can detect completion"
    )


# ── Reaper writes terminal status for stopped/failed runs ─────────────


def test_reaper_writes_stopped_status_for_run_lock_with_sigterm_exit(
    tmp_path, monkeypatch
):
    """When an experiment ``.lock``'s child exits via SIGTERM (return
    code -15) and progress.json doesn't already have a terminal status,
    the reaper must write ``status="stopped"`` so the dashboard
    experiment card flips off the static ``"pending"`` initial state.

    Pre-v0.3.2 the reaper only unlinked the lock; the dashboard then
    fell back to ``experiment.json`` whose status was still
    ``"pending"`` (the seed value), so the card lied about the run
    state. Combined with the CLI's missing SIGTERM handler, this was
    exactly the symptom the user reported on the Stop button.
    """
    import json
    import subprocess

    from urika.dashboard.runs import _DAEMON_THREADS, spawn_experiment_run

    project_root = tmp_path
    exp_dir = project_root / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "progress.json").write_text(
        json.dumps({"status": "running"}), encoding="utf-8"
    )

    class FakeProc:
        pid = 8888

        def wait(self):
            return -15  # SIGTERM (-signal.SIGTERM)

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProc())

    before = list(_DAEMON_THREADS)
    spawn_experiment_run("alpha", project_root, "exp-001")
    new = [t for t in _DAEMON_THREADS if t not in before]
    assert new
    new[-1].join(timeout=5.0)

    progress = json.loads((exp_dir / "progress.json").read_text(encoding="utf-8"))
    assert progress["status"] == "stopped", (
        "reaper must write 'stopped' for a SIGTERM exit so the dashboard "
        "card doesn't fall back to the static 'pending' initial state"
    )


def test_reaper_does_not_overwrite_existing_terminal_status(tmp_path, monkeypatch):
    """When the CLI's SIGTERM handler already wrote a terminal status
    (``stopped`` / ``failed`` / ``completed``), the reaper must respect
    it — race-free fallback only fills in when the status is missing.
    """
    import json
    import subprocess

    from urika.dashboard.runs import _DAEMON_THREADS, spawn_experiment_run

    project_root = tmp_path
    exp_dir = project_root / "experiments" / "exp-002"
    exp_dir.mkdir(parents=True)
    (exp_dir / "progress.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8"
    )

    class FakeProc:
        pid = 9999

        def wait(self):
            return -15

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProc())

    before = list(_DAEMON_THREADS)
    spawn_experiment_run("alpha", project_root, "exp-002")
    new = [t for t in _DAEMON_THREADS if t not in before]
    assert new
    new[-1].join(timeout=5.0)

    progress = json.loads((exp_dir / "progress.json").read_text(encoding="utf-8"))
    assert progress["status"] == "completed"


def test_reaper_skips_status_write_for_zero_exit(tmp_path, monkeypatch):
    """A successful exit (returncode 0) means the CLI wrote its own
    completion status — reaper does nothing, just unlinks the lock.
    """
    import json
    import subprocess

    from urika.dashboard.runs import _DAEMON_THREADS, spawn_experiment_run

    project_root = tmp_path
    exp_dir = project_root / "experiments" / "exp-003"
    exp_dir.mkdir(parents=True)
    (exp_dir / "progress.json").write_text(
        json.dumps({"status": "running"}), encoding="utf-8"
    )

    class FakeProc:
        pid = 7777

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProc())

    before = list(_DAEMON_THREADS)
    spawn_experiment_run("alpha", project_root, "exp-003")
    new = [t for t in _DAEMON_THREADS if t not in before]
    assert new
    new[-1].join(timeout=5.0)

    progress = json.loads((exp_dir / "progress.json").read_text(encoding="utf-8"))
    # Stays "running" — the reaper trusts the CLI to have written
    # the completion state by the time it exited cleanly.
    assert progress["status"] == "running"
