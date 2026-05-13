"""Replay realistic agent transcripts through the orchestrator loop.

The canned strings in ``test_loop.py`` are hand-trimmed so they parse
cleanly — they don't exercise prompt/parser drift or "what does prose
around the JSON do". The fixtures in ``tests/fixtures/transcripts/``
are realistic (prose + a fenced ``json`` block using the schema the
prompts ask for, including the optional fields). If a prompt's output
schema and the parsers ever drift apart, replaying these breaks here.

Refresh the corpus from a real ``URIKA_SMOKE_REAL=1`` run when you
change a role's prompt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.core.experiment import create_experiment
from urika.core.method_registry import load_methods
from urika.core.models import ProjectConfig
from urika.core.progress import load_progress
from urika.core.workspace import create_project_workspace
from urika.evaluation.leaderboard import load_leaderboard
from urika.orchestrator.loop import run_experiment
from urika.orchestrator.parsing import (
    parse_evaluation,
    parse_method_plan,
    parse_run_records,
    parse_suggestions,
)

_TRANSCRIPTS = Path(__file__).resolve().parents[1] / "fixtures" / "transcripts"


def _t(name: str) -> str:
    return (_TRANSCRIPTS / name).read_text(encoding="utf-8")


class _TranscriptRunner(AgentRunner):
    """Returns a fixed transcript per role, cycling the list."""

    def __init__(self, by_role: dict[str, list[str]]):
        self._by_role = by_role
        self.calls: dict[str, int] = {}

    async def run(
        self, config: AgentConfig, prompt: str, *, on_message: object = None
    ) -> AgentResult:
        role = config.name
        self.calls[role] = self.calls.get(role, 0) + 1
        texts = self._by_role.get(role, [""])
        text = texts[min(self.calls[role] - 1, len(texts) - 1)]
        return AgentResult(
            success=True,
            messages=[],
            text_output=text,
            session_id=f"s-{role}",
            num_turns=2,
            duration_ms=10,
        )


def _setup(tmp_path: Path) -> tuple[Path, str]:
    project_dir = tmp_path / "proj"
    create_project_workspace(
        project_dir,
        ProjectConfig(name="proj", question="Does X predict Y?", mode="exploratory",
                      data_paths=[]),
    )
    exp = create_experiment(project_dir, name="baseline", hypothesis="linear suffices")
    return project_dir, exp.experiment_id


@pytest.mark.asyncio
async def test_golden_run_completes_with_recorded_work(tmp_path: Path) -> None:
    project_dir, exp_id = _setup(tmp_path)
    runner = _TranscriptRunner(
        {
            "planning_agent": [_t("planning_agent.baseline.md")],
            "task_agent": [_t("task_agent.one_run.md")],
            "evaluator": [_t("evaluator.criteria_met.md")],
            "advisor_agent": [_t("advisor_agent.next_steps.md")],
        }
    )
    result = await run_experiment(project_dir, exp_id, runner, max_turns=3)

    assert result["status"] == "completed"
    runs = load_progress(project_dir, exp_id)["runs"]
    assert len(runs) >= 1
    assert isinstance(runs[0]["metrics"], dict) and runs[0]["metrics"], runs[0]
    # The run was registered as a method and reached the leaderboard.
    method_names = {m["name"] for m in load_methods(project_dir)}
    assert "ridge_regression_standardized" in method_names
    lb = load_leaderboard(project_dir)
    rank = lb.get("ranking", lb if isinstance(lb, list) else [])
    assert rank, "leaderboard is empty after a real run record"


@pytest.mark.asyncio
async def test_golden_multirun_turn_records_all(tmp_path: Path) -> None:
    project_dir, exp_id = _setup(tmp_path)
    runner = _TranscriptRunner(
        {
            "planning_agent": [_t("planning_agent.baseline.md")],
            # Turn 1 records two runs; turn 2 records the single-run one.
            "task_agent": [_t("task_agent.two_runs.md"), _t("task_agent.one_run.md")],
            "evaluator": [
                _t("evaluator.criteria_not_met.md"),
                _t("evaluator.criteria_met.md"),
            ],
            "advisor_agent": [_t("advisor_agent.next_steps.md")],
        }
    )
    result = await run_experiment(project_dir, exp_id, runner, max_turns=3)

    assert result["status"] == "completed"
    runs = load_progress(project_dir, exp_id)["runs"]
    # 2 from turn 1 + 1 from turn 2.
    assert len(runs) == 3
    run_ids = {r["run_id"] for r in runs}
    assert {"run-001", "run-002", "run-003"} == run_ids
    method_names = {m["name"] for m in load_methods(project_dir)}
    assert {"lightgbm_default", "lightgbm_tuned"} <= method_names


@pytest.mark.parametrize(
    "fname, parser, expect_keys",
    [
        ("planning_agent.baseline.md", parse_method_plan, ("method_name", "steps")),
        ("evaluator.criteria_met.md", parse_evaluation, ("criteria_met",)),
        ("evaluator.criteria_not_met.md", parse_evaluation, ("criteria_met",)),
        ("advisor_agent.next_steps.md", parse_suggestions, ("suggestions",)),
    ],
)
def test_golden_transcripts_parse(fname, parser, expect_keys) -> None:
    parsed = parser(_t(fname))
    assert parsed is not None, f"{fname} did not parse with {parser.__name__}"
    for k in expect_keys:
        assert k in parsed, f"{fname}: parsed dict missing {k!r}"


@pytest.mark.parametrize(
    "fname, expected_run_ids",
    [
        ("task_agent.one_run.md", {"run-001"}),
        ("task_agent.two_runs.md", {"run-002", "run-003"}),
    ],
)
def test_golden_task_transcripts_yield_run_records(fname, expected_run_ids) -> None:
    records = parse_run_records(_t(fname))
    assert {r.run_id for r in records} == expected_run_ids
    for r in records:
        assert r.method and isinstance(r.metrics, dict) and r.metrics
        assert isinstance(r.params, dict)
        assert isinstance(r.artifacts, list) and r.artifacts  # the prose includes figure paths
