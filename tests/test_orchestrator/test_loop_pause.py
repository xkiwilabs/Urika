"""Tests for pause/stop integration with the orchestrator loop and session management."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig
from urika.core.session import (
    load_session,
    pause_session,
    start_session,
    stop_session,
)
from urika.core.workspace import create_project_workspace
from urika.orchestrator.loop import run_experiment
from urika.orchestrator.pause import PauseController


# --- Helpers ---


def _setup_project(tmp_path: Path) -> tuple[Path, str]:
    config = ProjectConfig(
        name="test-proj",
        question="Does X predict Y?",
        mode="exploratory",
        data_paths=[],
    )
    project_dir = tmp_path / "test-proj"
    create_project_workspace(project_dir, config)
    exp = create_experiment(project_dir, name="baseline", hypothesis="Linear is enough")
    return project_dir, exp.experiment_id


class NeverCalledRunner(AgentRunner):
    """Runner that fails if any agent is actually called."""

    async def run(
        self, config: AgentConfig, prompt: str, *, on_message: object = None
    ) -> AgentResult:
        msg = f"Agent {config.name} should not have been called"
        raise AssertionError(msg)


# --- Tests ---


class TestRunExperimentPause:
    @pytest.mark.asyncio
    async def test_pause_before_first_turn(self, tmp_path: Path) -> None:
        """Pre-set pause flag causes immediate return without running agents."""
        project_dir, exp_id = _setup_project(tmp_path)

        pc = PauseController()
        pc.request_pause()

        result = await run_experiment(
            project_dir,
            exp_id,
            NeverCalledRunner(),
            max_turns=5,
            pause_controller=pc,
        )

        assert result["status"] == "paused"

    @pytest.mark.asyncio
    async def test_pause_returns_correct_status(self, tmp_path: Path) -> None:
        """Verify return dict has status=paused and turns=0 when paused before turn 1."""
        project_dir, exp_id = _setup_project(tmp_path)

        pc = PauseController()
        pc.request_pause()

        result = await run_experiment(
            project_dir,
            exp_id,
            NeverCalledRunner(),
            max_turns=5,
            pause_controller=pc,
        )

        assert result["status"] == "paused"
        assert result["turns"] == 0

    @pytest.mark.asyncio
    async def test_pause_sets_session_to_paused(self, tmp_path: Path) -> None:
        """Session on disk should be 'paused' after a pause."""
        project_dir, exp_id = _setup_project(tmp_path)

        pc = PauseController()
        pc.request_pause()

        await run_experiment(
            project_dir,
            exp_id,
            NeverCalledRunner(),
            max_turns=5,
            pause_controller=pc,
        )

        session = load_session(project_dir, exp_id)
        assert session is not None
        assert session.status == "paused"

    @pytest.mark.asyncio
    async def test_no_pause_controller_runs_normally(self, tmp_path: Path) -> None:
        """Without a pause_controller, the loop runs to completion as before."""
        project_dir, exp_id = _setup_project(tmp_path)

        _TASK_OUTPUT = """\
I ran a linear regression model.
```json
{
    "run_id": "run-001",
    "method": "linear_regression",
    "params": {"alpha": 0.01},
    "metrics": {"rmse": 0.42, "r2": 0.87}
}
```
"""
        _EVAL_MET = """\
Criteria met.
```json
{
    "criteria_met": true,
    "score": 0.87,
    "reasoning": "R2 exceeds threshold"
}
```
"""
        _PLAN = """\
```json
{
    "method_name": "lr",
    "steps": [{"step": 1, "action": "fit"}],
    "needs_tool": false
}
```
"""
        _SUGGESTION = """\
```json
{
    "suggestions": [{"method": "rf", "rationale": "try"}],
    "needs_tool": false
}
```
"""

        class SimpleRunner(AgentRunner):
            async def run(
                self, config: AgentConfig, prompt: str, *, on_message: object = None
            ) -> AgentResult:
                responses = {
                    "planning_agent": _PLAN,
                    "task_agent": _TASK_OUTPUT,
                    "evaluator": _EVAL_MET,
                    "advisor_agent": _SUGGESTION,
                }
                return AgentResult(
                    success=True,
                    messages=[],
                    text_output=responses.get(config.name, ""),
                    session_id=f"session-{config.name}",
                    num_turns=1,
                    duration_ms=100,
                )

        result = await run_experiment(
            project_dir,
            exp_id,
            SimpleRunner(),
            max_turns=5,
            pause_controller=None,
        )

        assert result["status"] == "completed"


class TestStopSession:
    @pytest.fixture
    def project_dir(self, tmp_path: Path) -> Path:
        config = ProjectConfig(name="test", question="?", mode="exploratory")
        d = tmp_path / "test"
        create_project_workspace(d, config)
        return d

    @pytest.fixture
    def experiment_id(self, project_dir: Path) -> str:
        exp = create_experiment(
            project_dir, name="baseline", hypothesis="Test hypothesis"
        )
        return exp.experiment_id

    def test_stop_session_sets_status(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        state = stop_session(project_dir, experiment_id)
        assert state.status == "stopped"
        assert state.completed_at is not None

    def test_stop_session_records_reason(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        state = stop_session(project_dir, experiment_id, reason="User pressed ESC")
        assert state.checkpoint["reason"] == "User pressed ESC"

    def test_stop_session_releases_lock(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        from urika.core.session import is_locked

        start_session(project_dir, experiment_id)
        stop_session(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is False

    def test_stop_session_persists_to_disk(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        stop_session(project_dir, experiment_id)
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.status == "stopped"

    def test_resume_from_stopped(self, project_dir: Path, experiment_id: str) -> None:
        from urika.core.session import resume_session

        start_session(project_dir, experiment_id)
        stop_session(project_dir, experiment_id)
        state = resume_session(project_dir, experiment_id)
        assert state.status == "running"

    def test_resume_from_paused(self, project_dir: Path, experiment_id: str) -> None:
        from urika.core.session import resume_session

        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)
        state = resume_session(project_dir, experiment_id)
        assert state.status == "running"
