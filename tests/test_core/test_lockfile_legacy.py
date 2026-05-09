"""Tests for v0.4.2 Package K — lockfile handling.

Pre-v0.3 (commit 2fdae4b4) ``acquire_lock`` used ``path.touch()``
which created EMPTY lock files. The current release ALWAYS writes the
PID. So an empty lock can only mean "leftover from a pre-v0.3 release
that crashed before clean exit." The pre-K behaviour was to refuse for
6 hours after the lock's mtime — catching brand-new releases bouncing
off ancient locks. Now empty locks are treated as stale immediately.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from urika.core.session import (
    _lock_path,
    acquire_lock,
    start_session,
)


def _exp_dir(tmp_path: Path) -> tuple[Path, str]:
    """Make a tmp project dir + experiment id with empty lock."""
    project_dir = tmp_path / "myproj"
    exp_id = "exp-001"
    (project_dir / "experiments" / exp_id).mkdir(parents=True)
    return project_dir, exp_id


class TestEmptyLockIsAlwaysStale:
    def test_empty_lock_treated_as_stale(self, tmp_path: Path) -> None:
        project_dir, exp_id = _exp_dir(tmp_path)
        lock = _lock_path(project_dir, exp_id)
        # Simulate a pre-v0.3 leftover: empty file via touch.
        lock.touch()
        assert lock.exists()
        assert lock.read_text() == ""

        # Pre-K this would refuse for 6 hours; now it succeeds.
        assert acquire_lock(project_dir, exp_id) is True
        # Lock is now ours with our PID.
        assert lock.read_text().strip() == str(os.getpid())

    def test_empty_lock_recent_mtime_still_acquirable(
        self, tmp_path: Path
    ) -> None:
        """The 6-hour age check is gone — even a freshly-touched empty
        lock should be cleared so the user isn't blocked."""
        project_dir, exp_id = _exp_dir(tmp_path)
        lock = _lock_path(project_dir, exp_id)
        lock.touch()
        # Touch again to ensure mtime is now.
        os.utime(lock, None)
        assert (time.time() - lock.stat().st_mtime) < 5

        assert acquire_lock(project_dir, exp_id) is True


class TestLiveLockStillRefused:
    def test_live_pid_lock_refused(self, tmp_path: Path) -> None:
        """The fix mustn't accidentally also remove valid locks from
        running processes. PID 1 (init) is always alive on POSIX."""
        project_dir, exp_id = _exp_dir(tmp_path)
        lock = _lock_path(project_dir, exp_id)
        lock.write_text("1")  # init/launchd

        assert acquire_lock(project_dir, exp_id) is False
        # Lock untouched.
        assert lock.read_text() == "1"

    def test_dead_pid_lock_treated_as_stale(self, tmp_path: Path) -> None:
        project_dir, exp_id = _exp_dir(tmp_path)
        lock = _lock_path(project_dir, exp_id)
        # PID 99999999 is implausibly large — definitely not alive.
        lock.write_text("99999999")

        assert acquire_lock(project_dir, exp_id) is True
        assert lock.read_text().strip() == str(os.getpid())


class TestStartSessionErrorMessage:
    def test_message_mentions_unlock_command(self, tmp_path: Path) -> None:
        """Pre-K the message was just 'Experiment X is already
        running' — users had no recovery path. The new message
        points at ``urika unlock``."""
        project_dir, exp_id = _exp_dir(tmp_path)
        lock = _lock_path(project_dir, exp_id)
        lock.write_text("1")  # init — always alive

        with pytest.raises(RuntimeError) as exc_info:
            start_session(project_dir, exp_id)

        msg = str(exc_info.value)
        assert "urika unlock" in msg
        assert exp_id in msg


class TestUrikaUnlockCommand:
    """The new ``urika unlock`` CLI surface."""

    def test_unlock_clears_lock_with_dead_pid(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When the lock points at a definitely-dead PID, --force
        isn't required; the safety check passes through."""
        from click.testing import CliRunner

        from urika.cli import cli
        from urika.core.models import ProjectConfig
        from urika.core.workspace import create_project_workspace
        from urika.core.experiment import create_experiment
        from urika.core.registry import ProjectRegistry

        monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
        project_dir = tmp_path / "myproj"
        config = ProjectConfig(
            name="myproj",
            question="q",
            mode="exploratory",
            data_paths=[],
        )
        create_project_workspace(project_dir, config)
        ProjectRegistry().register("myproj", project_dir)
        exp = create_experiment(project_dir, name="baseline", hypothesis="h")

        # Plant a lock with a dead PID.
        lock = _lock_path(project_dir, exp.experiment_id)
        lock.write_text("99999999")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["unlock", "myproj", exp.experiment_id]
        )
        assert result.exit_code == 0, result.output
        assert "Unlocked" in result.output
        assert not lock.exists()

    def test_unlock_refuses_live_pid_without_force(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When the PID is alive (init = 1) the command refuses
        unless --force is passed."""
        from click.testing import CliRunner

        from urika.cli import cli
        from urika.core.models import ProjectConfig
        from urika.core.workspace import create_project_workspace
        from urika.core.experiment import create_experiment
        from urika.core.registry import ProjectRegistry

        monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
        project_dir = tmp_path / "myproj"
        config = ProjectConfig(
            name="myproj",
            question="q",
            mode="exploratory",
            data_paths=[],
        )
        create_project_workspace(project_dir, config)
        ProjectRegistry().register("myproj", project_dir)
        exp = create_experiment(project_dir, name="baseline", hypothesis="h")

        lock = _lock_path(project_dir, exp.experiment_id)
        lock.write_text("1")  # init/launchd

        runner = CliRunner()
        result = runner.invoke(
            cli, ["unlock", "myproj", exp.experiment_id]
        )
        # /proc/1/comm on Linux is "systemd" or similar — not Urika —
        # so the command should refuse but instructively.
        assert result.exit_code != 0
        assert lock.exists()
        # The output should explain the situation.
        assert "ALIVE" in result.output or "alive" in result.output.lower()

    def test_unlock_force_overrides_live_pid(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from click.testing import CliRunner

        from urika.cli import cli
        from urika.core.models import ProjectConfig
        from urika.core.workspace import create_project_workspace
        from urika.core.experiment import create_experiment
        from urika.core.registry import ProjectRegistry

        monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
        project_dir = tmp_path / "myproj"
        config = ProjectConfig(
            name="myproj",
            question="q",
            mode="exploratory",
            data_paths=[],
        )
        create_project_workspace(project_dir, config)
        ProjectRegistry().register("myproj", project_dir)
        exp = create_experiment(project_dir, name="baseline", hypothesis="h")

        lock = _lock_path(project_dir, exp.experiment_id)
        lock.write_text("1")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["unlock", "myproj", exp.experiment_id, "--force"]
        )
        assert result.exit_code == 0, result.output
        assert not lock.exists()


def teardown_module(_module) -> None:
    """Final cleanup: ensure no test left a stray lock around."""
    pass
