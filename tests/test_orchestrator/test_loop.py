"""Tests for the orchestrator loop."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig, RunRecord
from urika.core.progress import append_run, load_progress
from urika.core.session import load_session, pause_session, start_session, update_turn
from urika.core.workspace import create_project_workspace
from urika.orchestrator.loop import run_experiment


# --- Canned agent responses ---

_TASK_OUTPUT = """\
I ran a linear regression model. Here are the results:
```json
{
    "run_id": "run-001",
    "method": "linear_regression",
    "params": {"alpha": 0.01},
    "metrics": {"rmse": 0.42, "r2": 0.87}
}
```
"""

_EVAL_CRITERIA_MET = """\
The model meets the success criteria.
```json
{
    "criteria_met": true,
    "score": 0.87,
    "reasoning": "R2 exceeds 0.8 threshold"
}
```
"""

_EVAL_CRITERIA_NOT_MET = """\
The model does not yet meet criteria.
```json
{
    "criteria_met": false,
    "score": 0.42,
    "reasoning": "R2 below 0.8 threshold"
}
```
"""

_SUGGESTION = """\
Try a different approach:
```json
{
    "suggestions": [
        {"method": "random_forest", "rationale": "Non-linear may fit better"}
    ],
    "needs_tool": false
}
```
"""

_LITERATURE_OUTPUT = """\
I scanned the knowledge directory and found existing entries.
```json
{
    "ingested": [],
    "total_entries": 1,
    "relevant_findings": [
        {"source": "notes.txt", "summary": "Notes about regression"}
    ]
}
```
"""


# --- FakeRunner ---


class FakeRunner(AgentRunner):
    def __init__(self, responses: dict[str, list[str]]):
        self._responses = responses
        self._call_counts: dict[str, int] = {}

    async def run(
        self, config: AgentConfig, prompt: str, *, on_message: object = None
    ) -> AgentResult:
        role = config.name
        self._call_counts[role] = self._call_counts.get(role, 0) + 1
        idx = self._call_counts[role] - 1
        texts = self._responses.get(role, [""])
        text = texts[idx] if idx < len(texts) else texts[-1]
        return AgentResult(
            success=True,
            messages=[],
            text_output=text,
            session_id=f"session-{role}-{idx}",
            num_turns=1,
            duration_ms=100,
        )


class FailingRunner(AgentRunner):
    """Runner that returns success=False for a specific role."""

    def __init__(self, fail_role: str):
        self._fail_role = fail_role

    async def run(
        self, config: AgentConfig, prompt: str, *, on_message: object = None
    ) -> AgentResult:
        if config.name == self._fail_role:
            return AgentResult(
                success=False,
                messages=[],
                text_output="",
                session_id="session-fail",
                num_turns=0,
                duration_ms=0,
                error=f"{config.name} encountered an error",
            )
        return AgentResult(
            success=True,
            messages=[],
            text_output=_TASK_OUTPUT,
            session_id=f"session-{config.name}",
            num_turns=1,
            duration_ms=100,
        )


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


# --- Tests ---


class TestOrchestratorLoop:
    @pytest.mark.asyncio
    async def test_completes_when_criteria_met(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(project_dir, exp_id, runner, max_turns=5)

        assert result["status"] == "completed"
        assert result["turns"] == 1

    @pytest.mark.asyncio
    async def test_stops_at_max_turns(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_NOT_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(project_dir, exp_id, runner, max_turns=3)

        assert result["status"] == "completed"
        assert result["turns"] == 3

    @pytest.mark.asyncio
    async def test_records_runs_to_progress(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        await run_experiment(project_dir, exp_id, runner, max_turns=5)

        progress = load_progress(project_dir, exp_id)
        assert len(progress["runs"]) == 1
        assert progress["runs"][0]["run_id"] == "run-001"
        assert progress["runs"][0]["method"] == "linear_regression"

    @pytest.mark.asyncio
    async def test_session_state_updated(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        await run_experiment(project_dir, exp_id, runner, max_turns=5)

        session = load_session(project_dir, exp_id)
        assert session is not None
        assert session.status == "completed"

    @pytest.mark.asyncio
    async def test_handles_runner_error(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FailingRunner(fail_role="task_agent")

        result = await run_experiment(project_dir, exp_id, runner, max_turns=5)

        assert result["status"] == "failed"
        assert "error" in result

        session = load_session(project_dir, exp_id)
        assert session is not None
        assert session.status == "failed"

    @pytest.mark.asyncio
    async def test_calls_agents_in_order(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        await run_experiment(project_dir, exp_id, runner, max_turns=5)

        # planning_agent, task_agent, and evaluator should have been called
        assert runner._call_counts.get("planning_agent", 0) >= 1
        assert runner._call_counts.get("task_agent", 0) >= 1
        assert runner._call_counts.get("evaluator", 0) >= 1

    @pytest.mark.asyncio
    async def test_multiple_turns(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [
                    _EVAL_CRITERIA_NOT_MET,
                    _EVAL_CRITERIA_NOT_MET,
                    _EVAL_CRITERIA_MET,
                ],
                "advisor_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(project_dir, exp_id, runner, max_turns=10)

        assert result["status"] == "completed"
        assert result["turns"] == 3


_PLAN_OUTPUT = """\
Here is the method plan:
```json
{
    "method_name": "rf_pipeline",
    "steps": [
        {"step": 1, "action": "profile data", "tool": "data_profiler"},
        {"step": 2, "action": "fit random forest"}
    ],
    "evaluation": {"strategy": "10-fold CV"},
    "needs_tool": false
}
```
"""


class TestPlanningAgent:
    @pytest.mark.asyncio
    async def test_planning_agent_called_before_task_agent(
        self, tmp_path: Path
    ) -> None:
        """When planning_agent is registered, it runs first and its output
        is passed to task_agent as the prompt."""
        project_dir, exp_id = _setup_project(tmp_path)

        call_order: list[str] = []
        prompts_received: dict[str, list[str]] = {}

        class OrderTrackingRunner(AgentRunner):
            async def run(
                self, config: AgentConfig, prompt: str, *, on_message: object = None
            ) -> AgentResult:
                call_order.append(config.name)
                prompts_received.setdefault(config.name, []).append(prompt)
                responses = {
                    "planning_agent": _PLAN_OUTPUT,
                    "task_agent": _TASK_OUTPUT,
                    "evaluator": _EVAL_CRITERIA_MET,
                    "advisor_agent": _SUGGESTION,
                }
                text = responses.get(config.name, "")
                return AgentResult(
                    success=True,
                    messages=[],
                    text_output=text,
                    session_id=f"session-{config.name}",
                    num_turns=1,
                    duration_ms=100,
                )

        result = await run_experiment(
            project_dir, exp_id, OrderTrackingRunner(), max_turns=5
        )

        assert result["status"] == "completed"
        # Planning agent should be called before task agent
        plan_idx = call_order.index("planning_agent")
        task_idx = call_order.index("task_agent")
        assert plan_idx < task_idx
        # Task agent should receive the planning agent's output
        assert _PLAN_OUTPUT.strip() in prompts_received["task_agent"][0]

    @pytest.mark.asyncio
    async def test_loop_works_without_planning_agent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When planning_agent is NOT registered, task_agent gets the
        original task_prompt directly (backward compatibility)."""
        project_dir, exp_id = _setup_project(tmp_path)

        # Patch discover() to skip planning_agent registration
        from urika.agents.registry import AgentRegistry

        _orig_discover = AgentRegistry.discover

        def _discover_without_planner(self: AgentRegistry) -> None:
            _orig_discover(self)
            self._roles.pop("planning_agent", None)

        monkeypatch.setattr(AgentRegistry, "discover", _discover_without_planner)

        prompts_received: dict[str, list[str]] = {}

        class CapturingRunner(AgentRunner):
            async def run(
                self, config: AgentConfig, prompt: str, *, on_message: object = None
            ) -> AgentResult:
                prompts_received.setdefault(config.name, []).append(prompt)
                responses = {
                    "task_agent": _TASK_OUTPUT,
                    "evaluator": _EVAL_CRITERIA_MET,
                    "advisor_agent": _SUGGESTION,
                }
                text = responses.get(config.name, "")
                return AgentResult(
                    success=True,
                    messages=[],
                    text_output=text,
                    session_id=f"session-{config.name}",
                    num_turns=1,
                    duration_ms=100,
                )

        result = await run_experiment(
            project_dir, exp_id, CapturingRunner(), max_turns=5
        )

        assert result["status"] == "completed"
        # planning_agent should NOT have been called
        assert "planning_agent" not in prompts_received
        # task_agent should have received the initial task prompt
        assert "Begin the experiment" in prompts_received["task_agent"][0]


