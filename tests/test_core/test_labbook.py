"""Tests for labbook generation."""

from pathlib import Path

import pytest

from urika.core.experiment import create_experiment
from urika.core.labbook import (
    generate_experiment_summary,
    generate_key_findings,
    generate_results_summary,
    update_experiment_notes,
)
from urika.core.models import ProjectConfig, RunRecord
from urika.core.progress import append_run
from urika.core.workspace import create_project_workspace


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test"
    config = ProjectConfig(
        name="test-project",
        question="What predicts Y?",
        mode="exploratory",
    )
    create_project_workspace(d, config)
    return d


@pytest.fixture
def experiment_with_runs(project_dir: Path) -> str:
    exp = create_experiment(
        project_dir, name="Baseline", hypothesis="Linear models work"
    )
    eid = exp.experiment_id

    runs = [
        RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={"alpha": 0.1},
            metrics={"r2": 0.72, "rmse": 0.15},
            hypothesis="Baseline linear model",
            observation="R2=0.72, nonlinearity in residuals",
            next_step="Try tree-based methods",
        ),
        RunRecord(
            run_id="run-002",
            method="ridge_regression",
            params={"alpha": 1.0},
            metrics={"r2": 0.73, "rmse": 0.14},
            hypothesis="Regularization helps",
            observation="Marginal improvement",
            next_step="Issue is model form, not overfitting",
        ),
    ]
    for run in runs:
        append_run(project_dir, eid, run)

    return eid


class TestUpdateExperimentNotes:
    def test_appends_run_notes(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        update_experiment_notes(project_dir, experiment_with_runs)

        notes_path = (
            project_dir / "experiments" / experiment_with_runs / "labbook" / "notes.md"
        )
        content = notes_path.read_text()
        assert "linear_regression" in content
        assert "ridge_regression" in content
        assert "R2=0.72" in content

    def test_includes_metrics(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        update_experiment_notes(project_dir, experiment_with_runs)

        notes_path = (
            project_dir / "experiments" / experiment_with_runs / "labbook" / "notes.md"
        )
        content = notes_path.read_text()
        assert "r2" in content
        assert "0.72" in content


class TestGenerateExperimentSummary:
    def test_generates_summary(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        generate_experiment_summary(project_dir, experiment_with_runs)

        summary_path = (
            project_dir
            / "experiments"
            / experiment_with_runs
            / "labbook"
            / "summary.md"
        )
        assert summary_path.exists()
        content = summary_path.read_text()
        assert "Baseline" in content
        assert "run-001" in content or "linear_regression" in content

    def test_summary_includes_best_run(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        generate_experiment_summary(project_dir, experiment_with_runs)

        summary_path = (
            project_dir
            / "experiments"
            / experiment_with_runs
            / "labbook"
            / "summary.md"
        )
        content = summary_path.read_text()
        assert "0.73" in content


class TestGenerateResultsSummary:
    def test_generates_table(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        generate_results_summary(project_dir)

        path = project_dir / "labbook" / "results-summary.md"
        content = path.read_text()
        assert "Baseline" in content
        assert "ridge_regression" in content or "0.73" in content


class TestGenerateKeyFindings:
    def test_generates_findings(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        generate_key_findings(project_dir)

        path = project_dir / "labbook" / "key-findings.md"
        content = path.read_text()
        assert "test-project" in content or "Key Findings" in content
