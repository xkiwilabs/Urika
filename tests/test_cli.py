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


class TestResolveProject:
    """Tests confirming status works after _resolve_project refactor."""

    def test_status_shows_project_info(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "my-proj", "-q", "Does refactor work?", "-m", "exploratory"],
            env=urika_env,
        )
        result = runner.invoke(cli, ["status", "my-proj"], env=urika_env)
        assert result.exit_code == 0
        assert "my-proj" in result.output
        assert "Does refactor work?" in result.output

    def test_status_nonexistent_uses_resolve(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["status", "no-such-project"], env=urika_env)
        assert result.exit_code != 0
        assert "not found" in result.output


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


def _create_project(
    runner: CliRunner, urika_env: dict[str, str], name: str = "test-proj"
) -> None:
    """Helper to create a project for tests."""
    result = runner.invoke(
        cli,
        ["new", name, "-q", "Does X?", "-m", "exploratory"],
        env=urika_env,
    )
    assert result.exit_code == 0, result.output


class TestExperimentCreateCommand:
    def test_creates_experiment(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli,
            [
                "experiment",
                "create",
                "test-proj",
                "baseline",
                "--hypothesis",
                "Linear is enough",
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "exp-001" in result.output

    def test_creates_second_experiment(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "first", "--hypothesis", "H1"],
            env=urika_env,
        )
        result = runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "second", "--hypothesis", "H2"],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "exp-002" in result.output

    def test_nonexistent_project_errors(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            ["experiment", "create", "nope", "baseline"],
            env=urika_env,
        )
        assert result.exit_code != 0
        assert "not found" in result.output


class TestExperimentListCommand:
    def test_empty_shows_message(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(cli, ["experiment", "list", "test-proj"], env=urika_env)
        assert result.exit_code == 0
        assert "No experiments yet." in result.output

    def test_shows_experiments_after_create(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            [
                "experiment",
                "create",
                "test-proj",
                "baseline",
                "--hypothesis",
                "Linear is enough",
            ],
            env=urika_env,
        )
        result = runner.invoke(cli, ["experiment", "list", "test-proj"], env=urika_env)
        assert result.exit_code == 0
        assert "exp-001" in result.output
        assert "baseline" in result.output

    def test_nonexistent_project_errors(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["experiment", "list", "nope"], env=urika_env)
        assert result.exit_code != 0
        assert "not found" in result.output


class TestResultsCommand:
    def test_empty_leaderboard(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(cli, ["results", "test-proj"], env=urika_env)
        assert result.exit_code == 0
        assert "No results yet." in result.output

    def test_shows_leaderboard(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        from urika.evaluation.leaderboard import update_leaderboard

        _create_project(runner, urika_env)
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "test-proj"
        update_leaderboard(
            project_dir,
            method="linear_regression",
            metrics={"r2": 0.85, "rmse": 0.12},
            run_id="run-001",
            params={"alpha": 0.1},
            primary_metric="r2",
            direction="higher_is_better",
        )
        result = runner.invoke(cli, ["results", "test-proj"], env=urika_env)
        assert result.exit_code == 0
        assert "linear_regression" in result.output
        assert "0.85" in result.output

    def test_shows_experiment_runs(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        from urika.core.models import RunRecord
        from urika.core.progress import append_run

        _create_project(runner, urika_env)
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "test-proj"
        # Create an experiment first via CLI
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        # Get the experiment ID from the experiments directory
        exp_dirs = sorted((project_dir / "experiments").iterdir())
        exp_id = exp_dirs[0].name

        run = RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={"alpha": 0.1},
            metrics={"r2": 0.75},
            hypothesis="Baseline",
            observation="Decent fit",
            next_step="Try RF",
        )
        append_run(project_dir, exp_id, run)

        result = runner.invoke(
            cli,
            ["results", "test-proj", "--experiment", exp_id],
            env=urika_env,
        )
        assert result.exit_code == 0
        assert "run-001" in result.output
        assert "linear_regression" in result.output

    def test_nonexistent_project_errors(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["results", "nope"], env=urika_env)
        assert result.exit_code != 0
        assert "not found" in result.output


class TestMethodsCommand:
    def test_lists_builtins(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        result = runner.invoke(cli, ["methods"], env=urika_env)
        assert result.exit_code == 0
        assert "linear_regression" in result.output
        assert "random_forest" in result.output
        assert "paired_t_test" in result.output

    def test_filter_by_category(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["methods", "--category", "regression"], env=urika_env
        )
        assert result.exit_code == 0
        assert "linear_regression" in result.output
        assert "paired_t_test" not in result.output

    def test_empty_category(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        result = runner.invoke(
            cli, ["methods", "--category", "nonexistent"], env=urika_env
        )
        assert result.exit_code == 0
        assert "No methods" in result.output


class TestToolsCommand:
    def test_lists_builtins(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        result = runner.invoke(cli, ["tools"], env=urika_env)
        assert result.exit_code == 0
        assert "data_profiler" in result.output
        assert "correlation_analysis" in result.output

    def test_filter_by_category(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["tools", "--category", "exploration"], env=urika_env
        )
        assert result.exit_code == 0
        assert "data_profiler" in result.output

    def test_empty_category(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        result = runner.invoke(
            cli, ["tools", "--category", "nonexistent"], env=urika_env
        )
        assert result.exit_code == 0
        assert "No tools" in result.output
