"""v0.6.0 cut criterion #3: ``auto_push`` lands a commit on the remote.

End-to-end: register a project, ``urika github init --remote <bare>``,
enable ``auto_push`` in ``urika.toml``, ``urika run`` against a stubbed
``AgentRunner``, verify the bare remote received the commit with the
expected ``urika-event: run`` trailer.

The real Anthropic API is never hit. The runner factory is patched
globally with a deterministic ``AgentRunner`` (same pattern as
``tests/test_smoke/test_smoke_cli_run.py``) so the orchestrator loop
runs against canned plan/task/evaluator/advisor responses, completes
in one turn (criteria_met=true), and the ``run`` command's tail
``_maybe_auto_push`` hook fires.

Marked ``integration`` because it spawns a real ``git`` subprocess +
runs the real orchestrator loop end-to-end through ``CliRunner``.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.cli import cli

pytestmark = pytest.mark.integration


class _DeterministicRunner(AgentRunner):
    """Returns role-appropriate canned text so the orchestrator loop
    runs a single turn that records one run and completes (criteria met).

    Mirrors ``tests/test_smoke/test_smoke_cli_run.py``'s runner — the
    only difference is we don't care about the call log here, just
    that the loop reaches ``completed`` status so ``_maybe_auto_push``
    fires.
    """

    _PLAN = """```json
{"method_name": "ridge_baseline", "steps": [{"step": 1, "action": "fit"}],
 "evaluation": {"strategy": "80/20 holdout", "metrics": ["r2"]}}
```"""
    _TASK = """```json
{"run_id": "run-001", "method": "ridge_baseline",
 "params": {"alpha": 1.0},
 "metrics": {"r2": 0.83, "rmse": 4.21},
 "observation": "Strong baseline fit.",
 "next_step": "Try a non-linear model.",
 "artifacts": []}
```"""
    _EVAL = """```json
{"criteria_met": true,
 "assessment": {"threshold": {"primary_met": true, "primary_value": 0.83}},
 "best_metrics": {"r2": 0.83},
 "summary": "Criteria met — ridge baseline above threshold."}
```"""
    _SUGG = """```json
{"suggestions": [{"name": "follow-up", "method": "gradient boosting"}]}
```"""

    async def run(
        self, config: AgentConfig, prompt: str, *, on_message=None
    ) -> AgentResult:
        text = {
            "planning_agent": self._PLAN,
            "task_agent": self._TASK,
            "evaluator": self._EVAL,
            "advisor_agent": self._SUGG,
        }.get(config.name, "")
        return AgentResult(
            success=True,
            messages=[],
            text_output=text,
            session_id=f"s-{config.name}",
            num_turns=1,
            duration_ms=1,
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0001,
            model="claude-test",
        )


def _setup_project(home: Path) -> tuple[Path, str, str]:
    """Create a registered project + one pending experiment.

    Returns ``(project_dir, project_name, experiment_id)``. Mirrors
    ``tests/test_smoke/test_smoke_cli_run.py``'s helper so this test
    can exercise the same real-orchestrator path.
    """
    from urika.core.experiment import create_experiment
    from urika.core.models import ProjectConfig
    from urika.core.registry import ProjectRegistry
    from urika.core.workspace import create_project_workspace

    proj = home / "proj"
    create_project_workspace(
        proj,
        ProjectConfig(
            name="proj",
            question="Does X predict Y?",
            mode="exploratory",
            data_paths=[],
        ),
    )
    ProjectRegistry().register("proj", proj)
    exp = create_experiment(proj, name="baseline", hypothesis="linear suffices")
    return proj, "proj", exp.experiment_id


def test_auto_push_lands_commit_on_remote(tmp_path: Path, monkeypatch) -> None:
    """A project with ``[github] auto_push = true`` reflects a completed
    ``urika run`` as a commit on the configured remote.

    Bare-remote fixture; real Anthropic API never touched. The orchestrator
    is driven by a canned ``_DeterministicRunner`` (same pattern as the
    CLI smoke) that completes one turn with ``criteria_met=true``, so
    ``_maybe_auto_push`` fires from the tail of ``urika run``.
    """
    # --- 0. Test environment ---
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    # Bypass the Consumer Terms §3.7 gate without hitting the real API.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    # --- 1. Bare remote ---
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)

    # --- 2. Project + experiment ---
    proj_dir, proj_name, exp_id = _setup_project(tmp_path)

    # --- 3. ``urika github init`` with the bare remote as origin ---
    result = CliRunner().invoke(
        cli, ["github", "init", proj_name, "--remote", str(bare)]
    )
    assert result.exit_code == 0, result.output
    assert (proj_dir / ".git").is_dir()

    # --- 4. Enable auto_push in urika.toml ---
    toml_path = proj_dir / "urika.toml"
    toml_path.write_text(
        toml_path.read_text(encoding="utf-8")
        + '\n[github]\nauto_push = true\nauto_push_after = ["run"]\n',
        encoding="utf-8",
    )

    # --- 5. Stub the agent runner globally ---
    runner = _DeterministicRunner()
    monkeypatch.setattr("urika.agents.runner.get_runner", lambda *_a, **_k: runner)

    # --- 6. ``urika run`` (single turn, autonomous, quiet, json to skip TTY prompt) ---
    start = time.time()
    result = CliRunner().invoke(
        cli,
        [
            "run",
            proj_name,
            "--experiment",
            exp_id,
            "--max-turns",
            "1",
            "--auto",
            "-q",
        ],
    )
    elapsed = time.time() - start
    assert result.exit_code == 0, (
        f"non-zero exit ({result.exit_code}); output:\n{result.output}\n"
        f"exc: {result.exception!r}"
    )
    # Stubbed turn — comfortably under 60s. Detects an accidental real-API
    # hookup or a hang in the orchestrator loop.
    assert elapsed < 60, f"stubbed run took {elapsed:.1f}s — suspect API or hang"

    # --- 7. Sanity-check the orchestrator actually completed a turn ---
    prog = json.loads(
        (proj_dir / "experiments" / exp_id / "progress.json").read_text("utf-8")
    )
    assert prog.get("status") == "completed", prog
    assert len(prog.get("runs", [])) >= 1, prog

    # --- 8. The bare remote received an auto_push commit ---
    log = subprocess.run(
        ["git", "--git-dir", str(bare), "log", "--format=%B"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "urika-event: run" in log, (
        f"remote log has no urika-event: run trailer.\n--- log ---\n{log}\n"
        f"--- urika run output ---\n{result.output}"
    )
    # And the commit subject matches the run-event template
    # (see ``_EVENT_SUBJECT_TEMPLATES['run']`` in ``cli/github.py``).
    assert "urika: experiment run completed" in log, log
