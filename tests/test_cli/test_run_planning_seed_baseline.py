"""``cli/run_planning._determine_next_experiment`` — fresh-project
safety net.

Mirrors the v0.4.4 fix in ``orchestrator/meta.run_project``: on a
brand-new project with no initial plan, no pending remote suggestion,
and an advisor that returns nothing usable, ``urika run`` must NOT bail
with "nothing to do" and leave the user with a freshly-created project
that never runs — it seeds a deterministic ``baseline`` experiment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.runner import AgentResult


class _NoSuggestionRunner:
    """An advisor that runs fine but never proposes anything parseable."""

    async def run(self, config, prompt, *, on_message=None):  # noqa: ANN001
        return AgentResult(
            success=True,
            messages=[],
            text_output="I don't have a strong recommendation right now.",
            session_id="s",
            num_turns=1,
            duration_ms=1,
        )


class _FailingAdvisorRunner:
    async def run(self, config, prompt, *, on_message=None):  # noqa: ANN001
        return AgentResult(
            success=False, messages=[], text_output="", session_id="s",
            num_turns=0, duration_ms=0, error="advisor unreachable",
        )


def _fresh_project(tmp_path: Path, monkeypatch) -> tuple[Path, str]:
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace
    from urika.core.registry import ProjectRegistry

    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    proj = tmp_path / "freshproj"
    create_project_workspace(
        proj, ProjectConfig(name="freshproj", question="Q?", mode="exploratory")
    )
    ProjectRegistry().register("freshproj", proj)
    return proj, "freshproj"


@pytest.mark.parametrize("runner_cls", [_NoSuggestionRunner, _FailingAdvisorRunner])
def test_seeds_baseline_when_advisor_gives_nothing(
    tmp_path: Path, monkeypatch, runner_cls
) -> None:
    from urika.cli.run_planning import _determine_next_experiment

    proj, name = _fresh_project(tmp_path, monkeypatch)
    monkeypatch.setattr("urika.agents.runner.get_runner", lambda: runner_cls())

    exp_id = _determine_next_experiment(proj, name, auto=True)

    assert exp_id is not None, "expected a seeded baseline experiment, got None"
    exp_dirs = sorted((proj / "experiments").iterdir())
    assert len(exp_dirs) == 1
    assert "baseline" in exp_dirs[0].name


def test_does_not_seed_when_advisor_suggests_normally(
    tmp_path: Path, monkeypatch
) -> None:
    from urika.cli.run_planning import _determine_next_experiment

    class _GoodAdvisor:
        async def run(self, config, prompt, *, on_message=None):  # noqa: ANN001
            return AgentResult(
                success=True, messages=[],
                text_output='```json\n{"suggestions": [{"name": "rf-model", "method": "random forest"}]}\n```',
                session_id="s", num_turns=1, duration_ms=1,
            )

    proj, name = _fresh_project(tmp_path, monkeypatch)
    monkeypatch.setattr("urika.agents.runner.get_runner", lambda: _GoodAdvisor())

    exp_id = _determine_next_experiment(proj, name, auto=True)
    assert exp_id is not None
    exp_dirs = sorted((proj / "experiments").iterdir())
    assert "rf-model" in exp_dirs[0].name  # the advisor's name, not "baseline"


def test_does_not_seed_baseline_when_experiments_completed(
    tmp_path: Path, monkeypatch
) -> None:
    """The seed only fires on a *fresh* project — if there are completed
    experiments and the advisor says we're done, that's a legitimate
    "nothing left to do" → return None."""
    from urika.cli.run_planning import _determine_next_experiment
    from urika.core.experiment import create_experiment
    from urika.core.progress import update_experiment_status

    proj, name = _fresh_project(tmp_path, monkeypatch)
    exp = create_experiment(proj, name="done-one", hypothesis="h")
    update_experiment_status(proj, exp.experiment_id, "completed")
    monkeypatch.setattr("urika.agents.runner.get_runner", lambda: _NoSuggestionRunner())

    exp_id = _determine_next_experiment(proj, name, auto=True)
    assert exp_id is None
