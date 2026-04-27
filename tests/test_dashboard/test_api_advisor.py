"""Tests for POST /api/projects/<name>/advisor.

The advisor agent is now spawned as a subprocess matching every other
agent (summarize / finalize / report / present / evaluate / build-tool).
Tests stub ``spawn_advisor`` via monkeypatch so we never invoke a real
``urika advisor`` subprocess. We assert: (a) the spawn helper gets
called with the project name + path + question, (b) HTMX requests
HX-Redirect to the live log page, (c) blank/whitespace question is
rejected with 422, (d) 404 for unknown projects, (e) a duplicate spawn
while one is already running redirects to the live log instead of
spawning, and (f) the privacy gate fires before spawn when private
mode lacks an endpoint.
"""

from __future__ import annotations

import json
import os
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
    return proj


@pytest.fixture
def advisor_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, list[dict], Path]:
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    spawn_calls: list[dict] = []

    def fake_spawn(project_name, project_path, question, **_):
        spawn_calls.append(
            {
                "project_name": project_name,
                "project_path": project_path,
                "question": question,
            }
        )
        book_dir = project_path / "projectbook"
        book_dir.mkdir(parents=True, exist_ok=True)
        (book_dir / ".advisor.lock").write_text("88888")
        (book_dir / "advisor.log").write_text("Spawned\n")
        return 88888

    monkeypatch.setattr(runs_module, "spawn_advisor", fake_spawn)
    monkeypatch.setattr(api_module, "spawn_advisor", fake_spawn)

    app = create_app(project_root=tmp_path)
    return TestClient(app), spawn_calls, proj


def test_advisor_post_started(advisor_client):
    client, spawn_calls, proj = advisor_client
    r = client.post(
        "/api/projects/alpha/advisor",
        data={"question": "what next?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert body["pid"] == 88888

    assert len(spawn_calls) == 1
    assert spawn_calls[0]["project_name"] == "alpha"
    assert spawn_calls[0]["project_path"] == proj
    assert spawn_calls[0]["question"] == "what next?"


def test_advisor_post_hx_redirect_to_log(advisor_client):
    """HTMX requests should redirect to the live log streaming page."""
    client, spawn_calls, _ = advisor_client
    r = client.post(
        "/api/projects/alpha/advisor",
        data={"question": "what next?"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects/alpha/advisor/log"
    assert len(spawn_calls) == 1


def test_advisor_post_404_unknown_project(advisor_client):
    client, spawn_calls, _ = advisor_client
    r = client.post(
        "/api/projects/nonexistent/advisor",
        data={"question": "anything"},
    )
    assert r.status_code == 404
    assert spawn_calls == []


def test_advisor_post_blank_question_422(advisor_client):
    """An empty or whitespace-only question is rejected before spawn."""
    client, spawn_calls, _ = advisor_client
    r = client.post("/api/projects/alpha/advisor", data={"question": "   "})
    assert r.status_code == 422
    assert "question" in r.json()["detail"]
    assert spawn_calls == []


def test_advisor_post_missing_question_422(advisor_client):
    """Missing the question field at all is also rejected."""
    client, spawn_calls, _ = advisor_client
    r = client.post("/api/projects/alpha/advisor", data={})
    assert r.status_code == 422
    assert spawn_calls == []


def test_advisor_post_when_already_running_redirects_to_log(advisor_client):
    """HTMX POST while an advisor is already running must NOT spawn a
    duplicate. Instead, respond with HX-Redirect to the live log."""
    client, spawn_calls, proj = advisor_client
    book = proj / "projectbook"
    book.mkdir(exist_ok=True)
    (book / ".advisor.lock").write_text(str(os.getpid()))

    r = client.post(
        "/api/projects/alpha/advisor",
        headers={"hx-request": "true"},
        data={"question": "another question"},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects/alpha/advisor/log"
    assert spawn_calls == []


def test_advisor_post_when_already_running_returns_409_without_hx(advisor_client):
    """Non-HTMX caller (curl, scripts) must get a 409 with a JSON body
    so they can detect the duplicate explicitly."""
    client, spawn_calls, proj = advisor_client
    book = proj / "projectbook"
    book.mkdir(exist_ok=True)
    (book / ".advisor.lock").write_text(str(os.getpid()))

    r = client.post(
        "/api/projects/alpha/advisor",
        data={"question": "another question"},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["status"] == "already_running"
    assert body["log_url"] == "/projects/alpha/advisor/log"
    assert body["type"] == "advisor"
    assert spawn_calls == []


# ---- Privacy pre-flight check ---------------------------------------------


def _make_private_project(tmp_path: Path, name: str = "alpha") -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n\n'
        f'[privacy]\nmode = "private"\n'
    )
    return proj


def test_advisor_post_privacy_gate_blocks_unconfigured_private(
    tmp_path: Path, monkeypatch
):
    """Pre-flight gate: advisor on a private-mode project with no
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

    monkeypatch.setattr(runs_module, "spawn_advisor", fake_spawn)
    monkeypatch.setattr(api_module, "spawn_advisor", fake_spawn)

    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    r = client.post(
        "/api/projects/alpha/advisor",
        data={"question": "any question"},
    )
    assert r.status_code == 422
    assert spawn_calls == []
