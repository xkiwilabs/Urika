"""Tests for the experiment-comparison view (v0.4 Track 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def compare_client(tmp_path: Path):
    """Build a dashboard client with a project containing two experiments."""
    project_root = tmp_path / "projects"
    project_root.mkdir()
    proj = project_root / "alpha"
    (proj / "experiments" / "exp-001").mkdir(parents=True)
    (proj / "experiments" / "exp-002").mkdir(parents=True)
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "?"\nmode = "exploratory"\n',
        encoding="utf-8",
    )

    # Two experiments with metrics in their progress.json.
    (proj / "experiments" / "exp-001" / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-001",
                "name": "Linear baseline",
                "hypothesis": "linear models suffice",
            }
        ),
        encoding="utf-8",
    )
    (proj / "experiments" / "exp-001" / "progress.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "runs": [
                    {
                        "method": "linear_regression",
                        "metrics": {"r2": 0.50, "rmse": 0.80},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (proj / "experiments" / "exp-002" / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-002",
                "name": "Random forest",
                "hypothesis": "trees beat linear",
            }
        ),
        encoding="utf-8",
    )
    (proj / "experiments" / "exp-002" / "progress.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "runs": [
                    {
                        "method": "random_forest",
                        "metrics": {"r2": 0.78, "rmse": 0.40},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    # Register the project so load_project_summary finds it.
    home = tmp_path / "home"
    home.mkdir()
    import os

    os.environ["URIKA_HOME"] = str(home)
    (home / "projects.json").write_text(
        json.dumps({"alpha": str(proj)}), encoding="utf-8"
    )

    app = create_app(project_root=project_root)
    client = TestClient(app)
    yield client, proj
    os.environ.pop("URIKA_HOME", None)


def test_compare_renders_metrics_for_selected_experiments(compare_client):
    client, _proj = compare_client
    r = client.get("/projects/alpha/compare?experiments=exp-001,exp-002")
    assert r.status_code == 200
    body = r.text
    assert "exp-001" in body
    assert "exp-002" in body
    assert "r2" in body
    assert "rmse" in body
    assert "0.5" in body or "0.50" in body
    assert "0.78" in body


def test_compare_falls_back_to_all_when_query_empty(compare_client):
    client, _proj = compare_client
    r = client.get("/projects/alpha/compare")
    assert r.status_code == 200
    body = r.text
    assert "exp-001" in body
    assert "exp-002" in body


def test_compare_404_unknown_project(compare_client):
    client, _proj = compare_client
    r = client.get("/projects/unknown/compare")
    assert r.status_code == 404


def test_compare_silently_drops_unknown_experiment_ids(compare_client):
    """An ?experiments= entry that doesn't exist is filtered out
    rather than 4xx-ing — falls back to no-IDs → all-experiments."""
    client, _proj = compare_client
    r = client.get("/projects/alpha/compare?experiments=exp-999")
    assert r.status_code == 200
    # Falls back to all when nothing was matched.
    assert "exp-001" in r.text
    assert "exp-002" in r.text
