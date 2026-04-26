"""Tests for DELETE /api/projects/<name>.

Mirrors the URIKA_HOME monkeypatch + create_app(project_root) pattern
used in test_api_evaluate.py. Each test redirects the registry into
``tmp_path / 'home'`` so the trash directory and projects.json are
fully isolated from the real ``~/.urika``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
def home_with_alpha(tmp_path: Path, monkeypatch):
    """Register a real project ``alpha`` under URIKA_HOME=tmp_path/home."""
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app), proj, home


def test_delete_unknown_returns_404(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    client = TestClient(create_app(project_root=tmp_path))

    r = client.delete("/api/projects/ghost")
    assert r.status_code == 404
    assert r.json()["detail"] == "Unknown project"


def test_delete_with_active_lock_returns_422(home_with_alpha):
    import os
    client, proj, _home = home_with_alpha
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    lock = exp_dir / ".lock"
    # Use the test process's PID so the lock is detected as live.
    lock.write_text(str(os.getpid()))

    r = client.delete("/api/projects/alpha")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert str(lock) in detail


def test_delete_success_returns_payload_and_unregisters(home_with_alpha):
    client, proj, home = home_with_alpha

    r = client.delete("/api/projects/alpha")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "alpha"
    assert body["registry_only"] is False
    assert isinstance(body["trash_path"], str)
    assert body["trash_path"].startswith(str(home / "trash"))

    # Original folder gone, trash dir exists.
    assert not proj.exists()
    assert Path(body["trash_path"]).exists()

    # Registry no longer lists alpha.
    registry = json.loads((home / "projects.json").read_text())
    assert "alpha" not in registry


def test_delete_missing_folder_is_registry_only(tmp_path: Path, monkeypatch):
    """Registered name pointing at a non-existent path → registry-only cleanup.

    No move happens, no trash dir is created, the registry entry is removed.
    """
    bogus = tmp_path / "alpha"  # never created
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(bogus)}))
    client = TestClient(create_app(project_root=tmp_path))

    r = client.delete("/api/projects/alpha")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "alpha"
    assert body["trash_path"] is None
    assert body["registry_only"] is True

    # Registry empty.
    registry = json.loads((home / "projects.json").read_text())
    assert registry == {}


def test_delete_hx_request_returns_hx_redirect(home_with_alpha):
    client, _proj, _home = home_with_alpha

    r = client.delete(
        "/api/projects/alpha",
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects"
