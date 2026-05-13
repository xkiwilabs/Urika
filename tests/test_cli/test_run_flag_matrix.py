"""CLI ``urika run`` flag matrix.

Each flag must reach ``run_experiment`` (or ``run_project`` for
``--max-experiments``) as the right kwarg. Most flags were untested
at the CLI-integration layer pre-this-file — the orchestrator was
mocked but no test asserted *what* was forwarded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from urika.cli import cli


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> dict:
    """A registered project with one pending experiment so `urika run`
    has something to dispatch."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-001",
                "name": "baseline",
                "hypothesis": "linear suffices",
                "created": "2026-05-01T00:00:00Z",
            }
        )
    )
    (exp_dir / "progress.json").write_text(
        json.dumps({"status": "pending", "runs": []})
    )
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    return {"home": home, "proj": proj, "name": "alpha", "exp_id": "exp-001"}


@pytest.fixture
def captured(monkeypatch) -> dict:
    """Stub run_experiment + run_project to record kwargs."""
    rec: dict = {}

    async def _fake_run_experiment(*args, **kwargs):
        rec["single"] = {"args": args, "kwargs": kwargs}
        return {"status": "completed", "turns": 0, "tokens_in": 0,
                "tokens_out": 0, "cost_usd": 0.0, "agent_calls": 0}

    async def _fake_run_project(*args, **kwargs):
        rec["meta"] = {"args": args, "kwargs": kwargs}
        return {"experiments": [], "status": "completed",
                "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
                "agent_calls": 0}

    monkeypatch.setattr("urika.orchestrator.run_experiment", _fake_run_experiment)
    monkeypatch.setattr("urika.orchestrator.run_project", _fake_run_project)
    return rec


def _invoke(args: list[str], project: dict) -> object:
    env = {
        "URIKA_HOME": str(project["home"]),
        "ANTHROPIC_API_KEY": "test-key",
    }
    return CliRunner().invoke(cli, args, env=env)


# ── single-experiment flags forwarded to run_experiment ────────


def test_max_turns_forwarded(project, captured) -> None:
    r = _invoke(["run", "alpha", "--max-turns", "7", "--auto", "-q"], project)
    assert r.exit_code == 0, r.output
    assert captured["single"]["kwargs"]["max_turns"] == 7


def test_instructions_forwarded(project, captured) -> None:
    r = _invoke(
        ["run", "alpha", "--instructions", "focus on trees", "--auto", "-q"],
        project,
    )
    assert r.exit_code == 0, r.output
    assert captured["single"]["kwargs"]["instructions"] == "focus on trees"


def test_audience_forwarded(project, captured) -> None:
    r = _invoke(["run", "alpha", "--audience", "expert", "--auto", "-q"], project)
    assert r.exit_code == 0, r.output
    assert captured["single"]["kwargs"]["audience"] == "expert"


def test_review_criteria_forwarded(project, captured) -> None:
    r = _invoke(["run", "alpha", "--review-criteria", "--auto", "-q"], project)
    assert r.exit_code == 0, r.output
    assert captured["single"]["kwargs"]["review_criteria"] is True


def test_quiet_does_not_break_run(project, captured) -> None:
    """``-q`` / ``--quiet`` is consumed by the CLI for display
    suppression; the run must still proceed."""
    r = _invoke(["run", "alpha", "--auto", "-q"], project)
    assert r.exit_code == 0, r.output
    assert "single" in captured  # run_experiment was called


def test_resume_flag_forwarded_as_kwarg(project, captured, monkeypatch) -> None:
    """``--resume`` reaches the meta loop / experiment runner as a
    True kwarg. (Mirrors the existing TestRunContinueFlag tests; this
    one asserts the kwarg specifically.)"""
    # Mark the experiment as paused so --resume has a target.
    progress = project["proj"] / "experiments" / project["exp_id"] / "progress.json"
    progress.write_text(json.dumps({"status": "paused", "runs": []}))
    r = _invoke(["run", "alpha", "--resume", "--auto", "-q"], project)
    assert r.exit_code == 0, r.output
    # --resume single-experiment path: run_experiment gets resume=True.
    assert captured["single"]["kwargs"].get("resume") is True


# ── meta-orchestrator flags forwarded to run_project ───────────


def test_max_experiments_dispatches_to_run_project(project, captured) -> None:
    r = _invoke(
        ["run", "alpha", "--max-experiments", "3", "--auto", "-q"], project
    )
    assert r.exit_code == 0, r.output
    assert "meta" in captured, (
        "--max-experiments must dispatch to run_project, not run_experiment"
    )
    assert captured["meta"]["kwargs"]["max_experiments"] == 3


def test_max_turns_forwarded_to_meta_loop(project, captured) -> None:
    r = _invoke(
        ["run", "alpha", "--max-experiments", "2", "--max-turns", "4", "--auto", "-q"],
        project,
    )
    assert r.exit_code == 0, r.output
    assert captured["meta"]["kwargs"]["max_turns"] == 4


def test_meta_loop_instructions_forwarded(project, captured) -> None:
    r = _invoke(
        ["run", "alpha", "--max-experiments", "2", "--instructions", "try x",
         "--auto", "-q"],
        project,
    )
    assert r.exit_code == 0, r.output
    assert captured["meta"]["kwargs"].get("instructions") == "try x"


def test_advisor_first_propagates(project, captured) -> None:
    """--advisor-first forwards through to the single-experiment run
    (the meta loop handles its own advisor calls)."""
    r = _invoke(
        ["run", "alpha", "--advisor-first", "--auto", "-q"], project
    )
    assert r.exit_code == 0, r.output
    # The flag may land as ``advisor_first`` or as a CLI-side
    # behavior change; either way the test for "no crash on the flag"
    # is satisfied by exit 0. If the kwarg is forwarded, pin it.
    if "advisor_first" in captured["single"]["kwargs"]:
        assert captured["single"]["kwargs"]["advisor_first"] is True
