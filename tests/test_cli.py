"""Tests for the Urika CLI."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from urika.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def urika_env(tmp_path: Path) -> dict[str, str]:
    """Environment with URIKA_HOME and URIKA_PROJECTS set."""
    urika_home = tmp_path / ".urika"
    urika_home.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    return {
        "URIKA_HOME": str(urika_home),
        "URIKA_PROJECTS_DIR": str(projects_dir),
    }


class TestNewCommand:
    def test_creates_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "new",
                "sleep-study",
                "--question",
                "What predicts sleep quality?",
                "--mode",
                "exploratory",
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "Created project" in result.output

        # Verify project directory exists
        projects_dir = Path(urika_env["URIKA_PROJECTS_DIR"])
        assert (projects_dir / "sleep-study" / "urika.toml").exists()

    def test_registers_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "test", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        # Check registry
        reg_path = Path(urika_env["URIKA_HOME"]) / "projects.json"
        assert reg_path.exists()
        data = json.loads(reg_path.read_text())
        assert "test" in data

    def test_invalid_mode(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        result = runner.invoke(
            cli,
            ["new", "test", "-q", "?", "-m", "invalid"],
            env=urika_env,
        )
        assert result.exit_code != 0


class TestListCommand:
    def test_empty(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        result = runner.invoke(cli, ["list"], env=urika_env)
        assert result.exit_code == 0
        assert "No projects" in result.output

    def test_shows_projects(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        runner.invoke(
            cli,
            ["new", "project-a", "-q", "Question A?", "-m", "exploratory"],
            env=urika_env,
        )
        runner.invoke(
            cli,
            ["new", "project-b", "-q", "Question B?", "-m", "confirmatory"],
            env=urika_env,
        )
        result = runner.invoke(cli, ["list"], env=urika_env)
        assert "project-a" in result.output
        assert "project-b" in result.output


class TestStatusCommand:
    def test_shows_status(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        runner.invoke(
            cli,
            ["new", "test", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        result = runner.invoke(cli, ["status", "test"], env=urika_env)
        assert result.exit_code == 0
        assert "test" in result.output
        assert "Does X?" in result.output

    def test_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["status", "nope"], env=urika_env)
        assert result.exit_code != 0
