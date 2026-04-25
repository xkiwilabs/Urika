from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from urika.dashboard_v2.app import create_app


def _make_project_with_experiments(root: Path, name: str, n_exps: int):
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\n'
        f'name = "{name}"\n'
        f'question = "q for {name}"\n'
        f'mode = "exploratory"\n'
        f'description = ""\n'
        f'\n'
        f'[preferences]\n'
        f'audience = "expert"\n'
    )
    for i in range(n_exps):
        exp_id = f"exp-{i+1:03d}"
        exp_dir = proj / "experiments" / exp_id
        exp_dir.mkdir(parents=True)
        (exp_dir / "experiment.json").write_text(json.dumps({
            "experiment_id": exp_id,
            "name": f"experiment {i+1}",
            "hypothesis": f"hypothesis {i+1}",
            "status": "completed",
            "created_at": f"2026-04-{i+1:02d}T00:00:00Z",
        }))
    return proj


@pytest.fixture
def client_with_experiments(tmp_path: Path, monkeypatch) -> TestClient:
    _make_project_with_experiments(tmp_path, "alpha", 7)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_project_home_returns_200_and_shows_name_and_question(client_with_projects):
    r = client_with_projects.get("/projects/alpha")
    assert r.status_code == 200
    assert "alpha" in r.text
    assert "q for alpha" in r.text


def test_project_home_404_for_unknown(client_with_projects):
    r = client_with_projects.get("/projects/nonexistent")
    assert r.status_code == 404


def test_project_home_lists_recent_experiments(client_with_experiments):
    r = client_with_experiments.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    # 7 experiments created; recent 5 should be exp-003 through exp-007.
    # Most recent first, so exp-007 listed first.
    assert "exp-007" in body
    assert "exp-006" in body
    assert "exp-005" in body
    assert "exp-004" in body
    assert "exp-003" in body
    # exp-001 and exp-002 should NOT appear (they're outside the top-5)
    assert "exp-001" not in body
    assert "exp-002" not in body


def test_project_home_sidebar_shows_project_links(client_with_projects):
    r = client_with_projects.get("/projects/alpha")
    body = r.text
    # Sidebar has project-scoped Home/Experiments/Methods/Knowledge/Run/Settings links
    assert "/projects/alpha/experiments" in body
    assert "/projects/alpha/methods" in body
    assert "/projects/alpha/knowledge" in body
    assert "/projects/alpha/run" in body
    assert "/projects/alpha/settings" in body


def test_experiments_page_returns_200_and_shows_experiments(client_with_experiments):
    r = client_with_experiments.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    # All 7 experiments visible (this page shows the full list, not just top 5)
    for i in range(1, 8):
        assert f"exp-{i:03d}" in body


def test_experiments_page_404_for_unknown(client_with_projects):
    r = client_with_projects.get("/projects/nonexistent/experiments")
    assert r.status_code == 404


def test_experiments_page_empty_state(client_with_projects):
    """alpha in client_with_projects has no experiment dirs."""
    r = client_with_projects.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    assert "No experiments yet" in body or "no experiments" in body.lower()


def _make_project_with_runs(root: Path, name: str, exp_id: str, n_runs: int) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q for {name}"\n'
        f'mode = "exploratory"\ndescription = ""\n\n'
        f'[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / exp_id
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(json.dumps({
        "experiment_id": exp_id,
        "name": "baseline",
        "hypothesis": "linear models will fit",
        "status": "completed",
        "created_at": "2026-04-25T00:00:00Z",
    }))
    runs = [
        {
            "run_id": f"run-{i+1:03d}",
            "method": "ols",
            "params": {},
            "metrics": {"r2": 0.5 + i * 0.01},
            "observation": f"observation for run {i+1}",
            "timestamp": f"2026-04-25T0{i}:00:00Z",
        }
        for i in range(n_runs)
    ]
    (exp_dir / "progress.json").write_text(json.dumps({
        "experiment_id": exp_id,
        "status": "completed",
        "runs": runs,
    }))
    return proj


@pytest.fixture
def client_with_runs(tmp_path: Path, monkeypatch) -> TestClient:
    _make_project_with_runs(tmp_path, "alpha", "exp-001", 3)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_experiment_detail_returns_200_and_shows_hypothesis(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    assert r.status_code == 200
    body = r.text
    assert "linear models will fit" in body
    assert "exp-001" in body


def test_experiment_detail_lists_runs(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "ols" in body  # method name
    assert "run-001" in body or "observation for run 1" in body


def test_experiment_detail_404_for_unknown_experiment(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-999")
    assert r.status_code == 404


def test_experiment_detail_404_for_unknown_project(client_with_runs):
    r = client_with_runs.get("/projects/nonexistent/experiments/exp-001")
    assert r.status_code == 404
