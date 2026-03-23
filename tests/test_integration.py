"""Integration test: full project lifecycle."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from urika.cli import cli
from urika.core.experiment import create_experiment, list_experiments
from urika.core.labbook import (
    generate_experiment_summary,
    generate_key_findings,
    generate_results_summary,
    update_experiment_notes,
)
from urika.core.models import RunRecord
from urika.core.progress import append_run, get_best_run, load_progress
from urika.core.workspace import load_project_config


def test_full_lifecycle(tmp_path: Path) -> None:
    """End-to-end: create project -> experiments -> runs -> labbook."""
    urika_home = tmp_path / ".urika"
    urika_home.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    env = {
        "URIKA_HOME": str(urika_home),
        "URIKA_PROJECTS_DIR": str(projects_dir),
    }
    runner = CliRunner()

    # 1. Create project via CLI
    result = runner.invoke(
        cli,
        [
            "new",
            "sleep-study",
            "-q",
            "What predicts sleep quality?",
            "-m",
            "exploratory",
        ],
        env=env,
    )
    assert result.exit_code == 0

    project_dir = projects_dir / "sleep-study"
    config = load_project_config(project_dir)
    assert config.name == "sleep-study"

    # 2. Create experiments
    exp1 = create_experiment(
        project_dir,
        name="Baseline linear models",
        hypothesis="Linear models establish floor",
    )
    exp2 = create_experiment(
        project_dir,
        name="Tree-based methods",
        hypothesis="Nonlinear models improve over baseline",
        builds_on=[exp1.experiment_id],
    )

    assert len(list_experiments(project_dir)) == 2

    # 3. Record runs in experiment 1
    runs_exp1 = [
        RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={"fit_intercept": True},
            metrics={"r2": 0.72, "rmse": 0.15},
            hypothesis="Baseline linear",
            observation="Nonlinearity in residuals",
            next_step="Try regularization",
        ),
        RunRecord(
            run_id="run-002",
            method="ridge_regression",
            params={"alpha": 1.0},
            metrics={"r2": 0.73, "rmse": 0.14},
            hypothesis="Regularization helps",
            observation="Marginal improvement, issue is model form",
            next_step="Try tree-based methods",
        ),
    ]
    for run in runs_exp1:
        append_run(project_dir, exp1.experiment_id, run)

    # 4. Record runs in experiment 2
    runs_exp2 = [
        RunRecord(
            run_id="run-001",
            method="random_forest",
            params={"n_estimators": 100},
            metrics={"r2": 0.82, "rmse": 0.09},
            hypothesis="Random forest captures nonlinearity",
            observation="Big improvement over linear",
            next_step="Try XGBoost",
        ),
        RunRecord(
            run_id="run-002",
            method="xgboost",
            params={"max_depth": 5, "learning_rate": 0.1},
            metrics={"r2": 0.85, "rmse": 0.07},
            hypothesis="XGBoost further improves",
            observation="Best model so far, exercise and caffeine top features",
        ),
    ]
    for run in runs_exp2:
        append_run(project_dir, exp2.experiment_id, run)

    # 5. Verify progress tracking
    progress1 = load_progress(project_dir, exp1.experiment_id)
    assert len(progress1["runs"]) == 2

    best1 = get_best_run(
        project_dir, exp1.experiment_id, metric="r2", direction="higher"
    )
    assert best1 is not None
    assert best1["method"] == "ridge_regression"

    best2 = get_best_run(
        project_dir, exp2.experiment_id, metric="r2", direction="higher"
    )
    assert best2 is not None
    assert best2["method"] == "xgboost"

    # 6. Generate labbook
    update_experiment_notes(project_dir, exp1.experiment_id)
    update_experiment_notes(project_dir, exp2.experiment_id)
    generate_experiment_summary(project_dir, exp1.experiment_id)
    generate_experiment_summary(project_dir, exp2.experiment_id)
    generate_results_summary(project_dir)
    generate_key_findings(project_dir)

    # 7. Verify labbook content
    notes1 = (
        project_dir / "experiments" / exp1.experiment_id / "labbook" / "notes.md"
    ).read_text()
    assert "linear_regression" in notes1
    assert "ridge_regression" in notes1

    summary2 = (
        project_dir / "experiments" / exp2.experiment_id / "labbook" / "summary.md"
    ).read_text()
    assert "xgboost" in summary2 or "0.85" in summary2

    results = (project_dir / "projectbook" / "results-summary.md").read_text()
    assert "Baseline" in results
    assert "Tree-based" in results

    findings = (project_dir / "projectbook" / "key-findings.md").read_text()
    assert "Key Findings" in findings

    # 8. Verify CLI status
    result = runner.invoke(cli, ["status", "sleep-study"], env=env)
    assert result.exit_code == 0
    assert "sleep-study" in result.output
    assert "2" in result.output  # 2 experiments

    # 9. Verify list
    result = runner.invoke(cli, ["list"], env=env)
    assert "sleep-study" in result.output


def test_cli_smoke_test(tmp_path: Path) -> None:
    """Smoke test: exercise every CLI command in a single pipeline."""
    urika_home = tmp_path / ".urika"
    urika_home.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    env = {
        "URIKA_HOME": str(urika_home),
        "URIKA_PROJECTS_DIR": str(projects_dir),
    }
    runner = CliRunner()

    # 1. urika new
    result = runner.invoke(
        cli,
        [
            "new",
            "smoke-test",
            "-q",
            "Does exercise predict sleep?",
            "-m",
            "exploratory",
        ],
        env=env,
    )
    assert result.exit_code == 0, result.output
    assert "Created project" in result.output
    project_dir = projects_dir / "smoke-test"

    # 2. urika experiment create
    result = runner.invoke(
        cli,
        [
            "experiment",
            "create",
            "smoke-test",
            "baseline",
            "--hypothesis",
            "Linear model is enough",
        ],
        env=env,
    )
    assert result.exit_code == 0, result.output
    assert "exp-001" in result.output

    # 3. urika experiment list
    result = runner.invoke(cli, ["experiment", "list", "smoke-test"], env=env)
    assert result.exit_code == 0, result.output
    assert "baseline" in result.output

    # Get experiment ID
    exp_dirs = sorted((project_dir / "experiments").iterdir())
    exp_id = exp_dirs[0].name

    # 4. urika run (mocked orchestrator)
    with (
        patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner"),
        patch("urika.orchestrator.run_experiment", new_callable=AsyncMock) as mock_run,
    ):
        mock_run.return_value = {"status": "completed", "turns": 5, "error": None}
        result = runner.invoke(cli, ["run", "smoke-test", "--max-turns", "10"], env=env)
    assert result.exit_code == 0, result.output
    assert "completed" in result.output
    assert "5 turns" in result.output

    # 5. Seed run data (since orchestrator was mocked)
    runs = [
        RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={"alpha": 0.01},
            metrics={"r2": 0.72, "rmse": 0.15},
            hypothesis="Baseline linear",
            observation="Residuals show nonlinearity",
            next_step="Try random forest",
        ),
        RunRecord(
            run_id="run-002",
            method="random_forest",
            params={"n_estimators": 100},
            metrics={"r2": 0.85, "rmse": 0.08},
            hypothesis="Nonlinear may help",
            observation="Big improvement",
        ),
    ]
    for run in runs:
        append_run(project_dir, exp_id, run)

    # 6. urika results (experiment-level)
    result = runner.invoke(
        cli, ["results", "smoke-test", "--experiment", exp_id], env=env
    )
    assert result.exit_code == 0, result.output
    assert "linear_regression" in result.output
    assert "random_forest" in result.output

    # 7. urika report (project-level) — select "Project level" from the prompt
    result = runner.invoke(
        cli, ["report", "smoke-test"], env=env, input="3\n"
    )
    assert result.exit_code == 0, result.output
    assert "results-summary.md" in result.output
    assert "key-findings.md" in result.output
    assert (project_dir / "projectbook" / "results-summary.md").exists()
    assert (project_dir / "projectbook" / "key-findings.md").exists()

    # 8. urika report (experiment-level)
    result = runner.invoke(
        cli, ["report", "smoke-test", "--experiment", exp_id], env=env
    )
    assert result.exit_code == 0, result.output
    assert "summary.md" in result.output
    assert "notes.md" in result.output

    # Verify report content
    summary = (
        project_dir / "experiments" / exp_id / "labbook" / "summary.md"
    ).read_text()
    assert "random_forest" in summary

    # 9. urika run --continue (mocked)
    from urika.core.session import pause_session, start_session

    start_session(project_dir, exp_id, max_turns=10)
    pause_session(project_dir, exp_id)

    with (
        patch("urika.agents.adapters.claude_sdk.ClaudeSDKRunner"),
        patch("urika.orchestrator.run_experiment", new_callable=AsyncMock) as mock_run,
    ):
        mock_run.return_value = {"status": "completed", "turns": 7, "error": None}
        result = runner.invoke(cli, ["run", "smoke-test", "--continue"], env=env)
    assert result.exit_code == 0, result.output
    assert "Resuming" in result.output

    # 10. urika knowledge ingest
    knowledge_dir = project_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    notes_file = knowledge_dir / "sleep-research.txt"
    notes_file.write_text("Exercise improves sleep quality via melatonin regulation.")

    result = runner.invoke(
        cli, ["knowledge", "ingest", "smoke-test", str(notes_file)], env=env
    )
    assert result.exit_code == 0, result.output
    assert "k-001" in result.output

    # 11. urika knowledge search
    result = runner.invoke(
        cli, ["knowledge", "search", "smoke-test", "melatonin"], env=env
    )
    assert result.exit_code == 0, result.output
    assert "sleep-research.txt" in result.output

    # 12. urika knowledge list
    result = runner.invoke(cli, ["knowledge", "list", "smoke-test"], env=env)
    assert result.exit_code == 0, result.output
    assert "k-001" in result.output

    # 13. urika status (final check)
    result = runner.invoke(cli, ["status", "smoke-test"], env=env)
    assert result.exit_code == 0, result.output
    assert "smoke-test" in result.output
    assert "Does exercise predict sleep?" in result.output
    assert "1" in result.output  # 1 experiment