class TestOrchestratorKnowledgeIntegration:
    @pytest.mark.asyncio
    async def test_runs_literature_agent_pre_loop(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)

        # Add knowledge so pre-loop scan has something to find
        knowledge_dir = project_dir / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "notes.txt").write_text("Some research notes.")
        from urika.knowledge import KnowledgeStore

        store = KnowledgeStore(project_dir)
        store.ingest(str(knowledge_dir / "notes.txt"))

        runner = FakeRunner(
            {
                "literature_agent": [_LITERATURE_OUTPUT],
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(project_dir, exp_id, runner, max_turns=5)

        assert result["status"] == "completed"
        assert runner._call_counts.get("literature_agent", 0) >= 1

    @pytest.mark.asyncio
    async def test_skips_literature_when_no_knowledge(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)

        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(project_dir, exp_id, runner, max_turns=5)

        assert result["status"] == "completed"
        assert runner._call_counts.get("literature_agent", 0) == 0

    @pytest.mark.asyncio
    async def test_on_demand_literature_from_plan(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)

        plan_with_lit = """\
Here is the method plan:
```json
{
    "method_name": "rf_pipeline",
    "steps": [
        {"step": 1, "action": "fit random forest"}
    ],
    "needs_tool": false,
    "needs_literature": true,
    "literature_query": "random forest regression best practices"
}
```
"""
        runner = FakeRunner(
            {
                "planning_agent": [plan_with_lit],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_NOT_MET, _EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
                "literature_agent": [_LITERATURE_OUTPUT],
            }
        )

        result = await run_experiment(project_dir, exp_id, runner, max_turns=5)

        assert result["status"] == "completed"
        # Literature agent called on-demand from planning agent
        assert runner._call_counts.get("literature_agent", 0) >= 1


class TestOrchestratorResume:
    @pytest.mark.asyncio
    async def test_resume_calls_resume_session(self, tmp_path: Path) -> None:
        """Start+pause a session, then resume=True succeeds and completes."""
        project_dir, exp_id = _setup_project(tmp_path)

        # Start and pause the session to create a resumable state
        start_session(project_dir, exp_id, max_turns=5)
        pause_session(project_dir, exp_id)

        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(
            project_dir, exp_id, runner, max_turns=5, resume=True
        )

        assert result["status"] == "completed"
        session = load_session(project_dir, exp_id)
        assert session is not None
        assert session.status == "completed"

    @pytest.mark.asyncio
    async def test_resume_starts_from_current_turn(self, tmp_path: Path) -> None:
        """Resume starts from current_turn+1, result reports correct turn."""
        project_dir, exp_id = _setup_project(tmp_path)

        # Start session, advance turn to 2, then pause
        start_session(project_dir, exp_id, max_turns=10)
        update_turn(project_dir, exp_id)  # turn -> 1
        update_turn(project_dir, exp_id)  # turn -> 2
        pause_session(project_dir, exp_id)

        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(
            project_dir, exp_id, runner, max_turns=10, resume=True
        )

        assert result["status"] == "completed"
        # Should complete on turn 3 (current_turn=2, start at 3)
        assert result["turns"] == 3

    @pytest.mark.asyncio
    async def test_resume_uses_last_suggestion_as_prompt(self, tmp_path: Path) -> None:
        """With a run that has next_step, resume picks it up as task prompt."""
        project_dir, exp_id = _setup_project(tmp_path)

        # Start session, add a run with next_step, then pause
        start_session(project_dir, exp_id, max_turns=5)
        run_record = RunRecord(
            run_id="run-prev",
            method="linear_regression",
            params={"alpha": 0.01},
            metrics={"rmse": 0.5},
            next_step="Try random forest with max_depth=10",
        )
        append_run(project_dir, exp_id, run_record)
        pause_session(project_dir, exp_id)

        prompts_received: list[str] = []

        class CapturingRunner(AgentRunner):
            async def run(
                self, config: AgentConfig, prompt: str, *, on_message: object = None
            ) -> AgentResult:
                prompts_received.append(prompt)
                if config.name == "planning_agent":
                    text = _PLAN_OUTPUT
                elif config.name == "task_agent":
                    text = _TASK_OUTPUT
                elif config.name == "evaluator":
                    text = _EVAL_CRITERIA_MET
                else:
                    text = _SUGGESTION
                return AgentResult(
                    success=True,
                    messages=[],
                    text_output=text,
                    session_id=f"session-{config.name}",
                    num_turns=1,
                    duration_ms=100,
                )

        result = await run_experiment(
            project_dir, exp_id, CapturingRunner(), max_turns=5, resume=True
        )

        assert result["status"] == "completed"
        # The first prompt (to planning_agent) should contain the next_step
        assert "Try random forest with max_depth=10" in prompts_received[0]

    @pytest.mark.asyncio
    async def test_resume_false_is_default(self, tmp_path: Path) -> None:
        """Default behavior (resume=False) still works as before."""
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        # Call without resume kwarg — should work exactly as before
        result = await run_experiment(project_dir, exp_id, runner, max_turns=5)

        assert result["status"] == "completed"
        assert result["turns"] == 1

    @pytest.mark.asyncio
    async def test_resume_with_no_runs_uses_default_prompt(
        self, tmp_path: Path
    ) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        from urika.core.session import start_session, pause_session

        start_session(project_dir, exp_id, max_turns=50)
        pause_session(project_dir, exp_id)

        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        result = await run_experiment(
            project_dir, exp_id, runner, max_turns=50, resume=True
        )
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_resume_respects_stored_max_turns(self, tmp_path: Path) -> None:
        project_dir, exp_id = _setup_project(tmp_path)
        from urika.core.session import start_session, pause_session, update_turn

        start_session(project_dir, exp_id, max_turns=3)
        update_turn(project_dir, exp_id)  # turn 1
        update_turn(project_dir, exp_id)  # turn 2
        pause_session(project_dir, exp_id)

        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_NOT_MET, _EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        # Pass max_turns=50, but stored max_turns=3 should win
        result = await run_experiment(
            project_dir, exp_id, runner, max_turns=50, resume=True
        )
        assert result["status"] == "completed"
        assert result["turns"] == 3  # max_turns=3 from stored session

    @pytest.mark.asyncio
    async def test_resume_on_non_paused_session_fails(self, tmp_path: Path) -> None:
        """Resuming with no session returns failed."""
        project_dir, exp_id = _setup_project(tmp_path)

        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION],
            }
        )

        # No session exists, resume should fail
        result = await run_experiment(
            project_dir, exp_id, runner, max_turns=5, resume=True
        )

        assert result["status"] == "failed"
        assert "error" in result


