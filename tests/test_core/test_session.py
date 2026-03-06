"""Tests for session management."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig, SessionState
from urika.core.session import (
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

    def test_acquire_lock_twice_fails(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        acquire_lock(project_dir, experiment_id)
        assert acquire_lock(project_dir, experiment_id) is False

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

    def test_start_raises_if_locked(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
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

    def test_resume_raises_if_locked(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        with pytest.raises(RuntimeError, match="already running"):
            resume_session(project_dir, experiment_id)

    def test_resume_raises_if_no_session(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        with pytest.raises(FileNotFoundError, match="No session"):
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
