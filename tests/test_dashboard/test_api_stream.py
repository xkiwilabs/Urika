"""Tests for GET /api/projects/<name>/runs/<exp_id>/stream — SSE log tailer.

The SSE polling cadence is 0.5s, so the threaded test that simulates
appending lines and removing the lock takes a couple of seconds end
to end. That's intentional: the route polls the on-disk log until the
lockfile disappears, then emits a status:completed event and closes.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _make_project_with_log(
    tmp_path: Path, name: str, exp_id: str, log: str, lock: bool
) -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / exp_id
    exp_dir.mkdir(parents=True)
    (exp_dir / "run.log").write_text(log)
    if lock:
        (exp_dir / ".lock").write_text("123")
    return proj


@pytest.fixture
def stream_client_completed(tmp_path: Path, monkeypatch) -> TestClient:
    # No lock — simulates a completed run with full log on disk
    _make_project_with_log(
        tmp_path, "alpha", "exp-001", "line1\nline2\nline3\n", lock=False
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
def stream_client_running(tmp_path: Path, monkeypatch):
    # Has lock — caller will remove it from a thread to end the stream
    proj = _make_project_with_log(
        tmp_path, "alpha", "exp-001", "initial\n", lock=True
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app), proj


def test_stream_emits_existing_log_then_completes(stream_client_completed):
    with stream_client_completed.stream(
        "GET", "/api/projects/alpha/runs/exp-001/stream"
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "data: line1" in body
    assert "data: line2" in body
    assert "data: line3" in body
    assert "event: status" in body
    assert '"completed"' in body


def test_stream_404_unknown_project(stream_client_completed):
    r = stream_client_completed.get(
        "/api/projects/nonexistent/runs/exp-001/stream"
    )
    assert r.status_code == 404


def test_stream_includes_new_lines_then_completes(stream_client_running):
    client, proj = stream_client_running
    log_path = proj / "experiments" / "exp-001" / "run.log"
    lock_path = proj / "experiments" / "exp-001" / ".lock"

    def append_then_unlock():
        time.sleep(0.6)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("midway\n")
        time.sleep(0.6)
        lock_path.unlink()

    threading.Thread(target=append_then_unlock, daemon=True).start()

    with client.stream(
        "GET", "/api/projects/alpha/runs/exp-001/stream"
    ) as r:
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "data: initial" in body
    assert "data: midway" in body
    assert "event: status" in body
    assert '"completed"' in body
