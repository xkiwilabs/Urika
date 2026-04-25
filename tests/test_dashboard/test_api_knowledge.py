"""Tests for POST /api/projects/<n>/knowledge — Task 11E.3."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def kn_client(tmp_path: Path, monkeypatch):
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app), proj


def test_knowledge_add_with_text_file(kn_client, tmp_path):
    client, proj = kn_client
    txt = tmp_path / "note.md"
    txt.write_text("# A note\n\nbody")
    r = client.post("/api/projects/alpha/knowledge", data={"source": str(txt)})
    assert r.status_code == 201
    body = r.json()
    assert "id" in body
    # Index file written
    assert (proj / "knowledge" / "index.json").exists()


def test_knowledge_add_returns_hx_redirect(kn_client, tmp_path):
    client, _ = kn_client
    txt = tmp_path / "x.md"
    txt.write_text("body")
    r = client.post(
        "/api/projects/alpha/knowledge",
        headers={"hx-request": "true"},
        data={"source": str(txt)},
    )
    assert r.status_code == 201
    assert r.headers["hx-redirect"] == "/projects/alpha/knowledge"


def test_knowledge_add_404_unknown_project(kn_client, tmp_path):
    client, _ = kn_client
    r = client.post(
        "/api/projects/nonexistent/knowledge",
        data={"source": "/tmp/x.md"},
    )
    assert r.status_code == 404


def test_knowledge_add_422_missing_source(kn_client):
    client, _ = kn_client
    r = client.post("/api/projects/alpha/knowledge", data={"source": ""})
    assert r.status_code == 422
