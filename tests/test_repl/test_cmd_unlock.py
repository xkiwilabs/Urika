"""REPL ``/unlock`` parity test (v0.4.5 R1).

Pre-v0.4.5 the REPL had no unlock surface — stale-lock recovery
from inside the REPL required dropping to a shell. ``cmd_unlock``
wraps the same ``urika.core.unlock.try_unlock`` helper the CLI
``urika unlock`` uses, so both surfaces stay in lockstep.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.repl.commands import cmd_unlock
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


def test_no_locked_experiments_prints_and_returns(tmp_path: Path, capsys) -> None:
    session, _proj = _setup(tmp_path)
    cmd_unlock(session, "")
    out = capsys.readouterr().out
    assert "No locked experiments" in out


def test_single_locked_experiment_dead_pid_cleared(tmp_path: Path, capsys) -> None:
    """Dead-PID lock self-heals via the shared helper. Mirrors the
    CLI test ``test_dead_pid_lock_is_cleaned_and_run_proceeds`` in
    ``test_cli/test_unlock_command.py`` — same expected outcome
    because both surfaces call the same ``try_unlock``."""
    session, proj = _setup(tmp_path)
    exp_id = "exp-001-baseline"
    lock = proj / "experiments" / exp_id / ".lock"
    lock.write_text("99999998")  # implausibly large; psutil reports dead

    cmd_unlock(session, "")  # no args → pick the single lock

    assert not lock.exists(), "dead-PID lock should be cleared"
    out = capsys.readouterr().out
    assert "Unlocked" in out
    assert exp_id in out


def test_live_urika_lock_refused_without_force(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Refuses a live urika/python-looking lock unless --force.

    Pins the safety check that prevents the REPL from accidentally
    killing a real running experiment in another window.
    """
    session, proj = _setup(tmp_path)
    exp_id = "exp-001-baseline"
    lock = proj / "experiments" / exp_id / ".lock"
    lock.write_text("12345")

    # Mock the alive + name checks so the test is hermetic.
    monkeypatch.setattr("urika.core.session._pid_is_alive", lambda p: True)
    monkeypatch.setattr("urika.core.session._get_process_name", lambda p: "python")

    cmd_unlock(session, "")  # no force

    assert lock.exists(), "live-urika lock must not be removed without --force"
    out = capsys.readouterr().out
    assert "ALIVE" in out
    assert "force" in out.lower()


def test_live_urika_lock_force_unlocks(tmp_path: Path, capsys, monkeypatch) -> None:
    """Same setup as above but with --force — lock should clear."""
    session, proj = _setup(tmp_path)
    exp_id = "exp-001-baseline"
    lock = proj / "experiments" / exp_id / ".lock"
    lock.write_text("12345")

    monkeypatch.setattr("urika.core.session._pid_is_alive", lambda p: True)
    monkeypatch.setattr("urika.core.session._get_process_name", lambda p: "python")

    cmd_unlock(session, f"{exp_id} --force")

    assert not lock.exists(), "force should remove the lock"
    out = capsys.readouterr().out
    assert "Unlocked" in out


def test_explicit_experiment_id_with_no_lock(tmp_path: Path, capsys) -> None:
    """Asking for a specific exp that has no lock prints the
    ``No lock file at ...`` branch rather than the "no locked
    experiments in project" branch."""
    session, proj = _setup(tmp_path)
    cmd_unlock(session, "exp-001-baseline")
    out = capsys.readouterr().out
    assert "No lock file" in out


def test_unlock_command_is_registered_with_project_requirement() -> None:
    """The ``@command("unlock", requires_project=True, ...)`` registration
    must land in ``PROJECT_COMMANDS`` so the TUI's REPL-piggyback
    dispatcher also picks it up (v0.4.5 T2 parity)."""
    from urika.repl.commands import PROJECT_COMMANDS

    assert "unlock" in PROJECT_COMMANDS, (
        "cmd_unlock should be registered as a project command — the "
        "TUI inherits the REPL command registry so omitting this "
        "registration would silently re-create the v0.4.5 T2 gap"
    )
    entry = PROJECT_COMMANDS["unlock"]
    assert entry["func"] is cmd_unlock
    assert "description" in entry


@pytest.mark.parametrize(
    "args,expect_substr",
    [
        ("", "No locked experiments"),
        ("nonexistent-exp", "No lock file"),
    ],
)
def test_unlock_arg_handling_branches(
    tmp_path: Path, capsys, args, expect_substr
) -> None:
    session, _proj = _setup(tmp_path)
    cmd_unlock(session, args)
    out = capsys.readouterr().out
    assert expect_substr in out
