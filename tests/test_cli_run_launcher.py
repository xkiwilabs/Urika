"""CLI ``urika run`` launcher menu — autonomous-state surfacing.

v0.4.1 added an ``Autonomous`` line to the run-settings header and a
new ``Run autonomously (no prompts)`` menu option so users can opt out
of the advisor confirmation gate without learning the ``--auto`` flag.

These tests cover the launcher only (no real agent runs). The
orchestrator entry point ``run_experiment`` is monkeypatched out so the
prompt path is exercised in isolation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from urika.cli import cli


@pytest.fixture
def project_with_one_experiment(tmp_path: Path, monkeypatch) -> tuple[Path, str]:
    """A registered project with one pending experiment so ``urika run``
    skips the advisor-suggest path and lands directly on the launcher.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))

    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\n'
        'mode = "exploratory"\ndescription = ""\n\n'
        '[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-001",
                "name": "test-exp",
                "hypothesis": "h",
                "created": "2026-05-02T00:00:00Z",
            }
        )
    )
    (exp_dir / "progress.json").write_text(
        json.dumps({"status": "pending", "runs": []})
    )
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    return proj, "alpha"


@pytest.fixture
def stub_run_experiment(monkeypatch) -> dict:
    """Replace the orchestrator's ``run_experiment`` with a recorder so
    we can assert what flags the launcher passed without doing real work.
    """
    captured: dict = {}

    async def _fake_run_experiment(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"status": "completed", "turns": 0, "tokens_in": 0,
                "tokens_out": 0, "cost_usd": 0.0, "agent_calls": 0}

    # cli/run.py imports ``run_experiment`` and ``run_project`` lazily
    # inside the run() function via
    #   from urika.orchestrator import run_experiment, run_project
    # so the lookup hits ``urika.orchestrator.<name>`` at call time —
    # patching the source modules is sufficient.
    async def _fake_run_project(*args, **kwargs):
        captured["meta_kwargs"] = kwargs
        return {"experiments": [], "status": "completed"}

    monkeypatch.setattr(
        "urika.orchestrator.run_experiment", _fake_run_experiment
    )
    monkeypatch.setattr(
        "urika.orchestrator.run_project", _fake_run_project
    )
    return captured


def test_launcher_header_surfaces_autonomous_default(
    project_with_one_experiment, stub_run_experiment, monkeypatch
) -> None:
    """The Run-settings header tells the user that prompts will fire
    after the advisor — pre-v0.4.1 this state was invisible."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    # ``urika.cli.run`` resolves to the Click command (re-exported in
    # ``urika.cli.__init__``), not the submodule — go through sys.modules
    # to reach the actual module object.
    import sys as _sys
    _run_module = _sys.modules["urika.cli.run"]
    monkeypatch.setattr(_run_module, "_stdin_is_interactive", lambda: True)

    runner = CliRunner()
    # Pick option 5 = Skip so we exit cleanly after the prompt.
    result = runner.invoke(cli, ["run", "alpha"], input="5\n")
    body = result.output

    assert "Run settings for alpha" in body
    assert "Autonomous: no" in body
    assert "advisor picks an experiment" in body
    assert "use option 2, or pass --auto" in body


def test_launcher_option_2_runs_autonomously(
    project_with_one_experiment, stub_run_experiment, monkeypatch
) -> None:
    """Option 2 (``Run autonomously``) must set auto=True and stay on
    the single-experiment path — i.e. no max_experiments, no
    meta-orchestrator. Pre-fix this option did not exist; users had to
    pass ``--auto`` from the command line.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    # ``urika.cli.run`` resolves to the Click command (re-exported in
    # ``urika.cli.__init__``), not the submodule — go through sys.modules
    # to reach the actual module object.
    import sys as _sys
    _run_module = _sys.modules["urika.cli.run"]
    monkeypatch.setattr(_run_module, "_stdin_is_interactive", lambda: True)

    runner = CliRunner()
    result = runner.invoke(cli, ["run", "alpha"], input="2\n")
    body = result.output

    # Post-menu summary makes the autonomous state explicit.
    assert "single experiment (autonomous)" in body
    # The orchestrator entry point was hit (not the meta path).
    assert "args" in stub_run_experiment, (
        "run_experiment must be invoked when option 2 is chosen"
    )
    assert "meta_kwargs" not in stub_run_experiment, (
        "option 2 must NOT take the meta-orchestrator path"
    )


