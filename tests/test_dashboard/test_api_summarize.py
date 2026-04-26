"""Tests for POST /api/projects/<name>/summarize.

The spawn helper is stubbed via monkeypatch so tests never invoke a
real ``urika summarize`` subprocess. We assert: (a) the spawn helper
gets called with the right kwargs, (b) blank instructions still spawn,
(c) 404 for unknown projects, (d) HX-Redirect when called from HTMX,
and (e) the privacy gate fires before spawn when private mode lacks
an endpoint.
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
    return proj


@pytest.fixture
def summarize_client(
    tmp_path: Path, monkeypatch
) -> tuple[TestClient, list[dict], Path]:
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    spawn_calls: list[dict] = []

    def fake_spawn(project_name, project_path, *, instructions="", **_):
        spawn_calls.append(
            {
                "project_name": project_name,
                "project_path": project_path,
                "instructions": instructions,
            }
        )
        book_dir = project_path / "projectbook"
        book_dir.mkdir(parents=True, exist_ok=True)
        (book_dir / ".summarize.lock").write_text("77777")
        (book_dir / "summarize.log").write_text("Spawned\n")
        return 77777

    monkeypatch.setattr(runs_module, "spawn_summarize", fake_spawn)
    monkeypatch.setattr(api_module, "spawn_summarize", fake_spawn)

    app = create_app(project_root=tmp_path)
    return TestClient(app), spawn_calls, proj


def test_summarize_post_started(summarize_client):
    client, spawn_calls, proj = summarize_client
    r = client.post(
        "/api/projects/alpha/summarize",
        data={"instructions": "focus on open questions"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert body["pid"] == 77777
    assert len(spawn_calls) == 1
    assert spawn_calls[0]["project_name"] == "alpha"
    assert spawn_calls[0]["project_path"] == proj
    assert spawn_calls[0]["instructions"] == "focus on open questions"


def test_summarize_post_blank_instructions_passes(summarize_client):
    """Empty instructions should pass through as an empty string —
    the CLI just runs the default prompt."""
    client, spawn_calls, _ = summarize_client
    r = client.post("/api/projects/alpha/summarize", data={"instructions": ""})
    assert r.status_code == 200
    assert spawn_calls[0]["instructions"] == ""


def test_summarize_post_no_form_body_passes(summarize_client):
    """Request with no instructions field at all should still spawn."""
    client, spawn_calls, _ = summarize_client
    r = client.post("/api/projects/alpha/summarize", data={})
    assert r.status_code == 200
    assert len(spawn_calls) == 1
    assert spawn_calls[0]["instructions"] == ""


def test_summarize_post_404_unknown_project(summarize_client):
    client, spawn_calls, _ = summarize_client
    r = client.post("/api/projects/nonexistent/summarize", data={})
    assert r.status_code == 404
    assert spawn_calls == []


def test_summarize_post_hx_request_emits_redirect_header(summarize_client):
    """HTMX requests should redirect the whole page to the live log."""
    client, spawn_calls, _ = summarize_client
    r = client.post(
        "/api/projects/alpha/summarize",
        data={},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects/alpha/summarize/log"
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
    return proj


def test_summarize_post_private_mode_without_endpoint_returns_422(
    tmp_path: Path, monkeypatch
):
    """Pre-flight gate: summarize on a private-mode project with no
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

    monkeypatch.setattr(runs_module, "spawn_summarize", fake_spawn)
    monkeypatch.setattr(api_module, "spawn_summarize", fake_spawn)

    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    r = client.post(
        "/api/projects/alpha/summarize",
        data={"instructions": ""},
    )
    assert r.status_code == 422
    assert spawn_calls == []


# ---- Idempotent spawn: redirect to live log when already running ---------


def test_summarize_post_when_already_running_redirects_to_log(summarize_client):
    """HTMX POST while a summarize is already running must NOT spawn
    a duplicate. Instead, respond with HX-Redirect to the live log."""
    import os

    client, spawn_calls, proj = summarize_client
    book = proj / "projectbook"
    book.mkdir(exist_ok=True)
    (book / ".summarize.lock").write_text(str(os.getpid()))

    r = client.post(
        "/api/projects/alpha/summarize",
        headers={"hx-request": "true"},
        data={"instructions": ""},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects/alpha/summarize/log"
    assert spawn_calls == []


def test_summarize_post_when_already_running_returns_409_without_hx(
    summarize_client,
):
    """Non-HTMX caller (curl, scripts) must get a 409 with a JSON body
    so they can detect the duplicate explicitly instead of a 200."""
    import os

    client, spawn_calls, proj = summarize_client
    book = proj / "projectbook"
    book.mkdir(exist_ok=True)
    (book / ".summarize.lock").write_text(str(os.getpid()))

    r = client.post(
        "/api/projects/alpha/summarize",
        data={"instructions": ""},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["status"] == "already_running"
    assert body["log_url"] == "/projects/alpha/summarize/log"
    assert body["type"] == "summarize"
    assert spawn_calls == []
