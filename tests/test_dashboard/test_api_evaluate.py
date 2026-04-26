"""Tests for POST /api/projects/<name>/experiments/<exp_id>/evaluate.

The spawn helper is stubbed via monkeypatch so tests never invoke a
real ``urika evaluate`` subprocess. We assert: (a) the spawn helper
gets called with the right kwargs, (b) 404 for unknown projects,
(c) 422 for unknown experiments, and (d) HX-Redirect when called
from HTMX.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard import runs as runs_module
from urika.dashboard.app import create_app
from urika.dashboard.routers import api as api_module


def _make_project(tmp_path: Path, name: str = "alpha") -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text("{}")
    return proj


@pytest.fixture
def evaluate_client(tmp_path: Path, monkeypatch):
    proj = _make_project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    spawn_calls: list[dict] = []

    def fake_spawn(project_name, project_path, experiment_id, *, instructions="", **_):
        spawn_calls.append(
            {
                "project_name": project_name,
                "project_path": project_path,
                "experiment_id": experiment_id,
                "instructions": instructions,
            }
        )
        exp_dir = project_path / "experiments" / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / ".evaluate.lock").write_text("99999")
        (exp_dir / "evaluate.log").write_text("Spawned\n")
        return 99999

    monkeypatch.setattr(runs_module, "spawn_evaluate", fake_spawn)
    monkeypatch.setattr(api_module, "spawn_evaluate", fake_spawn)
    app = create_app(project_root=tmp_path)
    return TestClient(app), spawn_calls, proj


def test_evaluate_post_started(evaluate_client):
    client, spawn_calls, proj = evaluate_client
    r = client.post(
        "/api/projects/alpha/experiments/exp-001/evaluate",
        data={"instructions": "check overfitting"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert body["pid"] == 99999
    assert body["experiment_id"] == "exp-001"
    assert len(spawn_calls) == 1
    assert spawn_calls[0]["project_name"] == "alpha"
    assert spawn_calls[0]["project_path"] == proj
    assert spawn_calls[0]["experiment_id"] == "exp-001"
    assert spawn_calls[0]["instructions"] == "check overfitting"


def test_evaluate_post_blank_instructions_passes(evaluate_client):
    client, spawn_calls, _ = evaluate_client
    r = client.post(
        "/api/projects/alpha/experiments/exp-001/evaluate",
        data={"instructions": ""},
    )
    assert r.status_code == 200
    assert spawn_calls[0]["instructions"] == ""


def test_evaluate_post_404_unknown_project(evaluate_client):
    client, spawn_calls, _ = evaluate_client
    r = client.post(
        "/api/projects/nonexistent/experiments/exp-001/evaluate",
        data={"instructions": ""},
    )
    assert r.status_code == 404
    assert spawn_calls == []


def test_evaluate_post_422_unknown_experiment(evaluate_client):
    client, spawn_calls, _ = evaluate_client
    r = client.post(
        "/api/projects/alpha/experiments/exp-999/evaluate",
        data={"instructions": ""},
    )
    assert r.status_code == 422
    assert spawn_calls == []


def test_evaluate_post_hx_request_emits_redirect_header(evaluate_client):
    """When the request comes from HTMX, the response should redirect the
    whole page to the experiment log so the user sees streaming output."""
    client, spawn_calls, _ = evaluate_client
    r = client.post(
        "/api/projects/alpha/experiments/exp-001/evaluate",
        headers={"hx-request": "true"},
        data={"instructions": ""},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect", "").endswith(
        "/projects/alpha/experiments/exp-001/log?type=evaluate"
    )
    assert len(spawn_calls) == 1


# ---- Privacy pre-flight check ---------------------------------------------


def _make_private_project(tmp_path: Path, name: str = "alpha") -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n\n'
        f'[privacy]\nmode = "private"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text("{}")
    return proj


def test_evaluate_post_private_mode_without_endpoint_returns_422(
    tmp_path: Path, monkeypatch
):
    """Pre-flight gate: evaluate on a private-mode project with no
    private endpoint must 422 before the spawn helper runs."""
    proj = _make_private_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    (home / "settings.toml").write_text("", encoding="utf-8")

    spawn_calls: list[dict] = []

    def fake_spawn(*a, **kw):
        spawn_calls.append({"args": a, "kwargs": kw})
        return 1234

    monkeypatch.setattr(runs_module, "spawn_evaluate", fake_spawn)
    monkeypatch.setattr(api_module, "spawn_evaluate", fake_spawn)

    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    r = client.post(
        "/api/projects/alpha/experiments/exp-001/evaluate",
        data={"instructions": ""},
    )
    assert r.status_code == 422
    assert spawn_calls == []
