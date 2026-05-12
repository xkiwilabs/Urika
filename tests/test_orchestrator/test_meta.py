"""Tests for the meta-orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace
from urika.orchestrator.meta import _criteria_fully_met, _determine_next, run_project


class TestCriteriaFullyMet:
    def test_returns_false_when_no_criteria_file(self, tmp_path: Path) -> None:
        """No criteria.json means exploratory — never done."""
        assert _criteria_fully_met(tmp_path) is False

    def test_returns_false_when_empty_versions(self, tmp_path: Path) -> None:
        """Empty versions list means no criteria set."""
        (tmp_path / "criteria.json").write_text(json.dumps({"versions": []}))
        assert _criteria_fully_met(tmp_path) is False

    def test_returns_false_when_no_threshold(self, tmp_path: Path) -> None:
        """Criteria without threshold = exploratory, never auto-done."""
        criteria_data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "advisor_agent",
                    "turn": 1,
                    "rationale": "Initial criteria",
                    "criteria": {"type": "exploratory"},
                }
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(criteria_data))
        assert _criteria_fully_met(tmp_path) is False

    def test_returns_false_when_no_primary_threshold(self, tmp_path: Path) -> None:
        """Threshold without primary metric means not fully specified."""
        criteria_data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "advisor_agent",
                    "turn": 1,
                    "rationale": "Partial criteria",
                    "criteria": {
                        "type": "threshold",
                        "threshold": {"secondary": {}},
                    },
                }
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(criteria_data))
        assert _criteria_fully_met(tmp_path) is False

    def test_returns_false_even_with_primary_threshold(self, tmp_path: Path) -> None:
        """Current implementation always returns False — advisor decides."""
        criteria_data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "advisor_agent",
                    "turn": 1,
                    "rationale": "Target set",
                    "criteria": {
                        "type": "threshold",
                        "threshold": {
                            "primary": {
                                "metric": "accuracy",
                                "direction": ">",
                                "target": 0.9,
                            }
                        },
                    },
                }
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(criteria_data))
        assert _criteria_fully_met(tmp_path) is False

    def test_returns_true_when_a_run_passes_threshold(
        self, tmp_path: Path
    ) -> None:
        """A run whose metrics satisfy min/max thresholds -> criteria met."""
        criteria_data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "advisor_agent",
                    "turn": 1,
                    "rationale": "Need r2 >= 0.8",
                    "criteria": {
                        "type": "threshold",
                        "threshold": {"r2": {"min": 0.8}},
                    },
                }
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(criteria_data))

        exp_dir = tmp_path / "experiments" / "exp-001-baseline"
        exp_dir.mkdir(parents=True)
        (exp_dir / "progress.json").write_text(
            json.dumps(
                {
                    "experiment_id": "exp-001-baseline",
                    "status": "completed",
                    "runs": [
                        {
                            "run_id": "run-001",
                            "method": "linear",
                            "metrics": {"r2": 0.85},
                        }
                    ],
                }
            )
        )

        assert _criteria_fully_met(tmp_path) is True

    def test_returns_false_when_all_runs_fail_threshold(
        self, tmp_path: Path
    ) -> None:
        """If no run reaches the threshold, return False."""
        criteria_data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "advisor_agent",
                    "turn": 1,
                    "rationale": "Need r2 >= 0.95",
                    "criteria": {
                        "type": "threshold",
                        "threshold": {"r2": {"min": 0.95}},
                    },
                }
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(criteria_data))

        exp_dir = tmp_path / "experiments" / "exp-001"
        exp_dir.mkdir(parents=True)
        (exp_dir / "progress.json").write_text(
            json.dumps(
                {
                    "runs": [
                        {"run_id": "r1", "method": "m", "metrics": {"r2": 0.40}},
                        {"run_id": "r2", "method": "m", "metrics": {"r2": 0.70}},
                    ],
                }
            )
        )

        assert _criteria_fully_met(tmp_path) is False

    def test_tolerates_corrupt_progress_json(self, tmp_path: Path) -> None:
        """A corrupt progress.json is skipped, not propagated as a crash."""
        criteria_data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "advisor_agent",
                    "turn": 1,
                    "rationale": "Need r2 >= 0.8",
                    "criteria": {
                        "type": "threshold",
                        "threshold": {"r2": {"min": 0.8}},
                    },
                }
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(criteria_data))

        # One corrupt experiment
        exp_bad = tmp_path / "experiments" / "exp-001-corrupt"
        exp_bad.mkdir(parents=True)
        (exp_bad / "progress.json").write_text("{not valid json")

        # One good experiment whose metrics pass
        exp_good = tmp_path / "experiments" / "exp-002-good"
        exp_good.mkdir(parents=True)
        (exp_good / "progress.json").write_text(
            json.dumps(
                {
                    "runs": [
                        {
                            "run_id": "r1",
                            "method": "m",
                            "metrics": {"r2": 0.9},
                        }
                    ]
                }
            )
        )

        # Corrupt file should be skipped; good one satisfies criteria
        assert _criteria_fully_met(tmp_path) is True


# --- _determine_next tests (advisor handoff) -------------------------


class _FakeRunner(AgentRunner):
    """Minimal runner that records the prompt it was called with."""

    def __init__(self, text: str = "", success: bool = True, error: str = ""):
        self._text = text
        self._success = success
        self._error = error
        self.last_prompt: str = ""
        self.call_count: int = 0

    async def run(
        self,
        config: AgentConfig,
        prompt: str,
        *,
        on_message: object = None,
    ) -> AgentResult:
        self.call_count += 1
        self.last_prompt = prompt
        return AgentResult(
            success=self._success,
            messages=[],
            text_output=self._text,
            session_id="fake-session",
            num_turns=1,
            duration_ms=1,
            error=self._error or None,
        )


def _write_toml(project_dir: Path, name: str = "proj", mode: str = "exploratory",
                question: str = "Q?") -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nmode = "{mode}"\nquestion = "{question}"\n',
        encoding="utf-8",
    )


class TestDetermineNext:
    @pytest.mark.asyncio
    async def test_parses_advisor_suggestion(self, tmp_path: Path) -> None:
        """Advisor JSON-suggestions block yields the first suggestion."""
        _write_toml(tmp_path)
        advisor_text = (
            "Try this next:\n"
            "```json\n"
            '{"suggestions": ['
            '{"name": "rf-baseline", "method": "random forest"}'
            "]}\n"
            "```\n"
        )
        runner = _FakeRunner(text=advisor_text)

        next_exp, text, failed = await _determine_next(
            tmp_path, runner, instructions="", on_message=None
        )

        assert next_exp is not None
        assert next_exp["name"] == "rf-baseline"
        assert runner.call_count == 1
        assert failed is False
        # Text is the advisor's raw output
        assert "random forest" in text

    @pytest.mark.asyncio
    async def test_returns_none_when_runner_fails(self, tmp_path: Path) -> None:
        """If the advisor run fails, _determine_next returns (None, error, True)."""
        _write_toml(tmp_path)
        runner = _FakeRunner(success=False, error="boom")

        next_exp, text, failed = await _determine_next(
            tmp_path, runner, instructions="", on_message=None
        )

        assert next_exp is None
        assert text == "boom"
        assert failed is True

    @pytest.mark.asyncio
    async def test_returns_none_when_no_suggestions_in_output(
        self, tmp_path: Path
    ) -> None:
        """Plain prose without a suggestions JSON block -> no next experiment."""
        _write_toml(tmp_path)
        runner = _FakeRunner(
            text="I think we've covered all the promising directions."
        )

        next_exp, text, failed = await _determine_next(
            tmp_path, runner, instructions="", on_message=None
        )

        assert next_exp is None
        assert failed is False
        # The text is still returned for display to the user
        assert "promising" in text

    @pytest.mark.asyncio
    async def test_user_instructions_reach_advisor_prompt(
        self, tmp_path: Path
    ) -> None:
        """User instructions are injected into the advisor's context."""
        _write_toml(tmp_path)
        runner = _FakeRunner(text="no suggestions here")

        await _determine_next(
            tmp_path,
            runner,
            instructions="focus on tree-based models only",
            on_message=None,
        )

        assert "tree-based models only" in runner.last_prompt
        # The project question should also appear in context
        assert "Q?" in runner.last_prompt


