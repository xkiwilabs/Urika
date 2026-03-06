"""Tests for session management."""

from __future__ import annotations

from urika.core.models import SessionState


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
