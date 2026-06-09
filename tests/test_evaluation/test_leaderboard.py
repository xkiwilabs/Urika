"""Tests for leaderboard management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from urika.evaluation.leaderboard import load_leaderboard, update_leaderboard


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """Create a project dir with an empty leaderboard in workspace format."""
    d = tmp_path / "my_project"
    d.mkdir()
    (d / "leaderboard.json").write_text(json.dumps({"entries": []}, indent=2))
    return d


class TestLoadLeaderboard:
    """Tests for load_leaderboard."""

    def test_load_legacy_format(self, project_dir: Path) -> None:
        """Legacy format with 'entries' is converted to 'ranking'."""
        data = load_leaderboard(project_dir)
        assert "ranking" in data
        assert isinstance(data["ranking"], list)


class TestLoadLeaderboardCorrupt:
    """Task 1.3: corrupt leaderboard.json must not crash callers."""

    def test_load_leaderboard_corrupt_returns_empty_and_preserves(
        self, tmp_path: Path
    ) -> None:
        """Corrupt JSON → returns {"ranking": []}, .corrupt file preserved."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        lb_path = project_dir / "leaderboard.json"
        lb_path.write_text("{not json", encoding="utf-8")

        result = load_leaderboard(project_dir)
        assert result == {"ranking": []}, f"expected empty ranking, got {result}"
        assert not lb_path.exists(), "original corrupt file should be renamed away"
        corrupt_path = project_dir / "leaderboard.json.corrupt"
        assert corrupt_path.exists(), ".corrupt file should exist"


class TestUpdateLeaderboard:
    """Tests for update_leaderboard."""

    def test_first_entry(self, project_dir: Path) -> None:
        """First run creates a leaderboard entry at rank 1."""
        update_leaderboard(
            project_dir,
            method="linear_regression",
            metrics={"r2": 0.85, "rmse": 1.2},
            run_id="run_001",
            params={"alpha": 0.1},
            primary_metric="r2",
            direction="higher_is_better",
            experiment_id="exp_001",
        )
        data = load_leaderboard(project_dir)
        assert len(data["ranking"]) == 1
        entry = data["ranking"][0]
        assert entry["rank"] == 1
        assert entry["method"] == "linear_regression"
        assert entry["run_id"] == "run_001"
        assert entry["metrics"] == {"r2": 0.85, "rmse": 1.2}
        assert entry["params"] == {"alpha": 0.1}
        assert entry["experiment_id"] == "exp_001"

    def test_better_run_updates(self, project_dir: Path) -> None:
        """A better run for the same method replaces the existing entry."""
        update_leaderboard(
            project_dir,
            method="linear_regression",
            metrics={"r2": 0.80},
            run_id="run_001",
            params={},
            primary_metric="r2",
            direction="higher_is_better",
        )
        update_leaderboard(
            project_dir,
            method="linear_regression",
            metrics={"r2": 0.90},
            run_id="run_002",
            params={},
            primary_metric="r2",
            direction="higher_is_better",
        )
        data = load_leaderboard(project_dir)
        assert len(data["ranking"]) == 1
        assert data["ranking"][0]["run_id"] == "run_002"
        assert data["ranking"][0]["metrics"]["r2"] == 0.90

    def test_worse_run_does_not_update(self, project_dir: Path) -> None:
        """A worse run for the same method does not replace the existing entry."""
        update_leaderboard(
            project_dir,
            method="linear_regression",
            metrics={"r2": 0.90},
            run_id="run_001",
            params={},
            primary_metric="r2",
            direction="higher_is_better",
        )
        update_leaderboard(
            project_dir,
            method="linear_regression",
            metrics={"r2": 0.80},
            run_id="run_002",
            params={},
            primary_metric="r2",
            direction="higher_is_better",
        )
        data = load_leaderboard(project_dir)
        assert len(data["ranking"]) == 1
        assert data["ranking"][0]["run_id"] == "run_001"
        assert data["ranking"][0]["metrics"]["r2"] == 0.90

    def test_multiple_methods_sorted(self, project_dir: Path) -> None:
        """Multiple methods are sorted by primary metric (descending for higher_is_better)."""
        for method, r2, run_id in [
            ("svr", 0.70, "run_a"),
            ("linear_regression", 0.90, "run_b"),
            ("random_forest", 0.85, "run_c"),
        ]:
            update_leaderboard(
                project_dir,
                method=method,
                metrics={"r2": r2},
                run_id=run_id,
                params={},
                primary_metric="r2",
                direction="higher_is_better",
            )
        data = load_leaderboard(project_dir)
        assert len(data["ranking"]) == 3
        assert data["ranking"][0]["method"] == "linear_regression"
        assert data["ranking"][0]["rank"] == 1
        assert data["ranking"][1]["method"] == "random_forest"
        assert data["ranking"][1]["rank"] == 2
        assert data["ranking"][2]["method"] == "svr"
        assert data["ranking"][2]["rank"] == 3

    def test_lower_is_better(self, project_dir: Path) -> None:
        """direction=lower_is_better sorts ascending by primary metric."""
        update_leaderboard(
            project_dir,
            method="svr",
            metrics={"rmse": 2.0},
            run_id="run_a",
            params={},
            primary_metric="rmse",
            direction="lower_is_better",
        )
        update_leaderboard(
            project_dir,
            method="linear_regression",
            metrics={"rmse": 1.0},
            run_id="run_b",
            params={},
            primary_metric="rmse",
            direction="lower_is_better",
        )
        data = load_leaderboard(project_dir)
        assert data["ranking"][0]["method"] == "linear_regression"
        assert data["ranking"][0]["rank"] == 1
        assert data["ranking"][1]["method"] == "svr"
        assert data["ranking"][1]["rank"] == 2

    def test_stores_metadata(self, project_dir: Path) -> None:
        """Leaderboard stores params, experiment_id, primary_metric, direction."""
        update_leaderboard(
            project_dir,
            method="linear_regression",
            metrics={"r2": 0.85},
            run_id="run_001",
            params={"alpha": 0.1, "fit_intercept": True},
            primary_metric="r2",
            direction="higher_is_better",
            experiment_id="exp_042",
        )
        data = load_leaderboard(project_dir)
        assert data["primary_metric"] == "r2"
        assert data["direction"] == "higher_is_better"
        entry = data["ranking"][0]
        assert entry["params"] == {"alpha": 0.1, "fit_intercept": True}
        assert entry["experiment_id"] == "exp_042"
