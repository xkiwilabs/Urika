"""Tests for POST /api/projects/<name>/tools/build.

The spawn helper is stubbed via monkeypatch so tests never invoke a
real ``urika build-tool`` subprocess. We assert: (a) the spawn helper
gets called with the right kwargs, (b) blank instructions are rejected,
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
def build_tool_client(
    tmp_path: Path, monkeypatch
) -> tuple[TestClient, list[dict], Path]:
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    spawn_calls: list[dict] = []

    def fake_spawn(project_name, project_path, *, instructions, **_):
        spawn_calls.append(
            {
                "project_name": project_name,
                "project_path": project_path,
                "instructions": instructions,
            }
        )
        tools_dir = project_path / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        (tools_dir / ".build.lock").write_text("66666")
        (tools_dir / "build.log").write_text("Spawned\n")
        return 66666

    monkeypatch.setattr(runs_module, "spawn_build_tool", fake_spawn)
    monkeypatch.setattr(api_module, "spawn_build_tool", fake_spawn)

    app = create_app(project_root=tmp_path)
    return TestClient(app), spawn_calls, proj


def test_build_tool_post_started(build_tool_client):
    client, spawn_calls, proj = build_tool_client
    r = client.post(
        "/api/projects/alpha/tools/build",
        data={"instructions": "build a Pearson correlation heatmap tool"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert body["pid"] == 66666
    assert len(spawn_calls) == 1
    assert spawn_calls[0]["project_name"] == "alpha"
    assert spawn_calls[0]["project_path"] == proj
    assert spawn_calls[0]["instructions"] == (
        "build a Pearson correlation heatmap tool"
    )


def test_build_tool_post_blank_instructions_returns_422(build_tool_client):
    """Empty instructions must 422 — the build-tool CLI takes the
    description as a positional arg and would otherwise block on the
    interactive prompt."""
    client, spawn_calls, _ = build_tool_client
    r = client.post(
        "/api/projects/alpha/tools/build",
        data={"instructions": ""},
    )
    assert r.status_code == 422
    assert spawn_calls == []


def test_build_tool_post_whitespace_instructions_returns_422(build_tool_client):
    """All-whitespace instructions must 422 — same reason as the blank case."""
    client, spawn_calls, _ = build_tool_client
    r = client.post(
        "/api/projects/alpha/tools/build",
        data={"instructions": "   \t\n  "},
    )
    assert r.status_code == 422
    assert spawn_calls == []


def test_build_tool_post_no_form_body_returns_422(build_tool_client):
    """Request with no instructions field at all must 422."""
    client, spawn_calls, _ = build_tool_client
    r = client.post("/api/projects/alpha/tools/build", data={})
    assert r.status_code == 422
    assert spawn_calls == []


def test_build_tool_post_404_unknown_project(build_tool_client):
    client, spawn_calls, _ = build_tool_client
    r = client.post(
        "/api/projects/nonexistent/tools/build",
        data={"instructions": "anything"},
    )
    assert r.status_code == 404
    assert spawn_calls == []


def test_build_tool_post_hx_request_emits_redirect_header(build_tool_client):
    """HTMX requests should redirect the whole page to the live log."""
    client, spawn_calls, _ = build_tool_client
    r = client.post(
        "/api/projects/alpha/tools/build",
        data={"instructions": "make a thing"},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects/alpha/tools/build/log"
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


def test_build_tool_post_private_mode_without_endpoint_returns_422(
    tmp_path: Path, monkeypatch
):
    """Pre-flight gate: build-tool on a private-mode project with no
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

    monkeypatch.setattr(runs_module, "spawn_build_tool", fake_spawn)
    monkeypatch.setattr(api_module, "spawn_build_tool", fake_spawn)

    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    r = client.post(
        "/api/projects/alpha/tools/build",
        data={"instructions": "describe a tool"},
    )
    assert r.status_code == 422
    assert spawn_calls == []


# ---- Idempotent spawn: redirect to live log when already running ---------


def test_build_tool_post_when_already_running_redirects_to_log(build_tool_client):
    """HTMX POST while a build-tool run is already in flight must NOT
    spawn a duplicate. Instead, respond with HX-Redirect to the live log."""
    import os

    client, spawn_calls, proj = build_tool_client
    tools_dir = proj / "tools"
    tools_dir.mkdir(exist_ok=True)
    (tools_dir / ".build.lock").write_text(str(os.getpid()))

    r = client.post(
        "/api/projects/alpha/tools/build",
        headers={"hx-request": "true"},
        data={"instructions": "anything"},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects/alpha/tools/build/log"
    assert spawn_calls == []


def test_build_tool_post_when_already_running_returns_409_without_hx(
    build_tool_client,
):
    """Non-HTMX caller (curl, scripts) must get a 409 with a JSON body
    so they can detect the duplicate explicitly instead of a 200."""
    import os

    client, spawn_calls, proj = build_tool_client
    tools_dir = proj / "tools"
    tools_dir.mkdir(exist_ok=True)
    (tools_dir / ".build.lock").write_text(str(os.getpid()))

    r = client.post(
        "/api/projects/alpha/tools/build",
        data={"instructions": "anything"},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["status"] == "already_running"
    assert body["log_url"] == "/projects/alpha/tools/build/log"
    assert body["type"] == "build_tool"
    assert spawn_calls == []
