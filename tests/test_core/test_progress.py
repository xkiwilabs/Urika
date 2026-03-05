"""Tests for append-only progress tracking."""

from pathlib import Path

import pytest

from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig, RunRecord
from urika.core.progress import (
    append_run,
    get_best_run,
    load_progress,
    update_experiment_status,
)
from urika.core.workspace import create_project_workspace


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test"
    config = ProjectConfig(name="test", question="?", mode="exploratory")
    create_project_workspace(d, config)
    return d


@pytest.fixture
def experiment_id(project_dir: Path) -> str:
    exp = create_experiment(project_dir, name="Test", hypothesis="Test hypothesis")
    return exp.experiment_id


class TestAppendRun:
    def test_append_single_run(self, project_dir: Path, experiment_id: str) -> None:
        run = RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={"alpha": 0.1},
            metrics={"r2": 0.72},
        )
        append_run(project_dir, experiment_id, run)

        progress = load_progress(project_dir, experiment_id)
        assert len(progress["runs"]) == 1
        assert progress["runs"][0]["run_id"] == "run-001"

    def test_append_multiple_runs(self, project_dir: Path, experiment_id: str) -> None:
        for i in range(3):
            run = RunRecord(
                run_id=f"run-{i:03d}",
                method="test",
                params={},
                metrics={"r2": 0.1 * i},
            )
            append_run(project_dir, experiment_id, run)

        progress = load_progress(project_dir, experiment_id)
        assert len(progress["runs"]) == 3

    def test_append_is_additive(self, project_dir: Path, experiment_id: str) -> None:
        """Appending doesn't overwrite previous runs."""
        run1 = RunRecord(run_id="run-001", method="a", params={}, metrics={"r2": 0.5})
        run2 = RunRecord(run_id="run-002", method="b", params={}, metrics={"r2": 0.7})
        append_run(project_dir, experiment_id, run1)
        append_run(project_dir, experiment_id, run2)

        progress = load_progress(project_dir, experiment_id)
        assert progress["runs"][0]["method"] == "a"
        assert progress["runs"][1]["method"] == "b"


class TestGetBestRun:
    def test_best_run_higher_is_better(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        for i, r2 in enumerate([0.5, 0.9, 0.3]):
            run = RunRecord(
                run_id=f"run-{i:03d}",
                method="test",
                params={},
                metrics={"r2": r2},
            )
            append_run(project_dir, experiment_id, run)

        best = get_best_run(project_dir, experiment_id, metric="r2", direction="higher")
        assert best is not None
        assert best["run_id"] == "run-001"
        assert best["metrics"]["r2"] == 0.9

    def test_best_run_lower_is_better(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        for i, rmse in enumerate([0.5, 0.1, 0.3]):
            run = RunRecord(
                run_id=f"run-{i:03d}",
                method="test",
                params={},
                metrics={"rmse": rmse},
            )
            append_run(project_dir, experiment_id, run)

        best = get_best_run(
            project_dir, experiment_id, metric="rmse", direction="lower"
        )
        assert best is not None
        assert best["metrics"]["rmse"] == 0.1

    def test_best_run_empty(self, project_dir: Path, experiment_id: str) -> None:
        best = get_best_run(project_dir, experiment_id, metric="r2", direction="higher")
        assert best is None


class TestUpdateExperimentStatus:
    def test_update_status(self, project_dir: Path, experiment_id: str) -> None:
        update_experiment_status(project_dir, experiment_id, "in_progress")
        progress = load_progress(project_dir, experiment_id)
        assert progress["status"] == "in_progress"

    def test_update_to_completed(self, project_dir: Path, experiment_id: str) -> None:
        update_experiment_status(project_dir, experiment_id, "completed")
        progress = load_progress(project_dir, experiment_id)
        assert progress["status"] == "completed"
