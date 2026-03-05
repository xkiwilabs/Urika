"""Tests for experiment lifecycle."""

import json
from pathlib import Path

import pytest

from urika.core.experiment import (
    create_experiment,
    get_next_experiment_id,
    list_experiments,
    load_experiment,
)
from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a project workspace for testing."""
    d = tmp_path / "test-project"
    config = ProjectConfig(name="test", question="?", mode="exploratory")
    create_project_workspace(d, config)
    return d


class TestGetNextExperimentId:
    def test_first_experiment(self, project_dir: Path) -> None:
        assert get_next_experiment_id(project_dir) == "exp-001"

    def test_increments(self, project_dir: Path) -> None:
        create_experiment(
            project_dir,
            name="Baseline",
            hypothesis="Test",
        )
        assert get_next_experiment_id(project_dir) == "exp-002"


class TestCreateExperiment:
    def test_creates_directory_structure(self, project_dir: Path) -> None:
        exp = create_experiment(
            project_dir,
            name="Baseline linear models",
            hypothesis="Linear models establish a reasonable baseline",
        )

        exp_dir = project_dir / "experiments" / exp.experiment_id
        assert exp_dir.is_dir()
        assert (exp_dir / "experiment.json").exists()
        assert (exp_dir / "methods").is_dir()
        assert (exp_dir / "labbook").is_dir()
        assert (exp_dir / "artifacts").is_dir()
        assert (exp_dir / "progress.json").exists()

    def test_experiment_json_content(self, project_dir: Path) -> None:
        exp = create_experiment(
            project_dir,
            name="Baseline",
            hypothesis="Linear models work",
        )
        exp_dir = project_dir / "experiments" / exp.experiment_id
        data = json.loads((exp_dir / "experiment.json").read_text())
        assert data["name"] == "Baseline"
        assert data["hypothesis"] == "Linear models work"
        assert data["status"] == "pending"

    def test_progress_json_initialized(self, project_dir: Path) -> None:
        exp = create_experiment(
            project_dir,
            name="Test",
            hypothesis="Test",
        )
        exp_dir = project_dir / "experiments" / exp.experiment_id
        data = json.loads((exp_dir / "progress.json").read_text())
        assert data["experiment_id"] == exp.experiment_id
        assert data["runs"] == []

    def test_auto_slug_in_id(self, project_dir: Path) -> None:
        exp = create_experiment(
            project_dir,
            name="Baseline Linear Models",
            hypothesis="Test",
        )
        assert exp.experiment_id.startswith("exp-001")
        assert "baseline-linear-models" in exp.experiment_id

    def test_with_builds_on(self, project_dir: Path) -> None:
        exp1 = create_experiment(project_dir, name="First", hypothesis="Test")
        exp2 = create_experiment(
            project_dir,
            name="Second",
            hypothesis="Builds on first",
            builds_on=[exp1.experiment_id],
        )
        assert exp2.builds_on == [exp1.experiment_id]


class TestListExperiments:
    def test_empty(self, project_dir: Path) -> None:
        assert list_experiments(project_dir) == []

    def test_lists_all(self, project_dir: Path) -> None:
        create_experiment(project_dir, name="A", hypothesis="Test A")
        create_experiment(project_dir, name="B", hypothesis="Test B")
        experiments = list_experiments(project_dir)
        assert len(experiments) == 2

    def test_sorted_by_id(self, project_dir: Path) -> None:
        create_experiment(project_dir, name="A", hypothesis="Test")
        create_experiment(project_dir, name="B", hypothesis="Test")
        experiments = list_experiments(project_dir)
        assert experiments[0].experiment_id < experiments[1].experiment_id


class TestLoadExperiment:
    def test_load(self, project_dir: Path) -> None:
        exp = create_experiment(project_dir, name="Test", hypothesis="Test hypothesis")
        loaded = load_experiment(project_dir, exp.experiment_id)
        assert loaded.name == "Test"
        assert loaded.hypothesis == "Test hypothesis"

    def test_load_nonexistent(self, project_dir: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_experiment(project_dir, "exp-999-nope")
