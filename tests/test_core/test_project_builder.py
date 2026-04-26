"""Tests for ProjectBuilder."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from urika.core.project_builder import ProjectBuilder


class TestProjectBuilderInit:
    def test_creates_with_name_and_source(self, tmp_path: Path) -> None:
        source = tmp_path / "data"
        source.mkdir()
        (source / "test.csv").write_text("x,y\n1,2\n")
        builder = ProjectBuilder(
            name="test-project",
            source_path=source,
            projects_dir=tmp_path / "projects",
        )
        assert builder.name == "test-project"


class TestProjectBuilderScan:
    def test_scan_classifies_files(self, tmp_path: Path) -> None:
        source = tmp_path / "repo"
        source.mkdir()
        (source / "data.csv").write_text("x,y\n1,2\n")
        (source / "README.md").write_text("# About\n")
        builder = ProjectBuilder(
            name="test", source_path=source, projects_dir=tmp_path / "projects"
        )
        scan = builder.scan()
        assert len(scan.data_files) == 1
        assert len(scan.docs) == 1

    def test_scan_finds_nested_csvs(self, tmp_path: Path) -> None:
        source = tmp_path / "repo"
        sub = source / "data" / "group1"
        sub.mkdir(parents=True)
        (sub / "t1.csv").write_text("x\n1\n")
        (sub / "t2.csv").write_text("x\n2\n")
        builder = ProjectBuilder(
            name="test", source_path=source, projects_dir=tmp_path / "projects"
        )
        scan = builder.scan()
        assert len(scan.data_files) == 2


class TestProjectBuilderProfile:
    def test_profile_returns_summary(self, tmp_path: Path) -> None:
        source = tmp_path / "data"
        source.mkdir()
        (source / "test.csv").write_text("x,y\n1,2\n3,4\n")
        builder = ProjectBuilder(
            name="test", source_path=source, projects_dir=tmp_path / "projects"
        )
        builder.scan()
        summary = builder.profile_data()
        assert summary.n_rows == 2

    def test_profile_without_scan_auto_scans(self, tmp_path: Path) -> None:
        source = tmp_path / "data"
        source.mkdir()
        (source / "test.csv").write_text("x,y\n1,2\n")
        builder = ProjectBuilder(
            name="test", source_path=source, projects_dir=tmp_path / "projects"
        )
        summary = builder.profile_data()
        assert summary.n_rows == 1

    def test_profile_no_data_raises(self, tmp_path: Path) -> None:
        source = tmp_path / "empty"
        source.mkdir()
        builder = ProjectBuilder(
            name="test", source_path=source, projects_dir=tmp_path / "projects"
        )
        builder.scan()
        with pytest.raises(ValueError, match="No data files"):
            builder.profile_data()


class TestProjectBuilderWrite:
    def _make_builder(self, tmp_path: Path) -> ProjectBuilder:
        source = tmp_path / "data"
        source.mkdir()
        (source / "test.csv").write_text("x,y\n1,2\n")
        builder = ProjectBuilder(
            name="test",
            source_path=source,
            projects_dir=tmp_path / "projects",
            description="Test description",
            question="What is X?",
            mode="exploratory",
        )
        builder.scan()
        return builder

    def test_write_creates_workspace(self, tmp_path: Path) -> None:
        builder = self._make_builder(tmp_path)
        project_dir = builder.write_project()
        assert (project_dir / "urika.toml").exists()
        assert (project_dir / "experiments").is_dir()
        assert (project_dir / "tools").is_dir()
        assert (project_dir / "methods").is_dir()

    def test_write_stores_data_source(self, tmp_path: Path) -> None:
        builder = self._make_builder(tmp_path)
        project_dir = builder.write_project()
        with open(project_dir / "urika.toml", "rb") as f:
            data = tomllib.load(f)
        assert "data" in data
        assert data["data"]["format"] == "csv"

    def test_write_stores_description(self, tmp_path: Path) -> None:
        builder = self._make_builder(tmp_path)
        project_dir = builder.write_project()
        with open(project_dir / "urika.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["description"] == "Test description"

    def test_write_suggestions(self, tmp_path: Path) -> None:
        builder = self._make_builder(tmp_path)
        builder.set_initial_suggestions({"suggestions": [{"name": "baseline"}]})
        project_dir = builder.write_project()
        suggestions_path = project_dir / "suggestions" / "initial.json"
        assert suggestions_path.exists()
        data = json.loads(suggestions_path.read_text())
        assert "suggestions" in data

    def test_write_tasks(self, tmp_path: Path) -> None:
        builder = self._make_builder(tmp_path)
        builder.add_task(
            {"name": "derive labels", "description": "Create target column"}
        )
        project_dir = builder.write_project()
        tasks_path = project_dir / "tasks" / "initial.json"
        assert tasks_path.exists()
        data = json.loads(tasks_path.read_text())
        assert len(data) == 1

    def test_write_no_suggestions_skips_file(self, tmp_path: Path) -> None:
        builder = self._make_builder(tmp_path)
        project_dir = builder.write_project()
        assert not (project_dir / "suggestions" / "initial.json").exists()

    def test_write_creates_criteria(self, tmp_path: Path) -> None:
        builder = self._make_builder(tmp_path)
        project_dir = builder.write_project()
        criteria_path = project_dir / "criteria.json"
        assert criteria_path.exists()
        data = json.loads(criteria_path.read_text())
        assert len(data["versions"]) == 1
        assert data["versions"][0]["set_by"] == "project_builder"

    def test_write_directory_data_format(self, tmp_path: Path) -> None:
        source = tmp_path / "data"
        sub = source / "group1"
        sub.mkdir(parents=True)
        (sub / "t1.csv").write_text("x\n1\n")
        (sub / "t2.csv").write_text("x\n2\n")
        builder = ProjectBuilder(
            name="test",
            source_path=source,
            projects_dir=tmp_path / "projects",
            question="Q?",
            mode="exploratory",
        )
        builder.scan()
        project_dir = builder.write_project()
        with open(project_dir / "urika.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["data"]["format"] == "csv_directory"


class TestProjectBuilderEndpointInheritance:
    """write_project must not duplicate the global private endpoint when
    the user picks the same URL — the runtime loader inherits from
    globals (commit 1) so a project-local copy only invites drift."""

    def _make_builder(
        self, tmp_path: Path, *, mode: str, url: str
    ) -> ProjectBuilder:
        source = tmp_path / "data"
        source.mkdir()
        (source / "test.csv").write_text("x,y\n1,2\n")
        builder = ProjectBuilder(
            name="test",
            source_path=source,
            projects_dir=tmp_path / "projects",
            question="Q?",
            mode="exploratory",
        )
        builder.scan()
        builder.privacy_mode = mode
        builder.private_endpoint_url = url
        return builder

    def test_url_matches_global_skips_project_endpoint_write(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """User picks a URL that matches globals' [privacy.endpoints.private] —
        the project TOML carries [privacy].mode only, not the duplicate
        endpoint."""
        urika_home = tmp_path / "home"
        urika_home.mkdir()
        monkeypatch.setenv("URIKA_HOME", str(urika_home))
        (urika_home / "settings.toml").write_text(
            '[privacy.endpoints.private]\n'
            'base_url = "http://localhost:11434"\n',
            encoding="utf-8",
        )

        builder = self._make_builder(
            tmp_path, mode="private", url="http://localhost:11434"
        )
        project_dir = builder.write_project()

        with open(project_dir / "urika.toml", "rb") as f:
            data = tomllib.load(f)
        privacy = data.get("privacy", {})
        assert privacy.get("mode") == "private"
        # No project-local duplicate — runtime loader inherits.
        assert "endpoints" not in privacy

    def test_url_differs_from_global_writes_project_endpoint(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """User picks a URL that differs from globals — the project TOML
        carries the override so the runtime loader's collision rule
        (project wins) takes effect."""
        urika_home = tmp_path / "home"
        urika_home.mkdir()
        monkeypatch.setenv("URIKA_HOME", str(urika_home))
        (urika_home / "settings.toml").write_text(
            '[privacy.endpoints.private]\n'
            'base_url = "http://localhost:11434"\n',
            encoding="utf-8",
        )

        builder = self._make_builder(
            tmp_path, mode="private", url="http://my-server:8080"
        )
        project_dir = builder.write_project()

        with open(project_dir / "urika.toml", "rb") as f:
            data = tomllib.load(f)
        ep = data["privacy"]["endpoints"]["private"]
        assert ep["base_url"] == "http://my-server:8080"

    def test_no_global_endpoint_writes_project_endpoint(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Without any global endpoint, the user's URL is the only
        source of truth — write it to the project TOML."""
        urika_home = tmp_path / "home"
        urika_home.mkdir()
        monkeypatch.setenv("URIKA_HOME", str(urika_home))
        # No settings.toml at all.

        builder = self._make_builder(
            tmp_path, mode="private", url="http://localhost:11434"
        )
        project_dir = builder.write_project()

        with open(project_dir / "urika.toml", "rb") as f:
            data = tomllib.load(f)
        ep = data["privacy"]["endpoints"]["private"]
        assert ep["base_url"] == "http://localhost:11434"
