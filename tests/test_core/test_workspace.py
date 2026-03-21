"""Tests for project workspace creation."""

from pathlib import Path

import pytest

from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace, load_project_config


class TestCreateProjectWorkspace:
    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "sleep-study"
        config = ProjectConfig(
            name="sleep-study",
            question="What predicts sleep quality?",
            mode="exploratory",
        )
        create_project_workspace(project_dir, config)

        assert (project_dir / "urika.toml").exists()
        assert (project_dir / "data").is_dir()
        assert (project_dir / "tools").is_dir()
        assert (project_dir / "methods").is_dir()
        assert (project_dir / "knowledge").is_dir()
        assert (project_dir / "experiments").is_dir()
        assert (project_dir / "projectbook").is_dir()

    def test_writes_urika_toml(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "test-project"
        config = ProjectConfig(
            name="test-project",
            question="Does X cause Y?",
            mode="confirmatory",
        )
        create_project_workspace(project_dir, config)

        loaded = load_project_config(project_dir)
        assert loaded.name == "test-project"
        assert loaded.mode == "confirmatory"

    def test_creates_projectbook_stubs(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "test"
        config = ProjectConfig(name="test", question="?", mode="exploratory")
        create_project_workspace(project_dir, config)

        assert (project_dir / "projectbook" / "key-findings.md").exists()
        assert (project_dir / "projectbook" / "results-summary.md").exists()
        assert (project_dir / "projectbook" / "progress-overview.md").exists()

    def test_raises_if_dir_exists(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "exists"
        project_dir.mkdir()
        (project_dir / "urika.toml").write_text("")

        config = ProjectConfig(name="exists", question="?", mode="exploratory")
        with pytest.raises(FileExistsError):
            create_project_workspace(project_dir, config)


class TestLoadProjectConfig:
    def test_load(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "test"
        config = ProjectConfig(
            name="test",
            question="Does X work?",
            mode="pipeline",
            data_paths=["data/input.csv"],
        )
        create_project_workspace(project_dir, config)

        loaded = load_project_config(project_dir)
        assert loaded.name == "test"
        assert loaded.mode == "pipeline"
        assert loaded.data_paths == ["data/input.csv"]

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_project_config(tmp_path / "nope")
