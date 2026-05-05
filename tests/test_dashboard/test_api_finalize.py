"""Tests for POST /api/projects/<name>/finalize and its SSE stream.

The spawn helper is stubbed via monkeypatch so tests never invoke a
real ``urika finalize`` subprocess. We assert: (a) the spawn helper
gets called with the right kwargs, (b) form validation rejects bogus
audience values, and (c) the SSE stream tails ``finalize.log`` and
emits ``completed`` when the lock disappears.
"""

from __future__ import annotations

import json
import threading
import time
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
def finalize_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, list[dict], Path]:
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    spawn_calls: list[dict] = []

    def fake_spawn(
        project_name, project_path, *, instructions="", audience=None, draft=False, **_
    ):
        spawn_calls.append(
            {
                "project_name": project_name,
                "project_path": project_path,
                "instructions": instructions,
                "audience": audience,
                "draft": draft,
            }
        )
        book_dir = project_path / "projectbook"
        book_dir.mkdir(parents=True, exist_ok=True)
        (book_dir / ".finalize.lock").write_text("88888")
        (book_dir / "finalize.log").write_text("Spawned\n")
        return 88888

    monkeypatch.setattr(runs_module, "spawn_finalize", fake_spawn)
    from urika.dashboard.routers import api as api_module

    monkeypatch.setattr(api_module, "spawn_finalize", fake_spawn)

    app = create_app(project_root=tmp_path)
    return TestClient(app), spawn_calls, proj


