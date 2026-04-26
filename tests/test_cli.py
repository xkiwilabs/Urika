"""Tests for the Urika CLI."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
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

    def test_with_description(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "new",
                "desc-proj",
                "-q",
                "Does X?",
                "-m",
                "exploratory",
                "--description",
                "A study of X",
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "Created project" in result.output

    def test_with_data_directory(
        self, runner: CliRunner, urika_env: dict[str, str], tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "source_data"
        data_dir.mkdir()
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        df.to_csv(data_dir / "sample.csv", index=False)

        result = runner.invoke(
            cli,
            [
                "new",
                "data-proj",
                "-q",
                "What predicts B?",
                "-m",
                "exploratory",
                "--data",
                str(data_dir),
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "Data files" in result.output
        assert "Created project" in result.output

    def test_with_data_file(
        self, runner: CliRunner, urika_env: dict[str, str], tmp_path: Path
    ) -> None:
        csv_file = tmp_path / "data.csv"
        df = pd.DataFrame({"x": [10, 20], "y": [30, 40]})
        df.to_csv(csv_file, index=False)

        result = runner.invoke(
            cli,
            [
                "new",
                "file-proj",
                "-q",
                "Predict Y?",
                "-m",
                "confirmatory",
                "--data",
                str(csv_file),
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "Created project" in result.output

    def test_data_path_not_found_warns(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "new",
                "bad-proj",
                "-q",
                "Does X?",
                "-m",
                "exploratory",
                "--data",
                "/nonexistent/path",
            ],
            env=urika_env,
            input="\n",  # skip re-prompt with empty input
        )
        assert "not found" in result.output.lower()

    def test_invalid_mode(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        result = runner.invoke(
            cli,
            ["new", "test", "-q", "?", "-m", "invalid"],
            env=urika_env,
        )
        assert result.exit_code != 0

    def test_json_private_mode_without_endpoint_aborts(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """``urika new --json --privacy-mode private`` with no global
        endpoint configured must exit non-zero and emit a JSON error
        rather than silently saving an unrunnable project."""
        result = runner.invoke(
            cli,
            [
                "new",
                "priv-proj",
                "-q",
                "Q?",
                "-m",
                "exploratory",
                "--privacy-mode",
                "private",
                "--json",
            ],
            env=urika_env,
        )
        assert result.exit_code != 0
        # Output is a JSON error blob carrying the fix instruction.
        assert "private endpoint" in result.output.lower() or "endpoint" in result.output.lower()

    def test_json_hybrid_mode_without_endpoint_aborts(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """Hybrid mode also requires a private endpoint — the
        forced-private agents (data_agent / tool_builder) need it."""
        result = runner.invoke(
            cli,
            [
                "new",
                "hyb-proj",
                "-q",
                "Q?",
                "-m",
                "exploratory",
                "--privacy-mode",
                "hybrid",
                "--json",
            ],
            env=urika_env,
        )
        assert result.exit_code != 0

    def test_json_private_mode_with_global_endpoint_succeeds(
        self, runner: CliRunner, urika_env: dict[str, str], tmp_path: Path
    ) -> None:
        """When a global private endpoint is configured (via
        ~/.urika/settings.toml), --json + --privacy-mode private must
        succeed."""
        # Seed a global endpoint
        settings = Path(urika_env["URIKA_HOME"]) / "settings.toml"
        settings.write_text(
            "[privacy.endpoints.private]\n"
            'base_url = "http://localhost:11434"\n',
            encoding="utf-8",
        )
        result = runner.invoke(
            cli,
            [
                "new",
                "priv-ok",
                "-q",
                "Q?",
                "-m",
                "exploratory",
                "--privacy-mode",
                "private",
                "--json",
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output


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
    # Prompts: privacy(1=open), data_path(empty), description(empty),
    #          web_search(n), venv(n), run(5=skip)
    result = runner.invoke(
        cli,
        ["new", name, "-q", "Does X?", "-m", "exploratory"],
        env=urika_env,
        input="1\n\n\nn\nn\n5\n",
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
    def test_no_methods_yet(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(cli, ["methods", "test-proj"], env=urika_env)
        assert result.exit_code == 0
        assert "No methods created yet." in result.output

    def test_requires_project_argument(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["methods"], env=urika_env)
        assert result.exit_code != 0

    def test_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["methods", "nope"], env=urika_env)
        assert result.exit_code != 0
        assert "not found" in result.output


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


class TestRunCommand:
    def test_run_completes(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        with (
            patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner"),
            patch(
                "urika.orchestrator.run_experiment", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = {"status": "completed", "turns": 3, "error": None}
            result = runner.invoke(cli, ["run", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "completed" in result.output
        assert "3 turns" in result.output

    def test_run_with_experiment_flag(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        with (
            patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner"),
            patch(
                "urika.orchestrator.run_experiment", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = {"status": "completed", "turns": 1, "error": None}
            result = runner.invoke(
                cli,
                ["run", "test-proj", "--experiment", "exp-001-baseline"],
                env=urika_env,
            )
        assert result.exit_code == 0

    def test_run_failed(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        with (
            patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner"),
            patch(
                "urika.orchestrator.run_experiment", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = {
                "status": "failed",
                "turns": 2,
                "error": "SDK error",
            }
            result = runner.invoke(cli, ["run", "test-proj"], env=urika_env)
        assert result.exit_code == 0
        assert "failed" in result.output

    def test_run_no_experiments(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(cli, ["run", "test-proj"], env=urika_env)
        assert result.exit_code != 0
        assert "No experiments" in result.output

    def test_run_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["run", "nope"], env=urika_env)
        assert result.exit_code != 0

    def test_run_dry_run_prints_plan_without_executing(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """--dry-run outputs the planned pipeline and returns 0 without calling any runner."""
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        with (
            patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner") as mock_sdk,
            patch(
                "urika.orchestrator.run_experiment", new_callable=AsyncMock
            ) as mock_run,
            patch(
                "urika.orchestrator.run_project", new_callable=AsyncMock
            ) as mock_run_project,
        ):
            result = runner.invoke(
                cli, ["run", "test-proj", "--dry-run"], env=urika_env
            )
        assert result.exit_code == 0, result.output
        # Runner must not have been invoked.
        mock_run.assert_not_called()
        mock_run_project.assert_not_called()
        mock_sdk.assert_not_called()
        # Output should identify this as a dry run.
        assert (
            "dry run" in result.output.lower()
            or "would run" in result.output.lower()
        )
        # Output should mention the pipeline stages.
        out_lower = result.output.lower()
        assert "planning" in out_lower
        assert "task" in out_lower
        assert "evaluator" in out_lower
        assert "advisor" in out_lower
        # Should tell user how to actually execute.
        assert "--dry-run" in result.output

    def test_run_dry_run_missing_project_errors(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """--dry-run still validates the project exists."""
        result = runner.invoke(
            cli, ["run", "not-a-project", "--dry-run"], env=urika_env
        )
        assert result.exit_code != 0


class TestRunContinueFlag:
    def test_continue_passes_resume_true(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        with (
            patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner"),
            patch(
                "urika.orchestrator.run_experiment", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = {"status": "completed", "turns": 3, "error": None}
            result = runner.invoke(
                cli, ["run", "test-proj", "--resume"], env=urika_env
            )
        assert result.exit_code == 0, result.output
        assert mock_run.call_args.kwargs["resume"] is True
        assert "Resuming experiment" in result.output

    def test_run_without_continue_passes_resume_false(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        with (
            patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner"),
            patch(
                "urika.orchestrator.run_experiment", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = {"status": "completed", "turns": 1, "error": None}
            result = runner.invoke(cli, ["run", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "resume" in mock_run.call_args.kwargs
        assert mock_run.call_args.kwargs["resume"] is False

    def test_continue_with_experiment_flag(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        with (
            patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner"),
            patch(
                "urika.orchestrator.run_experiment", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = {"status": "completed", "turns": 5, "error": None}
            result = runner.invoke(
                cli,
                [
                    "run",
                    "test-proj",
                    "--experiment",
                    "exp-001-baseline",
                    "--resume",
                ],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        assert mock_run.call_args.kwargs["resume"] is True
        # Verify experiment ID was also passed correctly
        assert mock_run.call_args.args[1] == "exp-001-baseline"


class TestReportCommand:
    def test_report_project_level(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(cli, ["report", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "results-summary.md" in result.output
        assert "key-findings.md" in result.output

    def test_report_experiment_level(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "test-proj"
        exp_dirs = sorted((project_dir / "experiments").iterdir())
        exp_id = exp_dirs[0].name

        result = runner.invoke(
            cli,
            ["report", "test-proj", "--experiment", exp_id],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "summary.md" in result.output
        assert "notes.md" in result.output

    def test_report_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["report", "nope"], env=urika_env)
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_report_nonexistent_experiment(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli,
            ["report", "test-proj", "--experiment", "exp-999-fake"],
            env=urika_env,
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_report_creates_files(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "test-proj"

        # Run project-level report
        result = runner.invoke(cli, ["report", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output

        # Check that projectbook files exist on disk
        assert (project_dir / "projectbook" / "results-summary.md").exists()
        assert (project_dir / "projectbook" / "key-findings.md").exists()

        # Run experiment-level report
        exp_dirs = sorted((project_dir / "experiments").iterdir())
        exp_id = exp_dirs[0].name
        result = runner.invoke(
            cli,
            ["report", "test-proj", "--experiment", exp_id],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert (project_dir / "experiments" / exp_id / "labbook" / "notes.md").exists()
        assert (
            project_dir / "experiments" / exp_id / "labbook" / "summary.md"
        ).exists()


class TestKnowledgeIngestCommand:
    def test_ingests_text_file(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "test-proj", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        projects_dir = Path(urika_env["URIKA_PROJECTS_DIR"])
        knowledge_dir = projects_dir / "test-proj" / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        note = knowledge_dir / "notes.txt"
        note.write_text("Some research notes about regression.")

        result = runner.invoke(
            cli,
            ["knowledge", "ingest", "test-proj", str(note)],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "k-001" in result.output

    def test_ingest_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            ["knowledge", "ingest", "nope", "/tmp/file.txt"],
            env=urika_env,
        )
        assert result.exit_code != 0
        assert "not found" in result.output


class TestKnowledgeSearchCommand:
    def test_search_with_results(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "test-proj", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        projects_dir = Path(urika_env["URIKA_PROJECTS_DIR"])
        knowledge_dir = projects_dir / "test-proj" / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "notes.txt").write_text("Regression analysis is useful.")
        runner.invoke(
            cli,
            ["knowledge", "ingest", "test-proj", str(knowledge_dir / "notes.txt")],
            env=urika_env,
        )

        result = runner.invoke(
            cli,
            ["knowledge", "search", "test-proj", "regression"],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "notes.txt" in result.output

    def test_search_no_results(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "test-proj", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        result = runner.invoke(
            cli,
            ["knowledge", "search", "test-proj", "quantum"],
            env=urika_env,
        )
        assert result.exit_code == 0
        assert "No results" in result.output


class TestKnowledgeListCommand:
    def test_list_empty(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        runner.invoke(
            cli,
            ["new", "test-proj", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        result = runner.invoke(
            cli,
            ["knowledge", "list", "test-proj"],
            env=urika_env,
        )
        assert result.exit_code == 0
        assert "No knowledge" in result.output

    def test_list_populated(self, runner: CliRunner, urika_env: dict[str, str]) -> None:
        runner.invoke(
            cli,
            ["new", "test-proj", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        projects_dir = Path(urika_env["URIKA_PROJECTS_DIR"])
        knowledge_dir = projects_dir / "test-proj" / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "notes.txt").write_text("Some notes.")
        runner.invoke(
            cli,
            ["knowledge", "ingest", "test-proj", str(knowledge_dir / "notes.txt")],
            env=urika_env,
        )

        result = runner.invoke(
            cli,
            ["knowledge", "list", "test-proj"],
            env=urika_env,
        )
        assert result.exit_code == 0
        assert "k-001" in result.output
        assert "notes.txt" in result.output


class TestInspectCommand:
    def test_inspect_shows_schema(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "test-proj"
        data_dir = project_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(
            {"age": [25, 30, 35], "score": [80.5, 90.1, 85.3], "name": ["A", "B", "C"]}
        )
        df.to_csv(data_dir / "sample.csv", index=False)

        result = runner.invoke(cli, ["inspect", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "Rows: 3" in result.output
        assert "Columns: 3" in result.output
        assert "age" in result.output
        assert "score" in result.output
        assert "name" in result.output
        assert "Schema:" in result.output

    def test_inspect_no_data_dir(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        # data/ directory exists from project creation but has no CSVs
        result = runner.invoke(cli, ["inspect", "test-proj"], env=urika_env)
        assert result.exit_code != 0
        assert "No supported data files" in result.output or "No CSV files" in result.output or "No data/" in result.output

    def test_inspect_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["inspect", "nope"], env=urika_env)
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_inspect_with_data_flag(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "test-proj"
        data_dir = project_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
        specific = data_dir / "specific.csv"
        df.to_csv(specific, index=False)

        result = runner.invoke(
            cli,
            ["inspect", "test-proj", "--data", str(specific)],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "specific.csv" in result.output
        assert "Rows: 3" in result.output


class TestLogsCommand:
    def test_logs_shows_runs(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        from urika.core.models import RunRecord
        from urika.core.progress import append_run

        _create_project(runner, urika_env)
        project_dir = Path(urika_env["URIKA_PROJECTS_DIR"]) / "test-proj"
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
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

        result = runner.invoke(cli, ["logs", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "run-001" in result.output
        assert "linear_regression" in result.output
        assert "r2=0.75" in result.output
        assert "Hypothesis: Baseline" in result.output
        assert "Observation: Decent fit" in result.output
        assert "Next step: Try RF" in result.output

    def test_logs_no_experiments(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(cli, ["logs", "test-proj"], env=urika_env)
        assert result.exit_code != 0
        assert "No experiments" in result.output

    def test_logs_empty_runs(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
            env=urika_env,
        )
        result = runner.invoke(cli, ["logs", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "No runs recorded" in result.output

    def test_logs_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["logs", "nope"], env=urika_env)
        assert result.exit_code != 0
        assert "not found" in result.output


class TestErrorHandlerIntegration:
    """The top-level CLI group renders UrikaError subclasses as
    message + optional hint, exits 2, and never leaks a traceback.
    This replaces the older ClickException rendering for migrated sites."""

    def test_config_error_from_resolve_project_renders_with_hint(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["logs", "nonexistent-project"], env=urika_env)
        assert result.exit_code == 2, result.output
        assert "not found in registry" in result.output
        assert "urika list" in result.output  # hint mentions the remediation
        # No traceback leaked.
        assert "Traceback" not in result.output

    def test_config_error_from_ensure_project_renders_with_hint(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        # No projects registered; an ambiguous invocation should hit _ensure_project.
        # Use a command that accepts no args and requires a project.
        result = runner.invoke(cli, ["logs"], env=urika_env)
        assert result.exit_code == 2, result.output
        assert "No projects registered" in result.output
        assert "urika new" in result.output  # hint
        assert "Traceback" not in result.output
