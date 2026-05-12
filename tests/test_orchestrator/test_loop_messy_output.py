"""The loop must *flag* messy / empty agent output, not silently
"complete" an experiment that did nothing.

The canned outputs in ``test_loop.py`` are hand-written to parse
cleanly, so they never exercised the "real LLM returned prose with no
JSON fence / a truncated fence / nothing at all" paths. Those are
exactly when an experiment exits looking fine while having recorded
zero runs. v0.4.4 made that case a *failure* (with a warning event);
these tests pin that behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig
from urika.core.progress import load_progress
from urika.core.session import load_session
from urika.core.workspace import create_project_workspace
from urika.orchestrator.loop import run_experiment

_PLAN_OK = """\
```json
{"method_name": "lr", "steps": [{"step": 1, "action": "fit"}], "needs_tool": false}
```
"""
_EVAL_NOT_MET = """\
```json
{"criteria_met": false, "reasoning": "not yet"}
```
"""
_SUGGESTION = """\
```json
{"suggestions": [{"name": "rf", "method": "random forest"}], "needs_tool": false}
```
"""
_GOOD_TASK = """\
```json
{"run_id": "run-001", "method": "lr", "params": {}, "metrics": {"r2": 0.8}}
```
"""


class _ScriptedRunner(AgentRunner):
    """Returns a fixed text per role (cycling the last one)."""

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
            num_turns=1,
            duration_ms=1,
        )


def _setup(tmp_path: Path) -> tuple[Path, str]:
    project_dir = tmp_path / "p"
    create_project_workspace(
        project_dir,
        ProjectConfig(name="p", question="Q?", mode="exploratory", data_paths=[]),
    )
    exp = create_experiment(project_dir, name="baseline", hypothesis="h")
    return project_dir, exp.experiment_id


def _events(collector: list[tuple[str, str]]):
    def _cb(event: str, detail: str = "") -> None:
        collector.append((event, detail))

    return _cb


@pytest.mark.parametrize(
    "task_text, label",
    [
        ("I ran a regression and R² was about 0.8 — but no JSON here.", "no fence"),
        ('```json\n{"run_id": "r1", "method": ', "truncated fence"),
        ("", "empty output"),
        ("ERROR: the dataset could not be loaded.", "error string"),
        # A fenced block that *is* JSON but isn't a run record — wrong schema.
        ('```json\n{"result": "great"}\n```', "wrong schema"),
    ],
)
@pytest.mark.asyncio
async def test_unrecordable_task_output_fails_with_warning(
    tmp_path: Path, task_text: str, label: str
) -> None:
    project_dir, exp_id = _setup(tmp_path)
    runner = _ScriptedRunner(
        {
            "planning_agent": [_PLAN_OK],
            "task_agent": [task_text],
            "evaluator": [_EVAL_NOT_MET],
            "advisor_agent": [_SUGGESTION],
        }
    )
    events: list[tuple[str, str]] = []
    result = await run_experiment(
        project_dir, exp_id, runner, max_turns=2, on_progress=_events(events)
    )

    # The experiment must NOT be reported as a clean completion when it
    # recorded zero runs across all turns.
    assert result["status"] == "failed", (
        f"[{label}] expected 'failed' (0 runs recorded), got {result['status']!r}"
    )
    assert load_progress(project_dir, exp_id).get("runs") == []
    session = load_session(project_dir, exp_id)
    assert session is not None and session.status == "failed"
    # ... and there must be a visible warning about it.
    warnings = [d for (e, d) in events if e == "warning"]
    assert any("no parseable run records" in d for d in warnings), (
        f"[{label}] expected a 'no parseable run records' warning event; "
        f"got warnings={warnings!r}"
    )


@pytest.mark.asyncio
async def test_one_clean_run_then_max_turns_completes(tmp_path: Path) -> None:
    """Sanity guard: if the task agent *does* record a real run, the
    experiment legitimately completes at max_turns even if criteria are
    never confirmed — the 0-runs failure path must not over-fire."""
    project_dir, exp_id = _setup(tmp_path)
    runner = _ScriptedRunner(
        {
            "planning_agent": [_PLAN_OK],
            "task_agent": [_GOOD_TASK],
            "evaluator": [_EVAL_NOT_MET],
            "advisor_agent": [_SUGGESTION],
        }
    )
    result = await run_experiment(project_dir, exp_id, runner, max_turns=2)
    assert result["status"] == "completed"
    assert len(load_progress(project_dir, exp_id)["runs"]) >= 1


@pytest.mark.asyncio
async def test_unparseable_evaluator_emits_warning(tmp_path: Path) -> None:
    """A real run that records work but whose evaluator output never
    parses should at least surface a warning rather than running to
    max_turns in silence."""
    project_dir, exp_id = _setup(tmp_path)
    runner = _ScriptedRunner(
        {
            "planning_agent": [_PLAN_OK],
            "task_agent": [_GOOD_TASK],
            "evaluator": ["I think it's going OK but I won't emit JSON."],
            "advisor_agent": [_SUGGESTION],
        }
    )
    events: list[tuple[str, str]] = []
    result = await run_experiment(
        project_dir, exp_id, runner, max_turns=2, on_progress=_events(events)
    )
    assert result["status"] == "completed"  # it did record runs
    warnings = [d for (e, d) in events if e == "warning"]
    assert any("no parseable criteria assessment" in d for d in warnings), warnings


@pytest.mark.asyncio
async def test_unparseable_plan_emits_warning(tmp_path: Path) -> None:
    project_dir, exp_id = _setup(tmp_path)
    runner = _ScriptedRunner(
        {
            "planning_agent": ["Let's just try a regression, no formal plan."],
            "task_agent": [_GOOD_TASK],
            "evaluator": [_EVAL_NOT_MET],
            "advisor_agent": [_SUGGESTION],
        }
    )
    events: list[tuple[str, str]] = []
    await run_experiment(
        project_dir, exp_id, runner, max_turns=1, on_progress=_events(events)
    )
    warnings = [d for (e, d) in events if e == "warning"]
    assert any("no parseable method plan" in d for d in warnings), warnings
