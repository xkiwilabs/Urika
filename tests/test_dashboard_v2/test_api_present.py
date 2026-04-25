"""Tests for POST /api/projects/<name>/present.

Spawns are stubbed via monkeypatch so tests never invoke a real
``urika present`` subprocess. We assert: (a) the spawn helper gets
called with the right args when the experiment dir exists, (b) form
validation rejects missing/unknown experiments and bogus audiences,
and (c) 404 is returned for unknown projects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard_v2 import runs as runs_module
from urika.dashboard_v2.app import create_app


def _make_project_with_experiment(
    tmp_path: Path, name: str = "alpha", exp_id: str = "exp-001"
) -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / exp_id
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text("{}")
    return proj


@pytest.fixture
def present_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, list[dict], Path]:
    proj = _make_project_with_experiment(tmp_path, "alpha", "exp-001")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    spawn_calls: list[dict] = []

    def fake_spawn(
        project_name,
        project_path,
        experiment_id,
        *,
        instructions="",
        audience=None,
        **_,
    ):
        spawn_calls.append(
            {
                "project_name": project_name,
                "project_path": project_path,
                "experiment_id": experiment_id,
                "instructions": instructions,
                "audience": audience,
            }
        )
        exp_dir = project_path / "experiments" / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / ".present.lock").write_text("77777")
        (exp_dir / "present.log").write_text("Spawned\n")
        return 77777

    monkeypatch.setattr(runs_module, "spawn_present", fake_spawn)
    from urika.dashboard_v2.routers import api as api_module

    monkeypatch.setattr(api_module, "spawn_present", fake_spawn)

    app = create_app(project_root=tmp_path)
    return TestClient(app), spawn_calls, proj


def test_present_post_started(present_client):
    client, spawn_calls, proj = present_client
    r = client.post(
        "/api/projects/alpha/present",
        data={"experiment_id": "exp-001"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert body["pid"] == 77777
    assert body["experiment_id"] == "exp-001"
    assert len(spawn_calls) == 1
    assert spawn_calls[0]["project_name"] == "alpha"
    assert spawn_calls[0]["project_path"] == proj
    assert spawn_calls[0]["experiment_id"] == "exp-001"


def test_present_post_passes_instructions_and_audience(present_client):
    client, spawn_calls, _ = present_client
    r = client.post(
        "/api/projects/alpha/present",
        data={
            "experiment_id": "exp-001",
            "instructions": "emphasize ensembles",
            "audience": "expert",
        },
    )
    assert r.status_code == 200
    assert spawn_calls[0]["instructions"] == "emphasize ensembles"
    assert spawn_calls[0]["audience"] == "expert"


def test_present_post_404_unknown_project(present_client):
    client, _, _ = present_client
    r = client.post(
        "/api/projects/nonexistent/present",
        data={"experiment_id": "exp-001"},
    )
    assert r.status_code == 404


def test_present_post_missing_experiment_id(present_client):
    client, spawn_calls, _ = present_client
    r = client.post("/api/projects/alpha/present", data={})
    assert r.status_code == 422
    assert "experiment_id" in r.json()["detail"]
    assert spawn_calls == []


def test_present_post_unknown_experiment(present_client):
    client, spawn_calls, _ = present_client
    r = client.post(
        "/api/projects/alpha/present",
        data={"experiment_id": "exp-does-not-exist"},
    )
    assert r.status_code == 422
    assert spawn_calls == []


def test_present_post_invalid_audience(present_client):
    client, spawn_calls, _ = present_client
    r = client.post(
        "/api/projects/alpha/present",
        data={"experiment_id": "exp-001", "audience": "alien"},
    )
    assert r.status_code == 422
    assert spawn_calls == []


def test_present_post_blank_audience_passes_as_none(present_client):
    client, spawn_calls, _ = present_client
    r = client.post(
        "/api/projects/alpha/present",
        data={"experiment_id": "exp-001", "audience": ""},
    )
    assert r.status_code == 200
    assert spawn_calls[0]["audience"] is None
