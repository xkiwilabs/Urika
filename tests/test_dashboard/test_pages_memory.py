"""Tests for the dashboard's project memory page.

v0.5.0 Task 1.4 — adds an HTML ``/projects/{name}/memory`` browser page
that lists memory entries (backed by the CRUD API shipped in T1.3) and
exposes an "Add an entry" HTMX form. Also surfaces a sidebar link to
Memory between Knowledge and Methods on every per-project page.

Mirrors the ``URIKA_HOME`` monkeypatch + ``create_app(project_root=...)``
pattern from ``test_api_memory.py`` so the registry is isolated from the
real ``~/.urika``.
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


def test_memory_page_renders_entries(client_and_proj):
    client, proj = client_and_proj
    project_memory.save_entry(
        proj,
        mem_type="user",
        description="visible-entry-name",
        body="visible-body",
    )
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    # ``description`` is one of the keys ``list_entries`` returns; it
    # should land somewhere in the rendered card.
    assert "visible-entry-name" in resp.text
    assert "Memory" in resp.text  # page header text


def test_memory_page_404_for_unknown_project(client_and_proj):
    client, _proj = client_and_proj
    resp = client.get("/projects/no-such/memory")
    assert resp.status_code == 404


def test_memory_page_empty_state_when_no_entries(client_and_proj):
    client, _proj = client_and_proj
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    # Empty-state copy lives in memory.html — match the exact prefix so
    # this test cannot pass on the populated case (where "Memory" alone
    # would still appear in the sidebar / heading / breadcrumb).
    assert "No memory entries yet" in resp.text


def test_memory_page_has_add_form(client_and_proj):
    client, _proj = client_and_proj
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    # The HTMX add-entry form posts to the existing CRUD endpoint with
    # the three form fields the API accepts.
    assert 'hx-post="/api/projects/proj/memory"' in resp.text
    assert 'name="mem_type"' in resp.text
    assert 'name="description"' in resp.text
    assert 'name="body"' in resp.text


def test_memory_form_has_response_error_handler(client_and_proj):
    """HTMX does not swap response bodies for non-2xx by default — the
    form needs an ``hx-on::response-error`` handler to surface 422
    validation failures (or 5xx errors) into the feedback span instead
    of silently swallowing them.
    """
    client, _proj = client_and_proj
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    assert "hx-on::response-error" in resp.text
    assert "add-memory-feedback" in resp.text


def test_sidebar_has_memory_link(client_and_proj):
    """The per-project sidebar — rendered on every project-scoped page
    via ``_sidebar.html`` — exposes a Memory link."""
    client, _proj = client_and_proj
    # Project home renders the sidebar.
    resp = client.get("/projects/proj")
    assert resp.status_code == 200
    assert "/projects/proj/memory" in resp.text
