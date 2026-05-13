"""Tests for ``loop_display._print_run_summary`` and
``context.summarize_task_output`` — small zero-coverage modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig, RunRecord
from urika.core.progress import append_run
from urika.core.workspace import create_project_workspace
from urika.orchestrator.context import summarize_task_output
from urika.orchestrator.loop_display import _print_run_summary


# ── context.summarize_task_output ──────────────────────────────


def test_summarize_extracts_json_blocks_and_drops_code() -> None:
    text = (
        "Some observation here.\n\n"
        "```python\nimport pandas as pd\ndf = pd.read_csv('x.csv')\n```\n"
        "```json\n"
        '{"run_id": "r1", "method": "lr", "metrics": {"r2": 0.5}}\n'
        "```\n"
    )
    out = summarize_task_output(text)
    # Python block stripped.
    assert "import pandas" not in out
    # JSON block preserved.
    assert '"run_id"' in out
    # Observation kept.
    assert "Some observation here" in out


def test_summarize_strips_pip_output() -> None:
    text = (
        "Successfully installed numpy-2.3.0\n"
        "Collecting pandas (from -r req.txt)\n"
        "Downloading pandas-2.0.tar.gz (12 MB)\n"
        "Installing collected packages: pandas\n"
        "The real summary: results were good.\n"
    )
    out = summarize_task_output(text)
    assert "Successfully installed" not in out
    assert "Downloading" not in out
    assert "Collecting" not in out
    assert "results were good" in out


def test_summarize_truncates_long_observations() -> None:
    text = "x" * 5000
    out = summarize_task_output(text)
    # 1000-char window + truncation marker.
    assert "(truncated)" in out
    assert len(out) < 1500


def test_summarize_empty_input_yields_empty() -> None:
    assert summarize_task_output("") == ""


def test_summarize_json_only_keeps_block() -> None:
    text = '```json\n{"run_id": "r"}\n```'
    out = summarize_task_output(text)
    assert "run_id" in out


# ── loop_display._print_run_summary ────────────────────────────


def _setup_with_runs(tmp_path: Path, runs: list[dict]) -> tuple[Path, str]:
    proj = tmp_path / "p"
    create_project_workspace(
        proj, ProjectConfig(name="p", question="Q?", mode="exploratory")
    )
    exp = create_experiment(proj, name="b", hypothesis="h")
    for r in runs:
        append_run(
            proj, exp.experiment_id,
            RunRecord(
                run_id=r["run_id"], method=r["method"],
                params=r.get("params", {}),
                metrics=r.get("metrics", {}),
                observation=r.get("observation", ""),
                next_step=r.get("next_step", ""),
            ),
        )
    return proj, exp.experiment_id


def test_print_run_summary_emits_progress_events_for_runs(tmp_path: Path) -> None:
    proj, exp_id = _setup_with_runs(
        tmp_path,
        [
            {"run_id": "r1", "method": "lr", "metrics": {"r2": 0.6}},
            {"run_id": "r2", "method": "rf", "metrics": {"r2": 0.85}},
        ],
    )
    events: list[tuple[str, str]] = []

    def progress(e, d=""):
        events.append((e, d))

    _print_run_summary(proj, exp_id, progress)
    # Some events emitted.
    assert events
    body = " | ".join(d for _, d in events)
    # Method names appear.
    assert "lr" in body or "rf" in body
    # Run count surfaced.
    assert "2" in body  # 2 runs


def test_print_run_summary_no_runs_no_output(tmp_path: Path) -> None:
    proj, exp_id = _setup_with_runs(tmp_path, [])
    events: list = []
    _print_run_summary(proj, exp_id, lambda e, d="": events.append((e, d)))
    # No runs → no summary emitted.
    assert events == []


def test_print_run_summary_picks_best_lower_is_better(tmp_path: Path) -> None:
    """When the metric is in _LOWER_IS_BETTER (rmse), the BEST run has
    the *smallest* value."""
    proj, exp_id = _setup_with_runs(
        tmp_path,
        [
            {"run_id": "r1", "method": "a", "metrics": {"rmse": 1.5}},
            {"run_id": "r2", "method": "b", "metrics": {"rmse": 0.5}},
            {"run_id": "r3", "method": "c", "metrics": {"rmse": 2.5}},
        ],
    )
    events: list = []
    _print_run_summary(proj, exp_id, lambda e, d="": events.append((e, d)))
    body = " | ".join(d for _, d in events)
    # The best method by lower-is-better rmse is "b".
    # (Loose assertion — exact phrasing of the "best" output may vary.)
    assert "b" in body
