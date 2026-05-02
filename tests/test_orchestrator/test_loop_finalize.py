"""Tests for the post-criteria-met finalize sequence in
``orchestrator/loop_finalize.py``.

Pinned behaviour:
- Per-experiment artifacts are auto-written (narrative + presentation).
- Project-level narrative is NOT auto-written (removed in v0.4.0 —
  it's now ``urika report`` / ``urika finalize`` territory only).

The agent feedback loop relies on methods.json + criteria.json +
advisor-history.json + advisor-context.md (rolling summary) + project
memory — never on projectbook/narrative.md, so dropping the
auto-write does not affect what the planner / advisor see.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from urika.orchestrator.loop_finalize import _generate_reports


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A minimal project workspace with one finished experiment.

    Just enough on-disk state for ``_generate_reports`` to exercise its
    template-generation + agent-narrative paths.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "proj"\nquestion = "?"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    (proj / "methods.json").write_text(json.dumps({"methods": []}))
    (proj / "criteria.json").write_text(
        json.dumps({"versions": [{"version": 1, "type": "exploratory"}]})
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(
        json.dumps({
            "experiment_id": "exp-001",
            "name": "exp",
            "hypothesis": "test hypothesis",
            "status": "completed",
        })
    )
    (exp_dir / "progress.json").write_text(
        json.dumps({"experiment_id": "exp-001", "runs": []})
    )
    (exp_dir / "labbook").mkdir()
    (exp_dir / "artifacts").mkdir()
    return proj


@pytest.mark.asyncio
async def test_generate_reports_does_not_write_project_narrative(
    project_dir: Path,
):
    """Regression: per-experiment finalize must NOT auto-write
    projectbook/narrative.md. That sequence used to add 10-25 min
    of cloud-LLM tail to every successful experiment; v0.4.0
    removes it. The user-facing narrative is now produced on
    demand by ``urika report`` and at end-of-project by
    ``urika finalize``.
    """
    progress_calls = []

    def progress(event, detail=""):
        progress_calls.append((event, detail))

    # A runner that succeeds with a long markdown body — if the
    # project-narrative path were still active, it would write
    # projectbook/narrative.md from this output.
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=MagicMock(
            success=True,
            text_output="# Hdr\n\n" + "x " * 300 + "\n\n# Hdr2\n",
            tokens_in=100,
            tokens_out=200,
            cost_usd=0.01,
        )
    )

    await _generate_reports(
        project_dir,
        "exp-001",
        progress,
        runner=runner,
        on_message=None,
        audience="expert",
    )

    # Project-level narrative was NOT written — that's the change.
    assert not (project_dir / "projectbook" / "narrative.md").exists()

    # And no progress event mentions the project-level narrative.
    project_narrative_events = [
        d for e, d in progress_calls
        if "project narrative" in (d or "").lower()
    ]
    assert project_narrative_events == [], (
        "loop_finalize should no longer announce project-narrative "
        "writes; that work belongs to urika report / urika finalize"
    )


@pytest.mark.asyncio
async def test_generate_reports_writes_experiment_narrative_and_calls_presentation(
    project_dir: Path,
):
    """Regression: experiment-level narrative + presentation are
    still auto-produced. Per-experiment narrative writes to
    experiments/<id>/labbook/narrative.md; presentation is
    handed off to the presentation-agent path (we just assert it
    was invoked — its rendering details have their own tests).
    """
    progress_calls = []

    def progress(event, detail=""):
        progress_calls.append((event, detail))

    # Long markdown response so the orchestrator's
    # "looks-like-a-real-report" guard accepts it.
    long_md = (
        "## Overview\n\n"
        + ("Detail line. " * 100)
        + "\n\n## Methods\n\nx\n\n## Results\n\ny\n"
    )

    async def fake_run(config, prompt, on_message=None):
        # The presentation agent path returns slide JSON, not
        # markdown; for this test we don't exercise the slide
        # rendering — we just assert the agent invocation
        # happened. Returning a markdown body is fine; the
        # presentation rendering path will simply not write a
        # slide deck (no JSON parse), which our test doesn't
        # check.
        return MagicMock(
            success=True,
            text_output=long_md,
            tokens_in=100,
            tokens_out=200,
            cost_usd=0.01,
        )

    runner = MagicMock()
    runner.run = AsyncMock(side_effect=fake_run)

    await _generate_reports(
        project_dir,
        "exp-001",
        progress,
        runner=runner,
        on_message=None,
        audience="expert",
    )

    # Experiment-level narrative IS written.
    exp_narrative = (
        project_dir / "experiments" / "exp-001" / "labbook" / "narrative.md"
    )
    assert exp_narrative.exists(), (
        "loop_finalize must still auto-write the per-experiment "
        "narrative — only the project-level one was removed"
    )

    # The presentation agent was invoked. We can't easily filter
    # by agent role from our mock-run side, but we can confirm
    # the runner was called multiple times — README summarizer +
    # experiment-narrative + presentation = at least 3.
    assert runner.run.call_count >= 3, (
        f"expected >=3 agent calls (README, experiment narrative, "
        f"presentation); got {runner.run.call_count}"
    )


@pytest.mark.asyncio
async def test_generate_reports_no_runner_writes_only_templates(
    project_dir: Path,
):
    """Without a runner (offline / dry mode), only the template
    artifacts (notes / summary / results-summary / key-findings)
    are written. This path is unchanged by the v0.4.0 removal.
    """
    progress_calls = []

    def progress(event, detail=""):
        progress_calls.append((event, detail))

    await _generate_reports(
        project_dir, "exp-001", progress,
        runner=None, on_message=None, audience="expert",
    )

    # Templates always run.
    assert (project_dir / "experiments" / "exp-001" / "labbook" / "notes.md").exists()
    assert (project_dir / "experiments" / "exp-001" / "labbook" / "summary.md").exists()
    # Project-level narrative still NOT written (no agent to call anyway).
    assert not (project_dir / "projectbook" / "narrative.md").exists()