def test_launcher_option_3_runs_multiple_experiments(
    project_with_one_experiment, stub_run_experiment, monkeypatch
) -> None:
    """Option 3 (``Run multiple``) is the renumbered meta-orchestrator
    entry — autonomous + capped. Pre-fix this was option 2; the renumber
    must not regress its behaviour.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    # ``urika.cli.run`` resolves to the Click command (re-exported in
    # ``urika.cli.__init__``), not the submodule — go through sys.modules
    # to reach the actual module object.
    import sys as _sys
    _run_module = _sys.modules["urika.cli.run"]
    monkeypatch.setattr(_run_module, "_stdin_is_interactive", lambda: True)

    runner = CliRunner()
    # 3 = Run multiple, then "5" for how-many-experiments.
    result = runner.invoke(cli, ["run", "alpha"], input="3\n5\n")
    body = result.output

    assert "Experiments:  up to 5 (autonomous)" in body
    assert "meta_kwargs" in stub_run_experiment, (
        "option 3 must invoke the meta-orchestrator"
    )


def test_launcher_skipped_when_auto_flag_present(
    project_with_one_experiment, stub_run_experiment, monkeypatch
) -> None:
    """Passing ``--auto`` on the command line bypasses the launcher
    entirely (its guard already covered this; we lock it in)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    # ``urika.cli.run`` resolves to the Click command (re-exported in
    # ``urika.cli.__init__``), not the submodule — go through sys.modules
    # to reach the actual module object.
    import sys as _sys
    _run_module = _sys.modules["urika.cli.run"]
    monkeypatch.setattr(_run_module, "_stdin_is_interactive", lambda: True)

    runner = CliRunner()
    result = runner.invoke(cli, ["run", "alpha", "--auto"])
    body = result.output

    assert "Run settings for alpha" not in body
    assert "Autonomous: no" not in body


# --- run-outcome surfacing (v0.4.4) --------------------------------------
#
# A failed / paused run must be *visibly* surfaced by `urika run` (and
# therefore by the TUI / REPL, which both invoke this same command).
# Pre-v0.4.4 a flaky agent error on turn 1 hard-failed the experiment;
# now it pauses-and-resumes. Either way the user must be told what
# happened — not see a bare "done".

def _patch_run_experiment(monkeypatch, return_value: dict) -> None:
    async def _fake(*args, **kwargs):
        base = {"turns": 0, "tokens_in": 0, "tokens_out": 0,
                "cost_usd": 0.0, "agent_calls": 0}
        base.update(return_value)
        return base

    monkeypatch.setattr("urika.orchestrator.run_experiment", _fake)


def test_run_surfaces_failed_status(
    project_with_one_experiment, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    _patch_run_experiment(
        monkeypatch, {"status": "failed", "error": "kaboom: the dataset vanished", "turns": 2}
    )
    result = CliRunner().invoke(cli, ["run", "alpha", "--auto"])
    # Must not crash, must report the failure and the error text.
    assert "fail" in result.output.lower()
    assert "kaboom" in result.output
    # And it must NOT claim success.
    assert "completed after" not in result.output.lower()


def test_run_surfaces_paused_status_with_resume_hint(
    project_with_one_experiment, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    _patch_run_experiment(monkeypatch, {"status": "paused", "turns": 1})
    result = CliRunner().invoke(cli, ["run", "alpha", "--auto"])
    assert "pause" in result.output.lower()
    assert "--resume" in result.output


def test_run_surfaces_unknown_status_gracefully(
    project_with_one_experiment, monkeypatch
) -> None:
    """A status the CLI doesn't recognise (e.g. a future 'completed_empty')
    must still be printed, not swallowed."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    _patch_run_experiment(monkeypatch, {"status": "completed_empty", "turns": 3})
    result = CliRunner().invoke(cli, ["run", "alpha", "--auto"])
    assert "completed_empty" in result.output
