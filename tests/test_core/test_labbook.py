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

        path = project_dir / "projectbook" / "results-summary.md"
        content = path.read_text()
        assert "Baseline" in content
        assert "ridge_regression" in content or "0.73" in content


class TestGenerateKeyFindings:
    def test_generates_findings(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        generate_key_findings(project_dir)

        path = project_dir / "projectbook" / "key-findings.md"
        content = path.read_text()
        assert "test-project" in content or "Key Findings" in content


class TestInlineFigureLinking:
    def test_figures_in_artifacts_dir_appear_in_notes(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        """Figures whose stem matches the method name get inlined in notes.md."""
        artifacts = (
            project_dir / "experiments" / experiment_with_runs / "artifacts"
        )
        # Create two PNG artifacts whose names overlap with the run method names
        (artifacts / "linear_regression.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (artifacts / "ridge_regression_plot.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        update_experiment_notes(project_dir, experiment_with_runs)

        notes = (
            project_dir
            / "experiments"
            / experiment_with_runs
            / "labbook"
            / "notes.md"
        ).read_text()

        # Both figures inline with the expected relative path (../artifacts/)
        assert "![Linear regression](../artifacts/linear_regression.png)" in notes
        assert (
            "![Ridge regression plot](../artifacts/ridge_regression_plot.png)"
            in notes
        )

    def test_summary_embeds_figures_section(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        """generate_experiment_summary collects figures into a Figures section."""
        artifacts = (
            project_dir / "experiments" / experiment_with_runs / "artifacts"
        )
        (artifacts / "residuals.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        generate_experiment_summary(project_dir, experiment_with_runs)

        summary = (
            project_dir
            / "experiments"
            / experiment_with_runs
            / "labbook"
            / "summary.md"
        ).read_text()
        assert "## Figures" in summary
        assert "![Residuals](../artifacts/residuals.png)" in summary


class TestMissingExperimentHandling:
    def test_update_notes_raises_for_missing_experiment(
        self, project_dir: Path
    ) -> None:
        """Calling update_experiment_notes for a non-existent experiment raises."""
        with pytest.raises(FileNotFoundError):
            update_experiment_notes(project_dir, "exp-999-does-not-exist")

    def test_results_summary_handles_empty_project(
        self, project_dir: Path
    ) -> None:
        """Projects with no experiments still produce a valid results-summary.md."""
        generate_results_summary(project_dir)
        path = project_dir / "projectbook" / "results-summary.md"
        content = path.read_text()
        assert "# Results Summary" in content
        assert "No experiments completed yet." in content


class TestBestRunLogic:
    def test_best_run_respects_lower_is_better_metrics(
        self, project_dir: Path
    ) -> None:
        """When the first metric is rmse, the lowest-rmse run is picked as best."""
        exp = create_experiment(
            project_dir, name="direction-test", hypothesis="test"
        )
        eid = exp.experiment_id

        # Order metrics dicts so rmse is first — that's the metric that
        # drives direction.  The best run is the one with the lowest rmse.
        append_run(
            project_dir,
            eid,
            RunRecord(
                run_id="run-001",
                method="method_a",
                params={},
                metrics={"rmse": 0.50, "r2": 0.60},
            ),
        )
        append_run(
            project_dir,
            eid,
            RunRecord(
                run_id="run-002",
                method="method_b",
                params={},
                metrics={"rmse": 0.10, "r2": 0.30},
            ),
        )
        append_run(
            project_dir,
            eid,
            RunRecord(
                run_id="run-003",
                method="method_c",
                params={},
                metrics={"rmse": 0.30, "r2": 0.80},
            ),
        )

        generate_experiment_summary(project_dir, eid)
        summary = (
            project_dir / "experiments" / eid / "labbook" / "summary.md"
        ).read_text()
        # Best run is run-002 (lowest rmse) even though its r2 is the worst
        assert "Best run**: run-002 (method_b)" in summary
