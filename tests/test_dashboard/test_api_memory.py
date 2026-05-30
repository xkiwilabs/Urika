"""Tests for the dashboard's memory CRUD API endpoints.

v0.5.0 Task 1.3 — adds GET list, GET single, POST upsert, DELETE
endpoints under ``/api/projects/{name}/memory`` so the dashboard's
memory page can read/write project memory entries.

Mirrors the URIKA_HOME monkeypatch + ``create_app(project_root=...)``
pattern used in ``test_api_delete_project.py`` so the registry is
isolated from the real ``~/.urika``.

All state-changing requests carry ``Origin: http://testserver`` to
satisfy the v0.4.5.1 CSRF origin guard. Cross-origin POSTs are tested
elsewhere (``test_csrf_origin.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.core import project_memory
from urika.dashboard.app import create_app


def _make_project(tmp_path: Path, name: str = "proj") -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    return proj


@pytest.fixture
def client_and_proj(tmp_path: Path, monkeypatch):
    """Register a real project ``proj`` under URIKA_HOME=tmp_path/home
    and return ``(TestClient, project_dir)``."""
    proj = _make_project(tmp_path, "proj")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"proj": str(proj)}))
    app = create_app(project_root=tmp_path, auth_token=None)
    return TestClient(app), proj


def _seed(proj_dir: Path) -> str:
    """Create one memory entry. Returns its filename."""
    path = project_memory.save_entry(
        proj_dir,
        mem_type="user",
        description="t1",
        body="b1",
    )
    return path.name


# ────────────────────────── GET list ────────────────────────────


def test_list_returns_entries(client_and_proj):
    client, proj = client_and_proj
    fname = _seed(proj)
    resp = client.get("/api/projects/proj/memory")
    assert resp.status_code == 200
    body = resp.json()
    # Endpoint shape: {"entries": [...]} mirrors the CLI's --json shape.
    assert "entries" in body
    entries = body["entries"]
    assert len(entries) == 1
    e = entries[0]
    # Real keys per ``list_entries``: filename, type, name, description,
    # body_preview.
    assert e["filename"] == fname
    assert e["type"] == "user"
    assert e["description"] == "t1"
    assert "body_preview" in e


def test_list_empty_when_no_memory_dir(client_and_proj):
    client, _proj = client_and_proj
    resp = client.get("/api/projects/proj/memory")
    assert resp.status_code == 200
    assert resp.json() == {"entries": []}


# ────────────────────────── GET single ──────────────────────────


def test_get_single_returns_frontmatter_and_body(client_and_proj):
    client, proj = client_and_proj
    fname = _seed(proj)
    resp = client.get(f"/api/projects/proj/memory/{fname}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["body"].strip() == "b1"
    assert isinstance(data["frontmatter"], dict)
    fm = data["frontmatter"]
    assert fm["type"] == "user"
    assert fm["description"] == "t1"
    assert "name" in fm
    assert data["filename"] == fname


def test_get_single_missing_returns_404(client_and_proj):
    client, _proj = client_and_proj
    resp = client.get("/api/projects/proj/memory/user_does_not_exist.md")
    assert resp.status_code == 404


# ────────────────────────── POST upsert ─────────────────────────


def test_post_upsert_creates_entry(client_and_proj):
    client, proj = client_and_proj
    resp = client.post(
        "/api/projects/proj/memory",
        data={"mem_type": "user", "description": "new", "body": "novel content"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code in (200, 201)
    entries = project_memory.list_entries(proj)
    assert any(e["description"] == "new" for e in entries)
    # Index rebuilt as part of save_entry.
    index = (proj / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert "new" in index


def test_post_upsert_hx_request_returns_redirect(client_and_proj):
    """When the dashboard's HTMX form POSTs (``HX-Request: true``),
    the endpoint should return 204 + ``HX-Redirect`` back to the memory
    page rather than the JSON body, so HTMX reloads the list instead
    of injecting raw JSON into the feedback span.
    """
    client, proj = client_and_proj
    resp = client.post(
        "/api/projects/proj/memory",
        data={"mem_type": "user", "description": "hx-new", "body": "hx-body"},
        headers={"Origin": "http://testserver", "HX-Request": "true"},
    )
    assert resp.status_code == 204
    assert resp.headers.get("HX-Redirect") == "/projects/proj/memory"
    # Entry still got saved.
    entries = project_memory.list_entries(proj)
    assert any(e["description"] == "hx-new" for e in entries)


def test_post_upsert_rejects_unknown_mem_type(client_and_proj):
    client, _proj = client_and_proj
    resp = client.post(
        "/api/projects/proj/memory",
        data={"mem_type": "bogus", "description": "x", "body": "y"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 422


def test_post_upsert_requires_body(client_and_proj):
    client, _proj = client_and_proj
    resp = client.post(
        "/api/projects/proj/memory",
        data={"mem_type": "user", "description": "x", "body": ""},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 422


# ────────────────────────── DELETE ──────────────────────────────


def test_delete_trashes_entry(client_and_proj):
    client, proj = client_and_proj
    fname = _seed(proj)
    resp = client.delete(
        f"/api/projects/proj/memory/{fname}",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code in (200, 204)
    remaining = project_memory.list_entries(proj)
    assert not any(e["filename"] == fname for e in remaining)
    assert (proj / "memory" / ".trash" / fname).exists()


def test_delete_missing_returns_404(client_and_proj):
    client, _proj = client_and_proj
    resp = client.delete(
        "/api/projects/proj/memory/user_nothing.md",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 404


# ────────────────────────── 404 + traversal ─────────────────────


def test_unknown_project_returns_404(client_and_proj):
    client, _proj = client_and_proj
    resp = client.get("/api/projects/nope/memory")
    assert resp.status_code == 404


def test_filename_traversal_rejected_get(client_and_proj):
    client, proj = client_and_proj
    _seed(proj)
    # Even URL-encoded, the path-segment validator should reject ``..``.
    resp = client.get("/api/projects/proj/memory/..%2Fevil")
    assert resp.status_code in (400, 404)


def test_filename_traversal_rejected_delete(client_and_proj):
    client, proj = client_and_proj
    _seed(proj)
    resp = client.delete(
        "/api/projects/proj/memory/..%2Fevil",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code in (400, 404)


def test_filename_with_backslash_rejected(client_and_proj):
    client, proj = client_and_proj
    _seed(proj)
    resp = client.get("/api/projects/proj/memory/foo%5Cbar")
    assert resp.status_code in (400, 404)
