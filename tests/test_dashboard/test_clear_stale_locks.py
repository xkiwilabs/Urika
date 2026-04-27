"""Tests for clear_stale_locks helper + POST clear-stale endpoint.

User-recovery path for crashed agent subprocesses that left a stale
``.lock`` file behind. Without this, the running-op detector keeps
reporting the project as "running" forever and blocks new runs +
resume.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.active_ops import clear_stale_locks
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
def project(tmp_path: Path) -> Path:
    return _make_project(tmp_path, "alpha")


# ---- Helper-level tests ----


def test_clear_stale_locks_removes_dead_pid(project):
    exp = project / "experiments" / "exp-001"
    exp.mkdir(parents=True)
    lock = exp / ".lock"
    lock.write_text("99999999")  # virtually guaranteed dead

    cleared = clear_stale_locks(project)
    assert not lock.exists()
    assert len(cleared) == 1
    assert cleared[0].pid == 99999999
    assert cleared[0].reason == "dead"


def test_clear_stale_locks_removes_empty_lock(project):
    exp = project / "experiments" / "exp-001"
    exp.mkdir(parents=True)
    lock = exp / ".lock"
    lock.touch()

    cleared = clear_stale_locks(project)
    assert not lock.exists()
    assert len(cleared) == 1
    assert cleared[0].pid is None
    assert cleared[0].reason == "empty"


def test_clear_stale_locks_removes_non_numeric(project):
    exp = project / "experiments" / "exp-001"
    exp.mkdir(parents=True)
    lock = exp / ".lock"
    lock.write_text("garbage-not-a-pid")

    cleared = clear_stale_locks(project)
    assert not lock.exists()
    assert len(cleared) == 1
    assert cleared[0].reason == "non-numeric"


def test_clear_stale_locks_leaves_live_locks_alone(project):
    """Locks pointing at this test process's PID must NOT be removed —
    only dead ones get cleared. Otherwise we'd kill real running runs
    by accident."""
    exp = project / "experiments" / "exp-001"
    exp.mkdir(parents=True)
    lock = exp / ".lock"
    lock.write_text(str(os.getpid()))

    cleared = clear_stale_locks(project)
    assert lock.exists(), "live-PID lock must not be removed"
    assert cleared == []


def test_clear_stale_locks_walks_all_known_lock_shapes(project):
    """All seven known lock locations get inspected — project-level
    finalize/summarize/build plus per-experiment .lock/.evaluate/.report/.present."""
    (project / "projectbook").mkdir()
    (project / "tools").mkdir()
    exp = project / "experiments" / "exp-001"
    exp.mkdir(parents=True)

    locks = [
        project / "projectbook" / ".finalize.lock",
        project / "projectbook" / ".summarize.lock",
        project / "tools" / ".build.lock",
        exp / ".lock",
        exp / ".evaluate.lock",
        exp / ".report.lock",
        exp / ".present.lock",
    ]
    for lock in locks:
        lock.write_text("99999999")  # all dead

    cleared = clear_stale_locks(project)
    assert len(cleared) == 7
    for lock in locks:
        assert not lock.exists(), f"{lock} should have been cleared"


def test_clear_stale_locks_ignores_non_known_lock_files(project):
    """Random .lock files in unrelated locations are NOT touched —
    only the known agent-lock shapes are inspected. Defends against
    deleting urika.core.filelock JSON-mutex files that share the
    .lock suffix but live elsewhere."""
    (project / "criteria.json.lock").write_text("99999999")
    (project / "usage.json.lock").write_text("99999999")

    cleared = clear_stale_locks(project)
    assert cleared == []
    assert (project / "criteria.json.lock").exists()
    assert (project / "usage.json.lock").exists()


# ---- API endpoint tests ----


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app), proj


def test_clear_stale_endpoint_404_unknown_project(client):
    api, _ = client
    r = api.post("/api/projects/nonexistent/active-ops/clear-stale")
    assert r.status_code == 404


def test_clear_stale_endpoint_returns_count_and_details(client):
    api, proj = client
    exp = proj / "experiments" / "exp-001"
    exp.mkdir(parents=True)
    (exp / ".lock").write_text("99999999")  # dead
    (exp / ".evaluate.lock").touch()  # empty

    r = api.post("/api/projects/alpha/active-ops/clear-stale")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    paths = {entry["path"] for entry in body["cleared"]}
    assert str(exp / ".lock") in paths
    assert str(exp / ".evaluate.lock") in paths


def test_clear_stale_endpoint_empty_when_nothing_stale(client):
    api, _ = client
    r = api.post("/api/projects/alpha/active-ops/clear-stale")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["cleared"] == []


def test_clear_stale_endpoint_button_renders_in_banner(client):
    """The 'Clear stale' button only renders when the running-ops
    banner is up — drop a dead-PID lock to surface it."""
    api, proj = client
    exp = proj / "experiments" / "exp-001"
    exp.mkdir(parents=True)
    # Use the test process's PID so the banner renders, then verify
    # the button is present.
    (exp / ".lock").write_text(str(os.getpid()))

    body = api.get("/projects/alpha").text
    assert "Clear stale" in body
    assert (
        'hx-post="/api/projects/alpha/active-ops/clear-stale"' in body
    )
