"""Tests for GET /api/projects/<name>/experiments/<exp_id>/artifacts.

A tiny read-only endpoint that reports whether the report,
presentation, and run.log files exist on disk for a given
experiment. Used by the live log page to decide which buttons
to reveal once a run completes, but useful from any page that
needs cheap artifact-existence probes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard_v2.app import create_app


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
    (exp_dir / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "name": "baseline",
                "hypothesis": "linear models will fit",
                "status": "completed",
                "created_at": "2026-04-25T00:00:00Z",
            }
        )
    )
    runs = [
        {
            "run_id": f"run-{i + 1:03d}",
            "method": "ols",
            "params": {},
            "metrics": {"r2": 0.5 + i * 0.01},
            "observation": f"observation for run {i + 1}",
            "timestamp": f"2026-04-25T0{i}:00:00Z",
        }
        for i in range(n_runs)
    ]
    (exp_dir / "progress.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "status": "completed",
                "runs": runs,
            }
        )
    )
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


def test_artifacts_endpoint_reports_presence(client_with_runs):
    # client_with_runs has exp-001 with progress.json but no report/presentation
    r = client_with_runs.get("/api/projects/alpha/experiments/exp-001/artifacts")
    assert r.status_code == 200
    data = r.json()
    assert data["has_report"] is False
    assert data["has_presentation"] is False


def test_artifacts_endpoint_404_unknown_project(client_with_runs):
    r = client_with_runs.get("/api/projects/nonexistent/experiments/exp-001/artifacts")
    assert r.status_code == 404


def test_artifacts_endpoint_detects_written_files(tmp_path: Path, monkeypatch):
    """When report.md and presentation.html exist, flags flip to True."""
    proj = _make_project_with_runs(tmp_path, "alpha", "exp-001", 1)
    exp_dir = proj / "experiments" / "exp-001"
    (exp_dir / "report.md").write_text("# Report\n")
    (exp_dir / "presentation.html").write_text("<html></html>")
    (exp_dir / "run.log").write_text("done\n")

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    r = client.get("/api/projects/alpha/experiments/exp-001/artifacts")
    assert r.status_code == 200
    data = r.json()
    assert data["has_report"] is True
    assert data["has_presentation"] is True
    assert data["has_log"] is True
