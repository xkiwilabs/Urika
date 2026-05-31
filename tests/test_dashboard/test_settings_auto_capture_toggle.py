"""Tests for the dashboard per-project ``[memory] auto_capture`` toggle.

v0.5.0 Task 3.5 — the project memory page exposes a checkbox that POSTs
to ``/api/projects/{name}/memory/auto_capture`` to flip the project's
``[memory] auto_capture`` flag in ``urika.toml``. The CRUD helper
:func:`urika.core.project_memory.is_enabled` already READS the flag; the
new endpoint WRITES it via :func:`urika.core.workspace._write_toml`.

Mirrors the ``URIKA_HOME`` monkeypatch + ``create_app(project_root=...)``
pattern from ``test_pages_memory.py`` so the registry is isolated from
the real ``~/.urika``.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _register(tmp_path: Path, monkeypatch, name: str, toml_text: str) -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(toml_text)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({name: str(proj)}))
    return proj


@pytest.fixture
def client_factory(tmp_path: Path, monkeypatch):
    """Return ``(make_client, tmp_path)`` where ``make_client(name, toml)``
    registers a project and returns a TestClient bound to ``tmp_path``."""

    def _make(name: str, toml_text: str) -> tuple[TestClient, Path]:
        proj = _register(tmp_path, monkeypatch, name, toml_text)
        app = create_app(project_root=tmp_path, auth_token=None)
        return TestClient(app), proj

    return _make, tmp_path


def test_auto_capture_toggle_writes_urika_toml(client_factory):
    make, _ = client_factory
    client, proj = make(
        "proj", '[project]\nname = "proj"\nquestion = "q"\nmode = "exploratory"\n'
    )
    resp = client.post(
        "/api/projects/proj/memory/auto_capture",
        data={"enabled": "false"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    data = tomllib.loads((proj / "urika.toml").read_text())
    assert data["memory"]["auto_capture"] is False


def test_auto_capture_toggle_enables(client_factory):
    make, _ = client_factory
    client, proj = make(
        "proj",
        '[project]\nname = "proj"\nquestion = "q"\nmode = "exploratory"\n'
        "[memory]\nauto_capture = false\n",
    )
    resp = client.post(
        "/api/projects/proj/memory/auto_capture",
        data={"enabled": "true"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    data = tomllib.loads((proj / "urika.toml").read_text())
    assert data["memory"]["auto_capture"] is True


def test_auto_capture_toggle_404_unknown_project(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    app = create_app(project_root=tmp_path, auth_token=None)
    client = TestClient(app)
    resp = client.post(
        "/api/projects/nope/memory/auto_capture",
        data={"enabled": "true"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 404


def test_auto_capture_toggle_cross_origin_rejected(client_factory):
    make, _ = client_factory
    client, _proj = make(
        "proj", '[project]\nname = "proj"\nquestion = "q"\nmode = "exploratory"\n'
    )
    resp = client.post(
        "/api/projects/proj/memory/auto_capture",
        data={"enabled": "true"},
        headers={"Origin": "http://evil.example"},
    )
    assert resp.status_code == 403


def test_memory_page_has_auto_capture_checkbox(client_factory):
    make, _ = client_factory
    client, _proj = make(
        "proj", '[project]\nname = "proj"\nquestion = "q"\nmode = "exploratory"\n'
    )
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    assert "auto_capture" in resp.text or "Auto-capture" in resp.text
    assert "/memory/auto_capture" in resp.text
