"""``cmd_run`` lock-detection + recovery (REPL /run path).

The locking/PID-probe block at ``commands_run.py:36-110`` had zero
direct coverage before this file. A stale lock blocking a `/run`
silently was the kind of bug only caught manually.
"""

from __future__ import annotations

import os
from pathlib import Path


from urika.repl.commands_run import cmd_run
from urika.repl.session import ReplSession


def _setup(tmp_path: Path) -> tuple[ReplSession, Path]:
    from urika.core.experiment import create_experiment
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace

    proj = tmp_path / "alpha"
    create_project_workspace(
        proj, ProjectConfig(name="alpha", question="Q?", mode="exploratory")
    )
    create_experiment(proj, name="baseline", hypothesis="h")
    session = ReplSession()
    session.load_project(path=proj, name="alpha")
    return session, proj


def _short_circuit_run(monkeypatch) -> None:
    """Stop cmd_run before it actually launches the orchestrator —
    we're testing the *pre-run* lock-detection paths."""
    # ctx.invoke(cli_run, ...) is the real-run dispatch; replace cli.run
    # with a no-op so we don't call out to anything.
    monkeypatch.setattr("urika.cli.run", lambda **_kw: None, raising=True)
    # Skip the interactive run-settings menu too — _prompt_numbered
    # below picks "Yes — defaults" automatically when stubbed.


def test_dead_pid_lock_is_cleaned_and_run_proceeds(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    session, proj = _setup(tmp_path)
    exp_id = "exp-001-baseline"
    lock = proj / "experiments" / exp_id / ".lock"
    lock.write_text("99999998")  # implausibly large; ProcessLookupError
    _short_circuit_run(monkeypatch)
    monkeypatch.setattr("urika.cli._helpers._prompt_numbered", lambda *a, **k: "Yes")
    monkeypatch.setattr(
        "urika.repl.helpers._load_run_defaults",
        lambda s: {"max_turns": 1, "auto_mode": "auto"},
    )
    # The dead-PID branch removes the lock and `continues` to the next
    # experiment; with no other experiments, the lock loop ends and we
    # continue toward the (stubbed) run.
    try:
        cmd_run(session, "")
    except Exception:
        pass  # we short-circuited urika.cli.run; any side effect is fine
    assert not lock.exists(), "dead-PID lock should have been cleaned"
    captured = capsys.readouterr()
    assert "Cleaned stale lock" in captured.out


def test_live_foreign_pid_interactive_prompts_to_cancel(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """A lock owned by a *live* foreign PID (interactive mode) prompts
    the user. When the user picks "Cancel", cmd_run returns without
    starting a run."""
    session, proj = _setup(tmp_path)
    exp_id = "exp-001-baseline"
    lock = proj / "experiments" / exp_id / ".lock"
    # os.getpid() of this test process is alive.
    lock.write_text(str(os.getpid()))
    monkeypatch.setattr(
        "urika.repl.commands_run._prompt_numbered", lambda *a, **k: "Cancel"
    )
    # cmd_run shouldn't reach urika.cli.run — Cancel returns early.
    cmd_run(session, "")
    # The lock is left untouched (it belongs to a real, live process).
    assert lock.exists()
    out = capsys.readouterr().out
    assert "currently running" in out.lower() or "running" in out.lower()


def test_live_foreign_pid_user_chooses_stop_calls_stop_session(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """When the user picks 'Stop it', stop_session is called and the
    lock is cleaned (by stop_session, which releases the lockfile)."""
    session, proj = _setup(tmp_path)
    exp_id = "exp-001-baseline"
    lock = proj / "experiments" / exp_id / ".lock"
    lock.write_text(str(os.getpid()))
    # First start a session so stop_session has something to stop.
    from urika.core.session import start_session

    start_session(proj, exp_id, max_turns=1)
    # Now the lock contains os.getpid(); make sure it does.
    lock.write_text(str(os.getpid()))
    monkeypatch.setattr(
        "urika.repl.commands_run._prompt_numbered", lambda *a, **k: "Stop"
    )
    _short_circuit_run(monkeypatch)
    monkeypatch.setattr(
        "urika.repl.helpers._load_run_defaults",
        lambda s: {"max_turns": 1, "auto_mode": "auto"},
    )
    try:
        cmd_run(session, "")
    except Exception:
        pass
    # stop_session removes the .lock as part of its cleanup.
    assert not lock.exists()
    out = capsys.readouterr().out
    assert "stopped" in out.lower()


def test_empty_lockfile_is_treated_as_stale(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """An empty lock file is treated as stale and auto-cleaned.

    Originally this test pinned the *opposite* behavior — empty
    locks were conservatively treated as valid because pre-v0.3
    lockfiles were empty sentinels. But ``session.py:acquire_lock``
    already treats empty locks as stale (commit 74cde602 / v0.4.2
    Package K) so the REPL's "treat as valid" was inconsistent with
    the underlying layer: ``cmd_run`` would prompt the user, then
    the next ``acquire_lock`` would silently clean it anyway.

    The realignment also lifts a Windows-CI regression: ``cmd_run``
    used raw ``os.kill(pid, 0)`` + ``ProcessLookupError`` to probe
    PID liveness, which is POSIX-only — the same bug already fixed
    in ``session.py`` in v0.4.2.1. ``cmd_run`` now routes through
    ``session._pid_is_alive`` (psutil-backed) and handles empty /
    garbage / dead-PID locks the same way: auto-clean and proceed.
    """
    _short_circuit_run(monkeypatch)
    monkeypatch.setattr(
        "urika.repl.helpers._load_run_defaults",
        lambda s: {"max_turns": 1, "auto_mode": "auto"},
    )
    session, proj = _setup(tmp_path)
    exp_id = "exp-001-baseline"
    lock = proj / "experiments" / exp_id / ".lock"
    lock.write_text("")
    try:
        cmd_run(session, "")
    except Exception:
        pass
    assert not lock.exists(), "empty lock should have been cleaned as stale"
    assert "Cleaned stale lock" in capsys.readouterr().out


def test_invalid_pid_string_is_treated_as_stale(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Garbage in the lock file (e.g. an external editor wrote
    'foobar') gets ValueError → treated as stale → cleaned."""
    session, proj = _setup(tmp_path)
    exp_id = "exp-001-baseline"
    lock = proj / "experiments" / exp_id / ".lock"
    lock.write_text("not-a-number")
    _short_circuit_run(monkeypatch)
    monkeypatch.setattr(
        "urika.repl.helpers._load_run_defaults",
        lambda s: {"max_turns": 1, "auto_mode": "auto"},
    )
    try:
        cmd_run(session, "")
    except Exception:
        pass
    assert not lock.exists()
    assert "Cleaned stale lock" in capsys.readouterr().out
