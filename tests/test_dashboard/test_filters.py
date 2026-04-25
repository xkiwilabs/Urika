"""Jinja humanize + tag_status filters."""
from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app
from urika.dashboard.filters import humanize, tag_status


def test_humanize_replaces_hyphens_and_titlecases():
    assert humanize("exp-001-baseline") == "Exp 001 Baseline"


def test_humanize_handles_underscores():
    assert humanize("linear_regression") == "Linear Regression"


def test_humanize_returns_empty_for_none():
    assert humanize(None) == ""
    assert humanize("") == ""


def test_humanize_keeps_already_capitalized():
    assert humanize("Already Capitalized") == "Already Capitalized"


def test_humanize_keeps_numbers():
    assert humanize("v123") == "V123"
    assert humanize("exp-123") == "Exp 123"


def test_tag_status_normalizes():
    assert tag_status("Running") == "running"
    assert tag_status("COMPLETED") == "completed"
    assert tag_status(None) == "pending"
    assert tag_status("nonsense") == "pending"


@pytest.fixture
def client_with_runs(tmp_path: Path, monkeypatch) -> TestClient:
    """Project with one completed experiment so the green pill renders."""
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q for alpha"\n'
        'mode = "exploratory"\ndescription = ""\n\n'
        '[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-001",
                "name": "baseline",
                "hypothesis": "h",
                "status": "completed",
                "created_at": "2026-04-25T00:00:00Z",
            }
        )
    )
    (exp_dir / "progress.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-001",
                "status": "completed",
                "runs": [
                    {
                        "run_id": "run-001",
                        "method": "ols",
                        "params": {},
                        "metrics": {"r2": 0.5},
                        "observation": "obs",
                        "timestamp": "2026-04-25T01:00:00Z",
                    }
                ],
            }
        )
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(
        json.dumps({"alpha": str(proj)})
    )
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_experiments_list_status_uses_tag_modifier(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    # The completed experiment should get the green modifier
    assert "tag--completed" in body