def test_finalize_post_started(finalize_client):
    client, spawn_calls, proj = finalize_client
    r = client.post(
        "/api/projects/alpha/finalize",
        data={"instructions": "be thorough", "audience": "standard"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert body["pid"] == 88888
    assert len(spawn_calls) == 1
    assert spawn_calls[0]["project_name"] == "alpha"
    assert spawn_calls[0]["project_path"] == proj
    assert spawn_calls[0]["instructions"] == "be thorough"
    assert spawn_calls[0]["audience"] == "standard"


def test_finalize_post_blank_audience_passes(finalize_client):
    """Empty audience should pass through as None — CLI uses its default."""
    client, spawn_calls, _ = finalize_client
    r = client.post("/api/projects/alpha/finalize", data={"audience": ""})
    assert r.status_code == 200
    assert spawn_calls[0]["audience"] is None


def test_finalize_post_404_unknown_project(finalize_client):
    client, _, _ = finalize_client
    r = client.post("/api/projects/nonexistent/finalize", data={})
    assert r.status_code == 404


def test_finalize_post_invalid_audience(finalize_client):
    """Audience values outside the finalize CLI's allow-list must 422."""
    client, spawn_calls, _ = finalize_client
    r = client.post(
        "/api/projects/alpha/finalize",
        data={"audience": "alien"},
    )
    assert r.status_code == 422
    assert spawn_calls == []


def test_finalize_post_accepts_finalize_specific_audience(finalize_client):
    """``standard`` is valid for finalize even though core/models excludes it."""
    client, spawn_calls, _ = finalize_client
    r = client.post(
        "/api/projects/alpha/finalize",
        data={"audience": "standard"},
    )
    assert r.status_code == 200
    assert spawn_calls[0]["audience"] == "standard"


def test_finalize_post_forwards_draft_flag(finalize_client):
    """The Draft-mode checkbox in the finalize modal must be forwarded
    to spawn_finalize as draft=True so the spawned subprocess gets
    --draft and writes to projectbook/draft/."""
    client, spawn_calls, _ = finalize_client
    r = client.post(
        "/api/projects/alpha/finalize",
        data={"instructions": "", "audience": "novice", "draft": "on"},
    )
    assert r.status_code == 200
    assert spawn_calls
    assert spawn_calls[0]["draft"] is True


def test_finalize_post_no_draft_defaults_false(finalize_client):
    """When the draft checkbox is left unchecked, spawn_finalize sees
    draft=False so the subprocess writes to the final outputs."""
    client, spawn_calls, _ = finalize_client
    r = client.post(
        "/api/projects/alpha/finalize",
        data={"instructions": "", "audience": "novice"},
    )
    assert r.status_code == 200
    assert spawn_calls
    assert spawn_calls[0]["draft"] is False


def test_finalize_post_hx_request_emits_redirect_header(finalize_client):
    """When the request comes from HTMX, the response should redirect the
    whole page to the finalize log so the user sees streaming output."""
    client, spawn_calls, _ = finalize_client
    r = client.post(
        "/api/projects/alpha/finalize",
        data={},
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects/alpha/finalize/log"
    assert len(spawn_calls) == 1


# ── SSE stream ────────────────────────────────────────────────────────────


def _make_project_with_finalize_log(
    tmp_path: Path, name: str, log: str, lock: bool
) -> Path:
    proj = _make_project(tmp_path, name)
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    (book / "finalize.log").write_text(log)
    if lock:
        (book / ".finalize.lock").write_text("123")
    return proj


@pytest.fixture
def finalize_stream_completed(tmp_path: Path, monkeypatch) -> TestClient:
    _make_project_with_finalize_log(
        tmp_path, "alpha", "step1\nstep2\nstep3\n", lock=False
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


@pytest.fixture
def finalize_stream_running(tmp_path: Path, monkeypatch):
    proj = _make_project_with_finalize_log(tmp_path, "alpha", "starting\n", lock=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app), proj


def test_finalize_stream_emits_existing_log_then_completes(finalize_stream_completed):
    with finalize_stream_completed.stream(
        "GET", "/api/projects/alpha/finalize/stream"
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "data: step1" in body
    assert "data: step2" in body
    assert "data: step3" in body
    assert "event: status" in body
    assert '"completed"' in body


def test_finalize_stream_404_unknown_project(finalize_stream_completed):
    r = finalize_stream_completed.get("/api/projects/nonexistent/finalize/stream")
    assert r.status_code == 404


@pytest.mark.slow
def test_finalize_stream_includes_new_lines_then_completes(finalize_stream_running):
    # v0.4.2 M15: writer-thread timing requires ~1.2s — marked slow so
    # default fast-loop runs skip it.
    client, proj = finalize_stream_running
    log_path = proj / "projectbook" / "finalize.log"
    lock_path = proj / "projectbook" / ".finalize.lock"

    def append_then_unlock():
        time.sleep(0.6)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("midway\n")
        time.sleep(0.6)
        lock_path.unlink()

    threading.Thread(target=append_then_unlock, daemon=True).start()

    with client.stream("GET", "/api/projects/alpha/finalize/stream") as r:
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "data: starting" in body
    assert "data: midway" in body
    assert "event: status" in body
    assert '"completed"' in body


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


def test_finalize_post_private_mode_without_endpoint_returns_422(
    tmp_path: Path, monkeypatch
):
    """Pre-flight gate: finalize on a private-mode project with no
    private endpoint configured anywhere must 422 before the spawn
    helper is called."""
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

    monkeypatch.setattr(runs_module, "spawn_finalize", fake_spawn)
    from urika.dashboard.routers import api as api_module

    monkeypatch.setattr(api_module, "spawn_finalize", fake_spawn)

    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    r = client.post(
        "/api/projects/alpha/finalize",
        data={"instructions": "", "audience": "standard"},
    )
    assert r.status_code == 422
    assert spawn_calls == []


# ---- Idempotent spawn: redirect to live log when already running ---------


def test_finalize_post_when_already_running_redirects_to_log(finalize_client):
    """HTMX POST while a finalize is already running must NOT spawn
    a duplicate. Instead, respond with HX-Redirect to the live log."""
    import os

    client, spawn_calls, proj = finalize_client
    book = proj / "projectbook"
    book.mkdir(exist_ok=True)
    (book / ".finalize.lock").write_text(str(os.getpid()))

    r = client.post(
        "/api/projects/alpha/finalize",
        headers={"hx-request": "true"},
        data={},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects/alpha/finalize/log"
    assert spawn_calls == []


def test_finalize_post_when_already_running_returns_409_without_hx(
    finalize_client,
):
    """Non-HTMX caller (curl, scripts) must get a 409 with a JSON body
    so they can detect the duplicate explicitly instead of a 200."""
    import os

    client, spawn_calls, proj = finalize_client
    book = proj / "projectbook"
    book.mkdir(exist_ok=True)
    (book / ".finalize.lock").write_text(str(os.getpid()))

    r = client.post(
        "/api/projects/alpha/finalize",
        data={},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["status"] == "already_running"
    assert body["log_url"] == "/projects/alpha/finalize/log"
    assert body["type"] == "finalize"
    assert spawn_calls == []
