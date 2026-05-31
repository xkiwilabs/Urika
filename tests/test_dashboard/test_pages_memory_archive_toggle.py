"""Tests for the dashboard memory page ``?show_archived=`` toggle.

v0.5.0 Task 3.4 — the project memory page (T1.4) lists *live* entries by
default. When the page is requested with ``?show_archived=true`` it also
loads :func:`urika.core.project_memory.list_archive` and renders the
archived entries in a separate block below the live list. A toggle link
in the page header flips the query param.

Mirrors the ``URIKA_HOME`` monkeypatch + ``create_app(project_root=...)``
pattern from ``test_pages_memory.py`` so the registry is isolated from
the real ``~/.urika``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.core import project_memory as pm
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


def _archive_second_entry(proj: Path) -> str:
    """Save two memory entries, archive the "archived-entry" one, return its
    filename. ``list_entries`` returns entries sorted alphabetically by
    filename so we look up the archived-entry candidate explicitly rather
    than relying on insertion order.
    """
    pm.save_entry(proj, mem_type="user", description="live-entry", body="b-live")
    pm.save_entry(proj, mem_type="user", description="archived-entry", body="b-archive")
    # Sorted alphabetically, so the entry with "archived" in its filename
    # may not be at index [1] — find it by description instead.
    target = next(
        e for e in pm.list_entries(proj) if e["description"] == "archived-entry"
    )
    pm.archive_entry(proj, target["filename"])
    return target["filename"]


def test_show_archived_includes_archived_entries(client_and_proj):
    client, proj = client_and_proj
    _archive_second_entry(proj)
    resp = client.get("/projects/proj/memory?show_archived=true")
    assert resp.status_code == 200
    assert "live-entry" in resp.text
    assert "archived-entry" in resp.text  # archived entry now visible


def test_default_hides_archived(client_and_proj):
    client, proj = client_and_proj
    _archive_second_entry(proj)
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    assert "live-entry" in resp.text
    assert "archived-entry" not in resp.text  # hidden by default


def test_toggle_link_present(client_and_proj):
    client, _proj = client_and_proj
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    assert "Show archived" in resp.text or "show_archived=true" in resp.text


def test_toggle_link_inverse_when_showing(client_and_proj):
    client, _proj = client_and_proj
    resp = client.get("/projects/proj/memory?show_archived=true")
    assert resp.status_code == 200
    assert "Hide archived" in resp.text or "show_archived=false" in resp.text
