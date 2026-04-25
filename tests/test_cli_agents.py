"""Tests for agent-related CLI commands: advisor, evaluate, plan, present, finalize, build-tool, criteria."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from urika.agents.runner import AgentResult
from urika.cli import cli


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


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


def _create_project(runner: CliRunner, urika_env: dict[str, str]) -> Path:
    """Create a bare project (no experiments). Returns project_dir."""
    result = runner.invoke(
        cli,
        ["new", "test-proj", "-q", "Does X?", "-m", "exploratory"],
        env=urika_env,
        input="1\n\n\nn\nn\n5\n",
    )
    assert result.exit_code == 0, result.output
    return Path(urika_env["URIKA_PROJECTS_DIR"]) / "test-proj"


def _create_project_with_experiment(
    runner: CliRunner, urika_env: dict[str, str]
) -> tuple[Path, str]:
    """Create a project and an experiment, return (project_dir, exp_id)."""
    project_dir = _create_project(runner, urika_env)
    runner.invoke(
        cli,
        ["experiment", "create", "test-proj", "baseline", "--hypothesis", "H1"],
        env=urika_env,
    )
    exp_dirs = sorted((project_dir / "experiments").iterdir())
    exp_id = exp_dirs[0].name
    return project_dir, exp_id


def _mock_agent_result(
    success: bool = True,
    text_output: str = "Agent output here",
    error: str | None = None,
) -> AgentResult:
    """Build a mock AgentResult."""
    return AgentResult(
        success=success,
        messages=[],
        text_output=text_output,
        session_id="test-session",
        tokens_in=100,
        tokens_out=200,
        cost_usd=0.01,
        error=error,
    )


def _extract_json(output: str) -> dict:
    """Extract the first JSON object from CLI output.

    Agent commands emit Spinner text (e.g. '  Thinking') before the JSON
    when running in a non-TTY (CliRunner). This helper finds and parses
    the first JSON object in the output.
    """
    start = output.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in output:\n{output}")
    # Find the matching closing brace
    depth = 0
    for i, ch in enumerate(output[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(output[start : i + 1])
    raise ValueError(f"Unbalanced JSON in output:\n{output}")


def _agent_mocks(mock_result: AgentResult | None = None):
    """Context manager that patches get_runner and AgentRegistry for agent commands."""
    if mock_result is None:
        mock_result = _mock_agent_result()
    return _AgentMockContext(mock_result)


class _AgentMockContext:
    """Reusable context manager wrapping agent patches."""

    def __init__(self, mock_result: AgentResult) -> None:
        self._mock_result = mock_result
        self._patches: list = []

    def __enter__(self):
        p1 = patch("urika.agents.runner.get_runner")
        p2 = patch("urika.agents.registry.AgentRegistry")
        self.mock_get_runner = p1.start()
        self.mock_registry_cls = p2.start()
        self._patches.extend([p1, p2])

        mock_runner = AsyncMock()
        mock_runner.run.return_value = self._mock_result
        self.mock_get_runner.return_value = mock_runner

        mock_registry = MagicMock()
        mock_role = MagicMock()
        mock_role.build_config.return_value = MagicMock(max_turns=25)
        mock_registry.get.return_value = mock_role
        self.mock_registry_cls.return_value = mock_registry

        return self

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------


class TestAdvisorCommand:
    def test_advisor_success_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        with _agent_mocks(_mock_agent_result(text_output="Try random forest next")):
            result = runner.invoke(
                cli,
                ["advisor", "test-proj", "What should I try next?", "--json"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert data["output"] == "Try random forest next"

    def test_advisor_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            ["advisor", "no-such-proj", "question"],
            env=urika_env,
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_advisor_success_plain(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(text_output="Consider ensemble methods")
        ):
            # _offer_to_run_advisor_suggestions is called as a bare name in
            # agents.py but is defined in run.py. Inject it into agents module
            # globals so the non-JSON code path does not raise NameError.
            with patch(
                "urika.cli.agents._offer_to_run_advisor_suggestions",
                create=True,
            ):
                result = runner.invoke(
                    cli,
                    ["advisor", "test-proj", "What approach works best?"],
                    env=urika_env,
                )
        assert result.exit_code == 0, result.output
        assert "ensemble methods" in result.output

    def test_advisor_error_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(success=False, text_output="", error="SDK timeout")
        ):
            result = runner.invoke(
                cli,
                ["advisor", "test-proj", "question", "--json"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert data["output"] == "SDK timeout"


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------


class TestEvaluateCommand:
    def test_evaluate_success_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _project_dir, exp_id = _create_project_with_experiment(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(text_output="Evaluation: R2=0.85, no overfitting")
        ):
            result = runner.invoke(
                cli,
                [
                    "evaluate",
                    "test-proj",
                    exp_id,
                    "--instructions",
                    "check for overfitting",
                    "--json",
                ],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert "R2=0.85" in data["output"]

    def test_evaluate_success_plain(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _project_dir, exp_id = _create_project_with_experiment(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(text_output="No overfitting detected")
        ):
            result = runner.invoke(
                cli,
                ["evaluate", "test-proj", exp_id],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        assert "overfitting" in result.output

    def test_evaluate_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            ["evaluate", "no-such-proj", "exp-001"],
            env=urika_env,
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_evaluate_no_experiments(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        with _agent_mocks():
            result = runner.invoke(
                cli,
                ["evaluate", "test-proj"],
                env=urika_env,
            )
        assert result.exit_code != 0
        assert "No experiments" in result.output

    def test_evaluate_defaults_to_latest_experiment(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """When no experiment_id is given, evaluate picks the most recent."""
        _project_dir, exp_id = _create_project_with_experiment(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(text_output="Evaluated latest")
        ):
            result = runner.invoke(
                cli,
                ["evaluate", "test-proj", "--json"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert data["output"] == "Evaluated latest"

    def test_evaluate_error_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _project_dir, exp_id = _create_project_with_experiment(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(success=False, text_output="", error="Agent crashed")
        ):
            result = runner.invoke(
                cli,
                ["evaluate", "test-proj", exp_id, "--json"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert data["output"] == "Agent crashed"


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


class TestPlanCommand:
    def test_plan_success_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _project_dir, exp_id = _create_project_with_experiment(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(text_output="Plan: try gradient boosting with depth=5")
        ):
            result = runner.invoke(
                cli,
                [
                    "plan",
                    "test-proj",
                    exp_id,
                    "--instructions",
                    "consider Bayesian approaches",
                    "--json",
                ],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert "gradient boosting" in data["output"]

    def test_plan_success_plain(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _project_dir, exp_id = _create_project_with_experiment(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(text_output="Next method: ridge regression")
        ):
            result = runner.invoke(
                cli,
                ["plan", "test-proj", exp_id],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        assert "ridge regression" in result.output

    def test_plan_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            ["plan", "no-such-proj", "exp-001"],
            env=urika_env,
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_plan_no_experiments(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        with _agent_mocks():
            result = runner.invoke(
                cli,
                ["plan", "test-proj"],
                env=urika_env,
            )
        assert result.exit_code != 0
        assert "No experiments" in result.output

    def test_plan_defaults_to_latest_experiment(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _project_dir, exp_id = _create_project_with_experiment(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(text_output="Planned for latest experiment")
        ):
            result = runner.invoke(
                cli,
                ["plan", "test-proj", "--json"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert data["output"] == "Planned for latest experiment"

    def test_plan_error_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _project_dir, exp_id = _create_project_with_experiment(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(success=False, text_output="", error="Planning failed")
        ):
            result = runner.invoke(
                cli,
                ["plan", "test-proj", exp_id, "--json"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert data["output"] == "Planning failed"


# ---------------------------------------------------------------------------
# Present
# ---------------------------------------------------------------------------


class TestPresentCommand:
    def test_present_success_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _project_dir, _exp_id = _create_project_with_experiment(runner, urika_env)
        with (
            patch("urika.agents.runner.get_runner") as mock_get_runner,
            patch(
                "urika.orchestrator.loop._generate_presentation",
                new_callable=AsyncMock,
            ) as mock_pres,
        ):
            mock_get_runner.return_value = MagicMock()
            mock_pres.return_value = {
                "tokens_in": 50,
                "tokens_out": 150,
                "cost_usd": 0.005,
                "agent_calls": 1,
            }
            result = runner.invoke(
                cli, ["present", "test-proj", "--json"], env=urika_env
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert "path" in data

    def test_present_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["present", "no-such-proj", "--json"], env=urika_env
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_present_no_experiments(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli, ["present", "test-proj", "--json"], env=urika_env
        )
        assert result.exit_code != 0
        assert "No experiments" in result.output

    def test_present_calls_generate_presentation(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """Verify that _generate_presentation is called with correct args."""
        project_dir, exp_id = _create_project_with_experiment(runner, urika_env)
        with (
            patch("urika.agents.runner.get_runner") as mock_get_runner,
            patch(
                "urika.orchestrator.loop._generate_presentation",
                new_callable=AsyncMock,
            ) as mock_pres,
        ):
            mock_get_runner.return_value = MagicMock()
            mock_pres.return_value = {
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0,
                "agent_calls": 0,
            }
            result = runner.invoke(
                cli, ["present", "test-proj", "--json"], env=urika_env
            )
        assert result.exit_code == 0, result.output
        mock_pres.assert_called_once()
        call_args = mock_pres.call_args
        # First positional arg is project_path, second is experiment_id
        assert call_args.args[0] == project_dir
        assert call_args.args[1] == exp_id

    def test_present_json_output_contains_path(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """JSON output includes the presentation file path."""
        project_dir, exp_id = _create_project_with_experiment(runner, urika_env)
        with (
            patch("urika.agents.runner.get_runner") as mock_get_runner,
            patch(
                "urika.orchestrator.loop._generate_presentation",
                new_callable=AsyncMock,
            ) as mock_pres,
        ):
            mock_get_runner.return_value = MagicMock()
            mock_pres.return_value = {
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0,
                "agent_calls": 0,
            }
            result = runner.invoke(
                cli, ["present", "test-proj", "--json"], env=urika_env
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert exp_id in data["path"]
        assert "presentation" in data["path"]


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------


class TestFinalizeCommand:
    def test_finalize_success_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project_with_experiment(runner, urika_env)
        with (
            patch("urika.agents.runner.get_runner") as mock_get_runner,
            patch(
                "urika.orchestrator.finalize.finalize_project",
                new_callable=AsyncMock,
            ) as mock_fin,
            patch("urika.agents.config.load_runtime_config") as mock_rc,
        ):
            mock_get_runner.return_value = MagicMock()
            mock_rc.return_value = MagicMock(privacy_mode="open")
            mock_fin.return_value = {
                "success": True,
                "tokens_in": 500,
                "tokens_out": 1000,
                "cost_usd": 0.05,
                "agent_calls": 3,
            }
            result = runner.invoke(
                cli, ["finalize", "test-proj", "--json"], env=urika_env
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["tokens_in"] == 500

    def test_finalize_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["finalize", "no-such-proj", "--json"], env=urika_env
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_finalize_failure_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project_with_experiment(runner, urika_env)
        with (
            patch("urika.agents.runner.get_runner") as mock_get_runner,
            patch(
                "urika.orchestrator.finalize.finalize_project",
                new_callable=AsyncMock,
            ) as mock_fin,
            patch("urika.agents.config.load_runtime_config") as mock_rc,
        ):
            mock_get_runner.return_value = MagicMock()
            mock_rc.return_value = MagicMock(privacy_mode="open")
            mock_fin.return_value = {
                "success": False,
                "error": "No completed experiments",
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0,
                "agent_calls": 0,
            }
            result = runner.invoke(
                cli, ["finalize", "test-proj", "--json"], env=urika_env
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is False
        assert "No completed experiments" in data["error"]

    def test_finalize_calls_finalize_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """Verify that finalize_project is called with the project path."""
        project_dir, _exp_id = _create_project_with_experiment(runner, urika_env)
        with (
            patch("urika.agents.runner.get_runner") as mock_get_runner,
            patch(
                "urika.orchestrator.finalize.finalize_project",
                new_callable=AsyncMock,
            ) as mock_fin,
            patch("urika.agents.config.load_runtime_config") as mock_rc,
        ):
            mock_get_runner.return_value = MagicMock()
            mock_rc.return_value = MagicMock(privacy_mode="open")
            mock_fin.return_value = {
                "success": True,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0,
                "agent_calls": 0,
            }
            result = runner.invoke(
                cli, ["finalize", "test-proj", "--json"], env=urika_env
            )
        assert result.exit_code == 0, result.output
        mock_fin.assert_called_once()
        assert mock_fin.call_args.args[0] == project_dir

    def test_finalize_with_instructions_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project_with_experiment(runner, urika_env)
        with (
            patch("urika.agents.runner.get_runner") as mock_get_runner,
            patch(
                "urika.orchestrator.finalize.finalize_project",
                new_callable=AsyncMock,
            ) as mock_fin,
            patch("urika.agents.config.load_runtime_config") as mock_rc,
        ):
            mock_get_runner.return_value = MagicMock()
            mock_rc.return_value = MagicMock(privacy_mode="open")
            mock_fin.return_value = {
                "success": True,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0,
                "agent_calls": 0,
            }
            result = runner.invoke(
                cli,
                [
                    "finalize",
                    "test-proj",
                    "--instructions",
                    "focus on ensemble methods",
                    "--json",
                ],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        # Verify instructions were passed through
        call_kwargs = mock_fin.call_args.kwargs
        assert call_kwargs.get("instructions") == "focus on ensemble methods"

    def test_finalize_with_draft_flag_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project_with_experiment(runner, urika_env)
        with (
            patch("urika.agents.runner.get_runner") as mock_get_runner,
            patch(
                "urika.orchestrator.finalize.finalize_project",
                new_callable=AsyncMock,
            ) as mock_fin,
            patch("urika.agents.config.load_runtime_config") as mock_rc,
        ):
            mock_get_runner.return_value = MagicMock()
            mock_rc.return_value = MagicMock(privacy_mode="open")
            mock_fin.return_value = {
                "success": True,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0,
                "agent_calls": 0,
            }
            result = runner.invoke(
                cli,
                ["finalize", "test-proj", "--draft", "--json"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        call_kwargs = mock_fin.call_args.kwargs
        assert call_kwargs.get("draft") is True


# ---------------------------------------------------------------------------
# Build-tool
# ---------------------------------------------------------------------------


class TestBuildToolCommand:
    def test_build_tool_success_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(text_output="Created tool: eeg_epoch_extractor")
        ):
            result = runner.invoke(
                cli,
                [
                    "build-tool",
                    "test-proj",
                    "create an EEG epoch extractor using MNE",
                    "--json",
                ],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert "eeg_epoch_extractor" in data["output"]

    def test_build_tool_success_plain(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(text_output="Tool built: correlation_heatmap")
        ):
            result = runner.invoke(
                cli,
                ["build-tool", "test-proj", "create a correlation heatmap tool"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        assert "correlation_heatmap" in result.output

    def test_build_tool_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            ["build-tool", "no-such-proj", "build something"],
            env=urika_env,
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_build_tool_error_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(
                success=False, text_output="", error="Missing dependency"
            )
        ):
            result = runner.invoke(
                cli,
                ["build-tool", "test-proj", "build something complex", "--json"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert data["output"] == "Missing dependency"


# ---------------------------------------------------------------------------
# Criteria
# ---------------------------------------------------------------------------


class TestCriteriaCommand:
    def test_criteria_shows_builder_defaults(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """Project builder seeds initial criteria; verify they display."""
        _create_project(runner, urika_env)
        result = runner.invoke(cli, ["criteria", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        # Project builder sets v1 criteria
        assert "v1" in result.output
        assert "project_builder" in result.output

    def test_criteria_no_criteria_after_removal(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """If criteria.json is removed, shows 'No criteria set'."""
        project_dir = _create_project(runner, urika_env)
        criteria_file = project_dir / "criteria.json"
        if criteria_file.exists():
            criteria_file.unlink()

        result = runner.invoke(cli, ["criteria", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "No criteria set" in result.output

    def test_criteria_with_custom_criteria(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        project_dir = _create_project(runner, urika_env)

        from urika.core.criteria import append_criteria

        append_criteria(
            project_dir,
            {
                "type": "predictive",
                "threshold": {
                    "primary": {
                        "metric": "accuracy",
                        "target": 0.8,
                        "direction": "higher",
                    }
                },
            },
            set_by="test",
            turn=0,
            rationale="Custom criteria",
        )

        result = runner.invoke(cli, ["criteria", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "predictive" in result.output
        assert "accuracy" in result.output
        assert "0.8" in result.output
        assert "higher" in result.output

    def test_criteria_json_no_criteria(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        project_dir = _create_project(runner, urika_env)
        # Remove the builder-seeded criteria
        criteria_file = project_dir / "criteria.json"
        if criteria_file.exists():
            criteria_file.unlink()

        result = runner.invoke(
            cli, ["criteria", "test-proj", "--json"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["criteria"] is None

    def test_criteria_json_with_criteria(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        project_dir = _create_project(runner, urika_env)

        from urika.core.criteria import append_criteria

        append_criteria(
            project_dir,
            {
                "type": "predictive",
                "threshold": {
                    "primary": {
                        "metric": "r2",
                        "target": 0.7,
                        "direction": "higher",
                    }
                },
            },
            set_by="evaluator",
            turn=3,
            rationale="Updated after baseline",
        )

        result = runner.invoke(
            cli, ["criteria", "test-proj", "--json"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        criteria = data["criteria"]
        assert criteria is not None
        assert criteria["set_by"] == "evaluator"
        assert criteria["type"] == "predictive"
        assert criteria["threshold"]["primary"]["metric"] == "r2"
        assert criteria["threshold"]["primary"]["target"] == 0.7

    def test_criteria_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["criteria", "no-such-proj"], env=urika_env)
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_criteria_multiple_versions_shows_latest(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """When multiple criteria versions exist, the command shows the latest."""
        project_dir = _create_project(runner, urika_env)
        # Remove builder-seeded criteria for a clean slate
        criteria_file = project_dir / "criteria.json"
        if criteria_file.exists():
            criteria_file.unlink()

        from urika.core.criteria import append_criteria

        append_criteria(
            project_dir,
            {
                "type": "exploratory",
                "threshold": {
                    "primary": {
                        "metric": "r2",
                        "target": 0.5,
                        "direction": "higher",
                    }
                },
            },
            set_by="planner",
            turn=0,
            rationale="Initial",
        )
        append_criteria(
            project_dir,
            {
                "type": "predictive",
                "threshold": {
                    "primary": {
                        "metric": "accuracy",
                        "target": 0.9,
                        "direction": "higher",
                    }
                },
            },
            set_by="evaluator",
            turn=5,
            rationale="Refined after experiment 2",
        )

        result = runner.invoke(
            cli, ["criteria", "test-proj", "--json"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        criteria = data["criteria"]
        assert criteria["version"] == 2
        assert criteria["set_by"] == "evaluator"
        assert criteria["type"] == "predictive"
        assert criteria["threshold"]["primary"]["metric"] == "accuracy"
        assert criteria["threshold"]["primary"]["target"] == 0.9

    def test_criteria_json_includes_version_and_set_by(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        """JSON output includes version and set_by in the criteria object."""
        _create_project(runner, urika_env)
        # Builder seeds v1; verify it appears in JSON
        result = runner.invoke(
            cli, ["criteria", "test-proj", "--json"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        criteria = data["criteria"]
        assert criteria is not None
        assert "version" in criteria
        assert "set_by" in criteria
        assert criteria["version"] >= 1


# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------


class TestSummarizeCommand:
    def test_summarize_help(self, runner: CliRunner) -> None:
        """Verify the summarize command is registered and shows help."""
        result = runner.invoke(cli, ["summarize", "--help"])
        assert result.exit_code == 0
        assert "Summarize" in result.output

    def test_summarize_runs_agent(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(
                text_output="Project has 3 experiments, best R2=0.85"
            )
        ):
            result = runner.invoke(
                cli,
                ["summarize", "test-proj", "--json"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert "R2=0.85" in data["output"]

    def test_summarize_success_plain(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(text_output="Summary: 2 experiments completed")
        ):
            result = runner.invoke(
                cli,
                ["summarize", "test-proj"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        assert "2 experiments completed" in result.output

    def test_summarize_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            ["summarize", "no-such-proj"],
            env=urika_env,
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_summarize_error_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        with _agent_mocks(
            _mock_agent_result(success=False, text_output="", error="Agent timeout")
        ):
            result = runner.invoke(
                cli,
                ["summarize", "test-proj", "--json"],
                env=urika_env,
            )
        assert result.exit_code == 0, result.output
        data = _extract_json(result.output)
        assert data["output"] == "Agent timeout"
