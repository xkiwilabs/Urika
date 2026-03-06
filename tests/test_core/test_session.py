"""Tests for session management."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig, SessionState
from urika.core.session import (
    acquire_lock,
    is_locked,
    load_session,
    release_lock,
    save_session,
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
