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
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


@pytest.fixture
def stream_client_running(tmp_path: Path, monkeypatch):
    # Has lock — caller will remove it from a thread to end the stream
    proj = _make_project_with_log(tmp_path, "alpha", "exp-001", "initial\n", lock=True)
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
    r = stream_client_completed.get("/api/projects/nonexistent/runs/exp-001/stream")
    assert r.status_code == 404


def test_stream_survives_non_utf8_bytes_in_log(tmp_path: Path, monkeypatch):
    """Regression: the SSE log tailer used to open run.log with strict
    ``encoding="utf-8"``, so a single non-UTF8 byte (e.g. cp1252
    em-dash 0x97 emitted by the bundled claude CLI on Windows) would
    blow up the SSE connection with a UnicodeDecodeError. The stream
    now uses ``errors="replace"`` so bad bytes render as the
    Unicode replacement char without breaking the connection.
    """
    proj = tmp_path / "alpha"
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    # Write three lines, the middle one containing cp1252 byte 0x97
    # (em-dash) which is invalid as UTF-8.
    log_bytes = b"line1\nbefore\x97after\nline3\n"
    (exp_dir / "run.log").write_bytes(log_bytes)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    with client.stream(
        "GET", "/api/projects/alpha/runs/exp-001/stream"
    ) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")

    # Both healthy lines came through and the bad line is rendered
    # with the Unicode replacement char rather than killing the SSE
    # response with a 500.
    assert "data: line1" in body
    assert "data: line3" in body
    assert "event: status" in body
    assert '"completed"' in body


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

    with client.stream("GET", "/api/projects/alpha/runs/exp-001/stream") as r:
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "data: initial" in body
    assert "data: midway" in body
    assert "event: status" in body
    assert '"completed"' in body


def test_stream_emits_prompt_event_for_urika_prompt_line(tmp_path: Path, monkeypatch):
    """A URIKA-PROMPT: line in run.log should be emitted as an SSE
    'prompt' event with the trailing JSON payload as the data line —
    not as an ordinary data: event with the raw prefix in it.
    """
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    log_content = (
        "normal log line\n"
        'URIKA-PROMPT: {"prompt_id": "p-001", "question": "Which baseline?", '
        '"type": "text"}\n'
        "another normal line\n"
    )
    (exp_dir / "run.log").write_text(log_content)
    # No lock file → the stream sees the backlog and exits via "completed".

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    with client.stream("GET", "/api/projects/alpha/runs/exp-001/stream") as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")

    # Normal lines should be data: events
    assert "data: normal log line" in body
    assert "data: another normal line" in body
    # The URIKA-PROMPT line should be a prompt event with the JSON payload
    assert "event: prompt" in body
    assert '"prompt_id": "p-001"' in body
    assert '"question": "Which baseline?"' in body
    # The literal "URIKA-PROMPT:" prefix should NOT appear in any data: event
    assert "data: URIKA-PROMPT:" not in body
    # Should reach completion (no lock file)
    assert "event: status" in body
    assert '"completed"' in body


# ---- Per-agent log type (?type=evaluate|report|present) -------------------


@pytest.fixture
def stream_client_typed(tmp_path: Path, monkeypatch):
    """A project with all four per-agent log files written; no locks
    so each stream completes after draining its backlog."""
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "run.log").write_text("from-run-log\n")
    (exp_dir / "evaluate.log").write_text("from-evaluate-log\n")
    (exp_dir / "report.log").write_text("from-report-log\n")
    (exp_dir / "present.log").write_text("from-present-log\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_stream_type_evaluate_reads_evaluate_log(stream_client_typed):
    with stream_client_typed.stream(
        "GET", "/api/projects/alpha/runs/exp-001/stream?type=evaluate"
    ) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "data: from-evaluate-log" in body
    assert "data: from-run-log" not in body
    assert '"completed"' in body


def test_stream_type_report_reads_report_log(stream_client_typed):
    with stream_client_typed.stream(
        "GET", "/api/projects/alpha/runs/exp-001/stream?type=report"
    ) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "data: from-report-log" in body
    assert "data: from-run-log" not in body
    assert '"completed"' in body


def test_stream_type_present_reads_present_log(stream_client_typed):
    with stream_client_typed.stream(
        "GET", "/api/projects/alpha/runs/exp-001/stream?type=present"
    ) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "data: from-present-log" in body
    assert "data: from-run-log" not in body
    assert '"completed"' in body


def test_stream_type_unknown_falls_back_to_run(stream_client_typed):
    """Unknown type values must not 422 or escape into a filesystem
    path — they silently degrade to ``run.log``."""
    with stream_client_typed.stream(
        "GET", "/api/projects/alpha/runs/exp-001/stream?type=../etc/passwd"
    ) as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "data: from-run-log" in body
    assert "data: from-evaluate-log" not in body


def test_stream_type_default_still_reads_run_log(stream_client_typed):
    """No ?type= → default to run.log (existing behaviour)."""
    with stream_client_typed.stream(
        "GET", "/api/projects/alpha/runs/exp-001/stream"
    ) as r:
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "data: from-run-log" in body
    assert "data: from-evaluate-log" not in body


def test_stream_type_evaluate_watches_evaluate_lock(tmp_path: Path, monkeypatch):
    """The lock file selection must follow the type too — otherwise the
    stream would terminate as soon as the run.log lock disappeared even
    though evaluate is still running."""
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    eval_log = exp_dir / "evaluate.log"
    eval_log.write_text("first eval line\n")
    eval_lock = exp_dir / ".evaluate.lock"
    eval_lock.write_text("9999")
    # No .lock for run — if the route mistakenly watched .lock, the
    # stream would think the run was already done and skip the polling.

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    def append_then_unlock():
        time.sleep(0.6)
        with open(eval_log, "a", encoding="utf-8") as f:
            f.write("second eval line\n")
        time.sleep(0.6)
        eval_lock.unlink()

    threading.Thread(target=append_then_unlock, daemon=True).start()

    with client.stream(
        "GET", "/api/projects/alpha/runs/exp-001/stream?type=evaluate"
    ) as r:
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "data: first eval line" in body
    assert "data: second eval line" in body
    assert '"completed"' in body