class TestRunProjectFreshSafetyNet:
    """A brand-new project must not exit having done zero experiments
    just because the advisor's first response had no parseable
    ``suggestions`` block (the v0.4.4 HIGH-3 fix)."""

    @pytest.mark.asyncio
    async def test_seeds_baseline_when_advisor_gives_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_dir = tmp_path / "fresh-proj"
        create_project_workspace(
            project_dir,
            ProjectConfig(
                name="fresh-proj",
                question="Does X predict Y?",
                mode="exploratory",
                data_paths=[],
            ),
        )

        # Advisor always replies with prose — no suggestions block,
        # ever (so the retry-with-nudge also yields nothing).
        runner = _FakeRunner(text="I have no particular recommendation.")

        ran_experiments: list[str] = []

        async def _fake_run_experiment(pdir, exp_id, rnr, **kw):  # noqa: ANN001
            ran_experiments.append(exp_id)
            return {"status": "completed", "turns": 1}

        async def _fake_finalize(*a, **k):  # noqa: ANN002, ANN003
            return None

        monkeypatch.setattr("urika.orchestrator.run_experiment", _fake_run_experiment)
        monkeypatch.setattr(
            "urika.orchestrator.finalize.finalize_project", _fake_finalize
        )

        result = await run_project(
            project_dir, runner, mode="capped", max_experiments=1, max_turns=1
        )

        # The orchestrator seeded a deterministic baseline experiment
        # and ran it, rather than bailing with 0 experiments.
        assert result["experiments_run"] == 1
        assert len(ran_experiments) == 1
        exps = sorted((project_dir / "experiments").iterdir())
        assert len(exps) == 1
        assert "baseline" in exps[0].name

    @pytest.mark.asyncio
    async def test_no_seed_when_advisor_suggests_normally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Guard against the safety net firing on the happy path.
        project_dir = tmp_path / "ok-proj"
        create_project_workspace(
            project_dir,
            ProjectConfig(
                name="ok-proj",
                question="Q?",
                mode="exploratory",
                data_paths=[],
            ),
        )
        runner = _FakeRunner(
            text='```json\n{"suggestions": [{"name": "rf", "method": "random forest"}]}\n```'
        )

        async def _fake_run_experiment(pdir, exp_id, rnr, **kw):  # noqa: ANN001
            return {"status": "completed", "turns": 1}

        async def _fake_finalize(*a, **k):  # noqa: ANN002, ANN003
            return None

        monkeypatch.setattr("urika.orchestrator.run_experiment", _fake_run_experiment)
        monkeypatch.setattr(
            "urika.orchestrator.finalize.finalize_project", _fake_finalize
        )

        await run_project(
            project_dir, runner, mode="capped", max_experiments=1, max_turns=1
        )
        # Advisor was called exactly once (no retry-with-nudge).
        assert runner.call_count == 1
        exps = sorted((project_dir / "experiments").iterdir())
        assert len(exps) == 1
        assert "rf" in exps[0].name
