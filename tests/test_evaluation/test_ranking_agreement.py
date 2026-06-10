"""Cross-surface agreement: labbook, progress, and leaderboard must name
the same best run now that all best-run selection delegates to
``urika.evaluation.ranking``."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.core.experiment import create_experiment
from urika.core.labbook import _find_best_run
from urika.core.models import ProjectConfig, RunRecord
from urika.core.progress import append_run, get_best_run, load_progress
from urika.core.workspace import create_project_workspace
from urika.evaluation.leaderboard import load_leaderboard, update_leaderboard


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "agreement"
    config = ProjectConfig(name="agreement", question="?", mode="exploratory")
    create_project_workspace(d, config)
    return d


def test_labbook_progress_leaderboard_agree_on_best(project_dir: Path) -> None:
    """Three runs, best-by-r2 is run-002 — all three surfaces must agree."""
    exp = create_experiment(project_dir, name="agree", hypothesis="they agree")
    eid = exp.experiment_id

    runs = [
        RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={"alpha": 0.1},
            metrics={"r2": 0.55, "rmse": 0.40},
        ),
        RunRecord(
            run_id="run-002",
            method="random_forest",
            params={"n_estimators": 100},
            metrics={"r2": 0.91, "rmse": 0.12},
        ),
        RunRecord(
            run_id="run-003",
            method="gradient_boosting",
            params={"n_estimators": 50},
            metrics={"r2": 0.78, "rmse": 0.21},
        ),
    ]
    for run in runs:
        append_run(project_dir, eid, run)
        update_leaderboard(
            project_dir,
            run.method,
            run.metrics,
            run.run_id,
            run.params,
            primary_metric="r2",
            direction="higher_is_better",
            experiment_id=eid,
        )

    # Labbook's pick (first metric of first run is r2 → higher is better).
    progress_runs = load_progress(project_dir, eid)["runs"]
    labbook_best = _find_best_run(progress_runs)
    assert labbook_best is not None
    assert labbook_best["run_id"] == "run-002"

    # progress.get_best_run's pick.
    progress_best = get_best_run(project_dir, eid, metric="r2", direction="higher")
    assert progress_best is not None
    assert progress_best["run_id"] == "run-002"

    # Leaderboard rank 1.
    ranking = load_leaderboard(project_dir)["ranking"]
    rank_one = next(e for e in ranking if e["rank"] == 1)
    assert rank_one["run_id"] == "run-002"
    assert rank_one["method"] == "random_forest"
