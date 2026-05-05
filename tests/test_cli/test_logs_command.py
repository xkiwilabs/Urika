"""Tests for ``urika logs`` — v0.4.2 C6 regression suite.

Pre-v0.4.2 the docstring said "Show experiment run log" but the body
only printed progress.json runs/metrics; ``run.log`` was never opened.
The dashboard's log view always tailed the real log; the CLI now
matches.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from urika.cli import cli
from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace
from urika.core.experiment import create_experiment
from urika.core.registry import ProjectRegistry


def _make_project(tmp_path: Path, monkeypatch) -> tuple[Path, str]:
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    project_dir = tmp_path / "myproj"
    config = ProjectConfig(
        name="myproj",
        question="Does X predict Y?",
        mode="exploratory",
        data_paths=[],
    )
    create_project_workspace(project_dir, config)
    ProjectRegistry().register("myproj", project_dir)
    exp = create_experiment(project_dir, name="baseline", hypothesis="h")
    return project_dir, exp.experiment_id


class TestLogsActuallyTailsRunLog:
    def test_tails_run_log_when_present(self, tmp_path: Path, monkeypatch) -> None:
        project_dir, exp_id = _make_project(tmp_path, monkeypatch)
        log_path = project_dir / "experiments" / exp_id / "run.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "line1\nline2\nline3\nline4\nline5\n", encoding="utf-8"
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["logs", "myproj", "--tail", "3"])

        assert result.exit_code == 0, result.output
        # Must show actual log lines, not progress.json metrics.
        assert "line5" in result.output
        assert "line4" in result.output
        assert "line3" in result.output
        # Pre-fix output included "Hypothesis:" / "Observation:" / run-ids.
        # Default mode no longer renders those.
        assert "Hypothesis:" not in result.output

    def test_missing_log_prints_help_not_exception(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _make_project(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["logs", "myproj"])
        # No log yet — exits zero with a friendly note on stderr.
        assert result.exit_code == 0
        # CliRunner combines stdout+stderr by default.
        assert "No run.log" in result.output

    def test_summary_flag_preserves_legacy_output(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        project_dir, exp_id = _make_project(tmp_path, monkeypatch)
        # Seed a progress.json with one run.
        from urika.core.models import RunRecord
        from urika.core.progress import append_run

        append_run(
            project_dir,
            exp_id,
            RunRecord(
                run_id="run-001",
                method="ols",
                params={},
                metrics={"r2": 0.9},
                hypothesis="linear is enough",
                observation="r2 above threshold",
                next_step="ship",
            ),
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["logs", "myproj", "--summary"])
        assert result.exit_code == 0, result.output
        assert "run-001" in result.output
        assert "ols" in result.output
        assert "Hypothesis:" in result.output

    def test_json_includes_log_lines(self, tmp_path: Path, monkeypatch) -> None:
        project_dir, exp_id = _make_project(tmp_path, monkeypatch)
        log_path = project_dir / "experiments" / exp_id / "run.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["logs", "myproj", "--json", "--tail", "2"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["log_lines"] == ["beta", "gamma"]
        assert data["log_path"].endswith("run.log")

    def test_json_empty_log_lines_when_log_missing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        project_dir, exp_id = _make_project(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["logs", "myproj", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["log_lines"] == []
