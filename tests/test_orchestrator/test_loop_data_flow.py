"""Data-flow contract — the orchestrator loop concatenates
``data_agent.text_output`` and (when invoked) ``literature_agent.text_output``
into the task_agent's prompt input. A silent break in that
concatenation would let the task agent run blind without the upstream
agents' work, and currently no test pins it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace
from urika.orchestrator.loop import run_experiment


_PLAN_PROSE = """```json
{"method_name": "x", "steps": ["a"], "needs_literature": true,
 "literature_query": "Cohen d effect-size methods"}
```"""
_PLAN_NO_LIT = '```json\n{"method_name": "x", "steps": ["a"]}\n```'
_GOOD_TASK = (
    '```json\n{"run_id": "r1", "method": "x", "params": {}, '
    '"metrics": {"r2": 0.8}}\n```'
)
_EVAL_MET = '```json\n{"criteria_met": true}\n```'
_SUGG = '```json\n{"suggestions": [{"name": "n", "method": "m"}]}\n```'


class _Recorder(AgentRunner):
    """Records the prompt text passed to each agent."""

    def __init__(self, by_role: dict[str, str]):
        self._by_role = by_role
        self.calls: list[tuple[str, str]] = []

    async def run(
        self, config: AgentConfig, prompt: str, *, on_message=None
    ) -> AgentResult:
        name = config.name
        self.calls.append((name, prompt))
        text = self._by_role.get(name, "")
        return AgentResult(
            success=True,
            messages=[],
            text_output=text,
            session_id="s",
            num_turns=1,
            duration_ms=1,
        )


def _setup_hybrid(tmp_path: Path) -> tuple[Path, str]:
    proj = tmp_path / "p"
    create_project_workspace(
        proj,
        ProjectConfig(name="p", question="Q?", mode="exploratory"),
    )
    # Flip to hybrid mode so the data_agent runs, AND define an inline
    # ``[privacy.endpoints.private]`` so ``build_agent_env_for_endpoint``
    # resolves cleanly without depending on a global
    # ``~/.urika/settings.toml``. Pre-fix the fixture only set
    # ``mode = "hybrid"`` and the test silently relied on the dev's
    # global config — passing locally but raising
    # ``MissingPrivateEndpointError`` on every CI runner.
    toml = proj / "urika.toml"
    toml.write_text(
        toml.read_text()
        + "\n"
        + '[privacy]\nmode = "hybrid"\n'
        + "[privacy.endpoints.private]\n"
        + 'base_url = "http://localhost:11434"\n'
        + 'default_model = "test-model"\n'
    )
    exp = create_experiment(proj, name="b", hypothesis="h")
    return proj, exp.experiment_id


@pytest.mark.asyncio
async def test_data_agent_output_concatenated_into_task_input(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "urika.core.privacy.requires_private_endpoint", lambda *_a, **_k: False
    )
    proj, exp = _setup_hybrid(tmp_path)
    data_marker = "DATA_AGENT_FEATURES_OUTPUT_GOES_HERE"
    runner = _Recorder(
        {
            "planning_agent": _PLAN_NO_LIT,
            "data_agent": data_marker,
            "task_agent": _GOOD_TASK,
            "evaluator": _EVAL_MET,
            "advisor_agent": _SUGG,
        }
    )
    await run_experiment(proj, exp, runner, max_turns=2)
    # Find the task_agent prompt and assert it contains the data marker.
    task_prompts = [p for (name, p) in runner.calls if name == "task_agent"]
    assert task_prompts, "task_agent was never called"
    assert any(data_marker in p for p in task_prompts), (
        "data_agent.text_output did not reach the task_agent prompt — "
        "the loop.py:448-449 concatenation is broken"
    )


@pytest.mark.asyncio
async def test_literature_agent_output_concatenated_when_plan_requests(
    tmp_path: Path,
) -> None:
    """When the planning agent's method_plan sets ``needs_literature=true``,
    the literature_agent runs and its output is concatenated into the
    task_agent's prompt (loop.py:373-377)."""
    proj = tmp_path / "lit"
    create_project_workspace(
        proj, ProjectConfig(name="lit", question="Q?", mode="exploratory")
    )
    exp = create_experiment(proj, name="b", hypothesis="h")
    lit_marker = "LIT_RESEARCH_FINDINGS_HERE"
    runner = _Recorder(
        {
            "planning_agent": _PLAN_PROSE,  # has needs_literature: true
            "literature_agent": lit_marker,
            "task_agent": _GOOD_TASK,
            "evaluator": _EVAL_MET,
            "advisor_agent": _SUGG,
        }
    )
    # Seed a knowledge entry so the literature_agent path is reachable.
    (proj / "knowledge").mkdir(exist_ok=True)
    (proj / "knowledge" / "notes.md").write_text("# notes\nrelevant prior work")
    await run_experiment(proj, exp.experiment_id, runner, max_turns=2)
    task_prompts = [p for (name, p) in runner.calls if name == "task_agent"]
    assert task_prompts
    assert any(lit_marker in p for p in task_prompts), (
        "literature_agent.text_output did not reach the task_agent prompt"
    )


@pytest.mark.asyncio
async def test_no_literature_when_plan_does_not_request_it(tmp_path: Path) -> None:
    """Sanity guard: a method plan without ``needs_literature`` does
    NOT call the literature_agent inside the turn (only the up-front
    knowledge scan at loop.py:191 if knowledge dir is populated)."""
    proj = tmp_path / "noplit"
    create_project_workspace(
        proj, ProjectConfig(name="noplit", question="?", mode="exploratory")
    )
    exp = create_experiment(proj, name="b", hypothesis="h")
    runner = _Recorder(
        {
            "planning_agent": _PLAN_NO_LIT,
            "task_agent": _GOOD_TASK,
            "evaluator": _EVAL_MET,
            "advisor_agent": _SUGG,
        }
    )
    await run_experiment(proj, exp, runner, max_turns=1)
    # The literature agent may be called for the up-front knowledge
    # scan if knowledge dir exists & is non-empty — here it's absent,
    # so no literature_agent call inside the turn.
    role_calls = [name for (name, _p) in runner.calls]
    # The per-turn literature path (i.e. driven by the plan) is NOT
    # entered. Up-front scan is guarded by the knowledge-dir-non-empty
    # check; either way, we should see at most one literature_agent
    # call (the up-front scan), not multiple.
    assert role_calls.count("literature_agent") <= 1