_SUGGESTION_WITH_CRITERIA = """\
Try a different approach:
```json
{
    "suggestions": [
        {"method": "random_forest", "rationale": "Non-linear may fit better"}
    ],
    "needs_tool": false,
    "criteria_update": {
        "criteria": {"primary_metric": "r2", "threshold": 0.9},
        "rationale": "Raising threshold after strong baseline"
    }
}
```
"""


class TestCriteriaUpdateFromSuggestions:
    @pytest.mark.asyncio
    async def test_criteria_update_written_from_suggestions(
        self, tmp_path: Path
    ) -> None:
        """When suggestion agent output includes criteria_update,
        the orchestrator writes it to criteria.json."""
        project_dir, exp_id = _setup_project(tmp_path)
        runner = FakeRunner(
            {
                "planning_agent": [_PLAN_OUTPUT],
                "task_agent": [_TASK_OUTPUT],
                "evaluator": [_EVAL_CRITERIA_NOT_MET, _EVAL_CRITERIA_MET],
                "advisor_agent": [_SUGGESTION_WITH_CRITERIA],
            }
        )

        result = await run_experiment(project_dir, exp_id, runner, max_turns=5)

        assert result["status"] == "completed"

        import json

        criteria_path = project_dir / "criteria.json"
        assert criteria_path.exists(), "criteria.json should have been created"

        data = json.loads(criteria_path.read_text())
        versions = data.get("versions", [])
        assert len(versions) >= 1
        latest = versions[-1]
        assert latest["set_by"] == "advisor_agent"
        assert latest["criteria"]["primary_metric"] == "r2"
        assert latest["criteria"]["threshold"] == 0.9
        assert latest["rationale"] == "Raising threshold after strong baseline"
