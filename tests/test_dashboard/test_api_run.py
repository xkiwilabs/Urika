"""Tests for POST /api/projects/<name>/run.

Spawns are stubbed via monkeypatch so the tests never invoke a
real ``urika run`` subprocess. We assert: (a) the experiment dir
is materialized on disk, (b) the spawn helper was called with
the right args, and (c) JSON vs HTMX response shaping behaves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard import runs as runs_module
from urika.dashboard.app import create_app


def _make_project(tmp_path: Path, name: str = "alpha") -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    return proj


@pytest.fixture
def run_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, list[dict], Path]:
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    spawn_calls: list[dict] = []

    def fake_spawn(project_name, project_path, experiment_id, **_):
        spawn_calls.append(
            {
                "project_name": project_name,
                "project_path": project_path,
                "experiment_id": experiment_id,
            }
        )
        # Simulate the daemon thread's first writes
        exp_dir = project_path / "experiments" / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / ".lock").write_text("99999")
        (exp_dir / "run.log").write_text("Spawned\n")
        return 99999

    monkeypatch.setattr(runs_module, "spawn_experiment_run", fake_spawn)
    # Also patch the symbol where the API router imported it from
    from urika.dashboard.routers import api as api_module

    monkeypatch.setattr(api_module, "spawn_experiment_run", fake_spawn)

    app = create_app(project_root=tmp_path)
    return TestClient(app), spawn_calls, proj


def test_run_post_creates_experiment_and_spawns(run_client):
    client, spawn_calls, proj = run_client
    r = client.post(
        "/api/projects/alpha/run",
        headers={"accept": "application/json"},
        data={
            "name": "baseline",
            "hypothesis": "linear models will fit",
            "mode": "exploratory",
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert body["pid"] == 99999
    exp_id = body["experiment_id"]
    # Experiment dir exists
    assert (proj / "experiments" / exp_id / "experiment.json").exists()
    # Lock file written by fake spawn
    assert (proj / "experiments" / exp_id / ".lock").read_text() == "99999"
    # Spawn was called with the right args
    assert len(spawn_calls) == 1
    assert spawn_calls[0]["project_name"] == "alpha"
    assert spawn_calls[0]["experiment_id"] == exp_id
    assert spawn_calls[0]["project_path"] == proj


def test_run_post_returns_html_fragment_by_default(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "name": "baseline",
            "hypothesis": "h",
            "mode": "exploratory",
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 200
    assert "View live log" in r.text


def test_run_post_404_unknown_project(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/nonexistent/run",
        data={
            "name": "x",
            "hypothesis": "h",
            "mode": "exploratory",
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 404


def test_run_post_invalid_max_turns(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "name": "x",
            "hypothesis": "h",
            "mode": "exploratory",
            "audience": "expert",
            "max_turns": "-1",
            "instructions": "",
        },
    )
    assert r.status_code == 422


def test_run_post_non_integer_max_turns(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "name": "x",
            "hypothesis": "h",
            "mode": "exploratory",
            "audience": "expert",
            "max_turns": "not-a-number",
            "instructions": "",
        },
    )
    assert r.status_code == 422


def test_run_post_invalid_mode(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "name": "x",
            "hypothesis": "h",
            "mode": "garbage",
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 422


def test_run_post_invalid_audience(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "name": "x",
            "hypothesis": "h",
            "mode": "exploratory",
            "audience": "alien",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 422


def test_run_post_missing_required_fields(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "name": "",  # empty
            "hypothesis": "",
            "mode": "exploratory",
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 422


def test_run_stop_writes_flag(run_client):
    client, _, proj = run_client
    r = client.post("/api/projects/alpha/runs/exp-001/stop")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "stop_requested"
    assert body["experiment_id"] == "exp-001"
    flag_path = proj / ".urika" / "pause_requested"
    assert flag_path.exists()
    assert flag_path.read_text() == "stop"


def test_run_stop_404_unknown_project(run_client):
    client, _, _ = run_client
    r = client.post("/api/projects/nonexistent/runs/exp-001/stop")
    assert r.status_code == 404


def test_run_stop_creates_dotdir_if_missing(run_client):
    """The .urika dir doesn't exist by default; the endpoint must mkdir it."""
    client, _, proj = run_client
    assert not (proj / ".urika").exists()
    r = client.post("/api/projects/alpha/runs/exp-001/stop")
    assert r.status_code == 200
    assert (proj / ".urika").is_dir()
