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

    def fake_spawn(project_name, project_path, *, instructions="", audience=None, **_):
        spawn_calls.append(
            {
                "project_name": project_name,
                "project_path": project_path,
                "instructions": instructions,
                "audience": audience,
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
    (home / "projects.json").write_text(
        json.dumps({"alpha": str(tmp_path / "alpha")})
    )
    app = create_app(project_root=tmp_path)
    return TestClient(app)


@pytest.fixture
def finalize_stream_running(tmp_path: Path, monkeypatch):
    proj = _make_project_with_finalize_log(
        tmp_path, "alpha", "starting\n", lock=True
    )
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


def test_finalize_stream_includes_new_lines_then_completes(finalize_stream_running):
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
