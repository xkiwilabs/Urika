"""Non-mocked CLI ``urika run`` smoke.

Every other test of the CLI ``run`` command patches
``urika.orchestrator.run_experiment`` directly, so the real path —
loading the orchestrator, building the loop, dispatching to each
agent role, parsing outputs, updating progress.json / methods.json /
leaderboard.json, surfacing status to the CLI display — never runs
end to end. This wires a deterministic *agent-runner* (one layer down
from ``run_experiment``) and invokes ``urika run`` via ``CliRunner``.

Catches the family of regressions where the orchestrator's loop did
the wrong thing with what the agents returned, and every CLI test
passed anyway because the orchestrator itself was mocked. Marked
``integration`` because it touches the real orchestrator + filesystem
+ click invocation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.cli import cli

pytestmark = pytest.mark.integration


class _DeterministicRunner(AgentRunner):
    """Returns role-appropriate text. Mirrors the structure of the
    golden transcripts (prose + JSON fence)."""

    _PLAN = '''```json
{"method_name": "ridge_baseline", "steps": [{"step": 1, "action": "fit"}],
 "evaluation": {"strategy": "80/20 holdout", "metrics": ["r2"]}}
```'''
    _TASK = '''```json
{"run_id": "run-001", "method": "ridge_baseline",
 "params": {"alpha": 1.0},
 "metrics": {"r2": 0.83, "rmse": 4.21},
 "observation": "Strong baseline fit.",
 "next_step": "Try a non-linear model.",
 "artifacts": ["artifacts/predicted_vs_actual.png"]}
```'''
    _EVAL = '''```json
{"criteria_met": true,
 "assessment": {"threshold": {"primary_met": true, "primary_value": 0.83}},
 "best_metrics": {"r2": 0.83},
 "summary": "Criteria met — ridge baseline above threshold."}
```'''
    _SUGG = '''```json
{"suggestions": [{"name": "follow-up", "method": "gradient boosting"}]}
```'''

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(
        self, config: AgentConfig, prompt: str, *, on_message=None
    ) -> AgentResult:
        name = config.name
        self.calls.append(name)
        text = {
            "planning_agent": self._PLAN,
            "task_agent": self._TASK,
            "evaluator": self._EVAL,
            "advisor_agent": self._SUGG,
        }.get(name, "")
        return AgentResult(
            success=True,
            messages=[],
            text_output=text,
            session_id=f"s-{name}",
            num_turns=1,
            duration_ms=1,
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0001,
            model="claude-test",
        )


def _setup_project(home: Path) -> tuple[Path, str, str]:
    """Create a registered project + one pending experiment."""
    from urika.core.experiment import create_experiment
    from urika.core.models import ProjectConfig
    from urika.core.registry import ProjectRegistry
    from urika.core.workspace import create_project_workspace

    proj = home / "alpha"
    create_project_workspace(
        proj,
        ProjectConfig(name="alpha", question="Does X predict Y?",
                      mode="exploratory", data_paths=[]),
    )
    ProjectRegistry().register("alpha", proj)
    exp = create_experiment(proj, name="baseline", hypothesis="linear suffices")
    return proj, "alpha", exp.experiment_id


def test_urika_run_real_orchestrator_records_runs_and_completes(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")  # bypass compliance gate

    proj, name, exp_id = _setup_project(tmp_path)

    runner = _DeterministicRunner()
    # Patch the runner factory globally — both the orchestrator loop's
    # ``get_runner()`` and any role-builder calls land on the same fake.
    monkeypatch.setattr("urika.agents.runner.get_runner", lambda *_a, **_k: runner)

    result = CliRunner().invoke(
        cli,
        ["run", name, "--experiment", exp_id, "--max-turns", "3", "--auto", "-q"],
    )
    assert result.exit_code == 0, (
        f"non-zero exit ({result.exit_code}); output:\n{result.output}\n"
        f"exc: {result.exception!r}"
    )

    # The real orchestrator path ran the planning + task + evaluator + advisor agents.
    assert "planning_agent" in runner.calls
    assert "task_agent" in runner.calls
    assert "evaluator" in runner.calls

    # progress.json reflects the real run we recorded — not a mock value.
    prog = json.loads(
        (proj / "experiments" / exp_id / "progress.json").read_text("utf-8")
    )
    assert len(prog["runs"]) >= 1
    r = prog["runs"][0]
    assert r["run_id"] == "run-001"
    assert r["method"] == "ridge_baseline"
    assert isinstance(r["metrics"], dict) and r["metrics"]["r2"] == 0.83

    # methods.json picked up the registered method.
    methods = json.loads((proj / "methods.json").read_text("utf-8"))
    names = [m["name"] for m in methods.get("methods", [])]
    assert "ridge_baseline" in names

    # leaderboard.json has at least one ranked entry.
    lb_path = proj / "leaderboard.json"
    assert lb_path.exists()
    lb = json.loads(lb_path.read_text("utf-8"))
    rank = lb.get("ranking") if isinstance(lb, dict) else (lb if isinstance(lb, list) else [])
    assert rank, "leaderboard empty after a real run"

    # CLI output mentions completion + the recorded turn count.
    out = result.output.lower()
    assert "completed" in out or "complete" in out
