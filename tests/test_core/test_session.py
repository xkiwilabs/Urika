"""Tests for session management."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig, SessionState
from urika.core.session import (
    _lock_path,
    acquire_lock,
    complete_session,
    fail_session,
    get_active_experiment,
    is_locked,
    load_session,
    pause_session,
    record_agent_session,
    release_lock,
    resume_session,
    save_session,
    start_session,
    stop_session,
    update_turn,
)
from urika.core.workspace import create_project_workspace


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test"
    config = ProjectConfig(name="test", question="?", mode="exploratory")
    create_project_workspace(d, config)
    return d


@pytest.fixture
def experiment_id(project_dir: Path) -> str:
    exp = create_experiment(project_dir, name="Test", hypothesis="Test hypothesis")
    return exp.experiment_id


class TestSessionState:
    def test_create_with_required_fields(self) -> None:
        state = SessionState(
            experiment_id="exp-001-baseline",
            status="running",
            started_at="2026-03-06T10:00:00+00:00",
        )
        assert state.experiment_id == "exp-001-baseline"
        assert state.status == "running"
        assert state.started_at == "2026-03-06T10:00:00+00:00"
        assert state.paused_at is None
        assert state.completed_at is None
        assert state.current_turn == 0
        assert state.max_turns is None
        assert state.agent_sessions == {}
        assert state.checkpoint == {}

    def test_create_with_all_fields(self) -> None:
        state = SessionState(
            experiment_id="exp-002",
            status="paused",
            started_at="2026-03-06T10:00:00+00:00",
            paused_at="2026-03-06T11:00:00+00:00",
            current_turn=15,
            max_turns=50,
            agent_sessions={"task_agent": "sess-abc123"},
            checkpoint={"last_suggestion": "try_xgboost"},
        )
        assert state.paused_at == "2026-03-06T11:00:00+00:00"
        assert state.current_turn == 15
        assert state.max_turns == 50
        assert state.agent_sessions["task_agent"] == "sess-abc123"
        assert state.checkpoint["last_suggestion"] == "try_xgboost"

    def test_to_dict(self) -> None:
        state = SessionState(
            experiment_id="exp-001",
            status="running",
            started_at="2026-03-06T10:00:00+00:00",
        )
        d = state.to_dict()
        assert d["experiment_id"] == "exp-001"
        assert d["status"] == "running"
        assert d["current_turn"] == 0
        assert d["agent_sessions"] == {}

    def test_from_dict(self) -> None:
        d = {
            "experiment_id": "exp-001",
            "status": "paused",
            "started_at": "2026-03-06T10:00:00+00:00",
            "paused_at": "2026-03-06T11:00:00+00:00",
            "current_turn": 5,
            "max_turns": 20,
            "agent_sessions": {"evaluator": "sess-xyz"},
            "checkpoint": {},
        }
        state = SessionState.from_dict(d)
        assert state.experiment_id == "exp-001"
        assert state.status == "paused"
        assert state.current_turn == 5
        assert state.agent_sessions["evaluator"] == "sess-xyz"

    def test_from_dict_with_defaults(self) -> None:
        d = {
            "experiment_id": "exp-001",
            "status": "running",
            "started_at": "2026-03-06T10:00:00+00:00",
        }
        state = SessionState.from_dict(d)
        assert state.paused_at is None
        assert state.completed_at is None
        assert state.current_turn == 0
        assert state.max_turns is None
        assert state.agent_sessions == {}
        assert state.checkpoint == {}


class TestLoadSaveSession:
    def test_load_nonexistent_returns_none(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        assert load_session(project_dir, experiment_id) is None

    def test_save_and_load_roundtrip(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        state = SessionState(
            experiment_id=experiment_id,
            status="running",
            started_at="2026-03-06T10:00:00+00:00",
            current_turn=3,
            agent_sessions={"task_agent": "sess-abc"},
        )
        save_session(project_dir, experiment_id, state)
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.experiment_id == experiment_id
        assert loaded.status == "running"
        assert loaded.current_turn == 3
        assert loaded.agent_sessions["task_agent"] == "sess-abc"

    def test_save_overwrites_previous(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        state1 = SessionState(
            experiment_id=experiment_id,
            status="running",
            started_at="2026-03-06T10:00:00+00:00",
        )
        save_session(project_dir, experiment_id, state1)

        state2 = SessionState(
            experiment_id=experiment_id,
            status="paused",
            started_at="2026-03-06T10:00:00+00:00",
            paused_at="2026-03-06T11:00:00+00:00",
        )
        save_session(project_dir, experiment_id, state2)

        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.status == "paused"


class TestLocking:
    def test_acquire_lock(self, project_dir: Path, experiment_id: str) -> None:
        assert acquire_lock(project_dir, experiment_id) is True
        assert is_locked(project_dir, experiment_id) is True

    def test_acquire_lock_twice_in_same_process_is_idempotent(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        """A second acquire from the same process succeeds — the lock
        already contains our PID. This is what makes the dashboard
        handoff work: spawn_experiment_run pre-writes the lock with
        the subprocess's PID, then the subprocess's own acquire_lock
        sees its own PID and treats it as already owned."""
        assert acquire_lock(project_dir, experiment_id) is True
        assert acquire_lock(project_dir, experiment_id) is True

    def test_acquire_lock_blocks_when_other_live_process_owns_it(
        self, project_dir: Path, experiment_id: str, monkeypatch
    ) -> None:
        """Pre-seed the lock with another live PID. acquire_lock must
        refuse — that's a real cross-process conflict."""
        import os
        from urika.core.session import _lock_path

        # Use a real different live PID — PPID (the test runner's parent
        # process) is guaranteed to exist and is not us.
        ppid = os.getppid()
        if ppid == os.getpid() or ppid == 0:
            # Edge case (init process or same-as-self) — fall back to a
            # fake live-pid stub.
            monkeypatch.setattr(os, "kill", lambda pid, sig: None)
            other_pid = 99999998
        else:
            other_pid = ppid

        _lock_path(project_dir, experiment_id).write_text(str(other_pid))
        assert acquire_lock(project_dir, experiment_id) is False

    def test_acquire_lock_clears_stale_lock_with_dead_pid(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        """A lock containing a dead PID is stale — acquire_lock cleans
        it up and succeeds."""
        from urika.core.session import _lock_path

        _lock_path(project_dir, experiment_id).write_text("99999998")
        assert acquire_lock(project_dir, experiment_id) is True

    def test_release_lock(self, project_dir: Path, experiment_id: str) -> None:
        acquire_lock(project_dir, experiment_id)
        release_lock(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is False

    def test_release_nonexistent_lock_is_safe(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        release_lock(project_dir, experiment_id)  # Should not raise

    def test_is_locked_when_no_lock(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        assert is_locked(project_dir, experiment_id) is False


class TestStartSession:
    def test_start_creates_session(self, project_dir: Path, experiment_id: str) -> None:
        state = start_session(project_dir, experiment_id)
        assert state.status == "running"
        assert state.experiment_id == experiment_id
        assert state.current_turn == 0
        assert state.started_at != ""

    def test_start_acquires_lock(self, project_dir: Path, experiment_id: str) -> None:
        start_session(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is True

    def test_start_with_max_turns(self, project_dir: Path, experiment_id: str) -> None:
        state = start_session(project_dir, experiment_id, max_turns=50)
        assert state.max_turns == 50

    def test_start_persists_to_disk(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.status == "running"

    def test_start_raises_if_locked_by_other_process(
        self, project_dir: Path, experiment_id: str, monkeypatch
    ) -> None:
        """A pre-existing lock owned by ANOTHER live process blocks
        ``start_session``. Same-process re-start is now idempotent at
        the lock layer (covered by the acquire_lock idempotency test);
        cross-process conflicts still raise."""
        from urika.core.session import _lock_path

        import os

        ppid = os.getppid()
        if ppid == os.getpid() or ppid == 0:
            monkeypatch.setattr(os, "kill", lambda pid, sig: None)
            other_pid = 99999998
        else:
            other_pid = ppid

        _lock_path(project_dir, experiment_id).parent.mkdir(
            parents=True, exist_ok=True
        )
        _lock_path(project_dir, experiment_id).write_text(str(other_pid))
        with pytest.raises(RuntimeError, match="already running"):
            start_session(project_dir, experiment_id)


class TestPauseSession:
    def test_pause_updates_status(self, project_dir: Path, experiment_id: str) -> None:
        start_session(project_dir, experiment_id)
        state = pause_session(project_dir, experiment_id)
        assert state.status == "paused"
        assert state.paused_at is not None

    def test_pause_releases_lock(self, project_dir: Path, experiment_id: str) -> None:
        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is False

    def test_pause_persists_to_disk(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.status == "paused"


class TestResumeSession:
    def test_resume_updates_status(self, project_dir: Path, experiment_id: str) -> None:
        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)
        state = resume_session(project_dir, experiment_id)
        assert state.status == "running"

    def test_resume_acquires_lock(self, project_dir: Path, experiment_id: str) -> None:
        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)
        resume_session(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is True

    def test_resume_preserves_turn_count(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        state = load_session(project_dir, experiment_id)
        assert state is not None
        state.current_turn = 10
        save_session(project_dir, experiment_id, state)
        pause_session(project_dir, experiment_id)
        resumed = resume_session(project_dir, experiment_id)
        assert resumed.current_turn == 10

    def test_resume_raises_if_running_by_other_process(
        self, project_dir: Path, experiment_id: str, monkeypatch
    ) -> None:
        """Resume from a different process is blocked by a live
        cross-process lock. (Same-process resume is idempotent at the
        lock layer — see TestLocking.)"""
        from urika.core.session import _lock_path

        import os

        # Set up a stopped session so resume has something to resume.
        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)

        # Now seed a lock owned by another live PID.
        ppid = os.getppid()
        if ppid == os.getpid() or ppid == 0:
            monkeypatch.setattr(os, "kill", lambda pid, sig: None)
            other_pid = 99999998
        else:
            other_pid = ppid

        _lock_path(project_dir, experiment_id).write_text(str(other_pid))
        with pytest.raises(RuntimeError, match="already running"):
            resume_session(project_dir, experiment_id)

    def test_resume_raises_if_no_session(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        with pytest.raises(FileNotFoundError, match="No session"):
            resume_session(project_dir, experiment_id)

    def test_resume_completed_session_raises(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        """Cannot resume a completed session."""
        start_session(project_dir, experiment_id)
        complete_session(project_dir, experiment_id)
        with pytest.raises(RuntimeError, match="Cannot resume"):
            resume_session(project_dir, experiment_id)


class TestCompleteSession:
    def test_complete_updates_status(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        state = complete_session(project_dir, experiment_id)
        assert state.status == "completed"
        assert state.completed_at is not None

    def test_complete_releases_lock(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        complete_session(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is False


class TestFailSession:
    def test_fail_updates_status(self, project_dir: Path, experiment_id: str) -> None:
        start_session(project_dir, experiment_id)
        state = fail_session(project_dir, experiment_id, error="Out of memory")
        assert state.status == "failed"
        assert state.completed_at is not None
        assert state.checkpoint.get("error") == "Out of memory"

    def test_fail_releases_lock(self, project_dir: Path, experiment_id: str) -> None:
        start_session(project_dir, experiment_id)
        fail_session(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is False

    def test_fail_without_error_message(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        state = fail_session(project_dir, experiment_id)
        assert state.status == "failed"
        assert "error" not in state.checkpoint


class TestStopSession:
    """Coverage for stop_session, including the v0.4.1 fix that
    refuses to downgrade a terminal status."""

    def test_stop_marks_running_session_as_stopped(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        state = stop_session(project_dir, experiment_id, reason="Stopped by user")
        assert state.status == "stopped"
        assert state.completed_at is not None
        assert state.checkpoint.get("reason") == "Stopped by user"
        assert is_locked(project_dir, experiment_id) is False

    def test_stop_does_not_downgrade_completed_session(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        """Regression (v0.4.1): a SIGTERM from the dashboard's Stop
        button arriving AFTER ``complete_session`` had already run
        used to overwrite ``completed`` with ``stopped`` and exit 1,
        making a successful run look like a failure. The success
        metrics on disk (``progress.json``) showed the run was good
        but the session card flipped to stopped.
        """
        start_session(project_dir, experiment_id)
        complete_session(project_dir, experiment_id)
        # Now SIGTERM arrives during _generate_reports.
        state = stop_session(
            project_dir, experiment_id, reason="Stopped by user"
        )
        assert state.status == "completed", (
            "stop_session must NOT downgrade an already-completed session"
        )
        # The reason gets recorded as a side note so dashboards can
        # distinguish a clean finish from a stopped-during-narrative
        # run when they want to.
        assert (
            state.checkpoint.get("post_terminal_stop_reason") == "Stopped by user"
        )
        # Lock is released either way so future runs aren't blocked.
        assert is_locked(project_dir, experiment_id) is False

    def test_stop_does_not_downgrade_failed_session(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        """A failure should not be silently rewritten as a stop, even
        if SIGTERM arrives during cleanup."""
        start_session(project_dir, experiment_id)
        fail_session(project_dir, experiment_id, error="boom")
        state = stop_session(project_dir, experiment_id)
        assert state.status == "failed"

    def test_stop_is_idempotent_on_already_stopped(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        """Calling stop twice in a row must not crash and must keep
        the original ``stopped`` state."""
        start_session(project_dir, experiment_id)
        stop_session(project_dir, experiment_id, reason="first")
        state = stop_session(project_dir, experiment_id, reason="second")
        assert state.status == "stopped"


class TestUpdateTurn:
    def test_increments_turn(self, project_dir: Path, experiment_id: str) -> None:
        start_session(project_dir, experiment_id)
        state = update_turn(project_dir, experiment_id)
        assert state.current_turn == 1

    def test_increments_multiple_times(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        update_turn(project_dir, experiment_id)
        update_turn(project_dir, experiment_id)
        state = update_turn(project_dir, experiment_id)
        assert state.current_turn == 3

    def test_persists_to_disk(self, project_dir: Path, experiment_id: str) -> None:
        start_session(project_dir, experiment_id)
        update_turn(project_dir, experiment_id)
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.current_turn == 1


class TestRecordAgentSession:
    def test_record_agent_session(self, project_dir: Path, experiment_id: str) -> None:
        start_session(project_dir, experiment_id)
        record_agent_session(project_dir, experiment_id, "task_agent", "sess-abc")
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.agent_sessions["task_agent"] == "sess-abc"

    def test_record_multiple_agents(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        record_agent_session(project_dir, experiment_id, "task_agent", "sess-1")
        record_agent_session(project_dir, experiment_id, "evaluator", "sess-2")
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert len(loaded.agent_sessions) == 2

    def test_record_overwrites_same_role(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        record_agent_session(project_dir, experiment_id, "task_agent", "sess-old")
        record_agent_session(project_dir, experiment_id, "task_agent", "sess-new")
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.agent_sessions["task_agent"] == "sess-new"


class TestGetActiveExperiment:
    def test_no_active_experiment(self, project_dir: Path) -> None:
        assert get_active_experiment(project_dir) is None

    def test_finds_active_experiment(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        active = get_active_experiment(project_dir)
        assert active == experiment_id

    def test_no_active_after_pause(self, project_dir: Path, experiment_id: str) -> None:
        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)
        assert get_active_experiment(project_dir) is None

    def test_no_active_after_complete(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        complete_session(project_dir, experiment_id)
        assert get_active_experiment(project_dir) is None


class TestStaleLockDetection:
    def test_stale_lock_cleaned(self, tmp_path: Path) -> None:
        """Stale lock from dead process is cleaned up."""
        lock = _lock_path(tmp_path, "exp-001")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("99999999")  # Non-existent PID
        # Should acquire because PID 99999999 is dead
        assert acquire_lock(tmp_path, "exp-001") is True

    def test_live_lock_from_other_process_blocks(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A lock owned by ANOTHER live process blocks acquisition.
        Same-process locks are idempotent (TestLocking covers that)."""
        import os

        ppid = os.getppid()
        if ppid == os.getpid() or ppid == 0:
            monkeypatch.setattr(os, "kill", lambda pid, sig: None)
            other_pid = 99999998
        else:
            other_pid = ppid

        lock = _lock_path(tmp_path, "exp-001")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(other_pid))
        assert acquire_lock(tmp_path, "exp-001") is False

    def test_live_lock_with_own_pid_is_idempotent(self, tmp_path: Path) -> None:
        """The dashboard handoff case: spawn helper writes the lock with
        the subprocess's PID, then the subprocess's own acquire_lock
        sees its own PID and treats the lock as already owned."""
        import os

        lock = _lock_path(tmp_path, "exp-001")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()))
        assert acquire_lock(tmp_path, "exp-001") is True

    def test_lock_writes_pid(self, tmp_path: Path) -> None:
        """New lock files contain the PID."""
        import os

        lock = _lock_path(tmp_path, "exp-001")
        lock.parent.mkdir(parents=True, exist_ok=True)
        assert acquire_lock(tmp_path, "exp-001") is True
        assert lock.read_text().strip() == str(os.getpid())
