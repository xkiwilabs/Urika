"""Tests for the dashboard memory archive + diff pages (cross-surface parity).

The CLI exposes ``urika memory archive`` and ``urika memory diff``. This
test module pins the equivalent dashboard pages:

  * ``GET /projects/{name}/memory/archive`` — lists archived snapshots,
    optionally filtered by ``?month=YYYY-MM``.
  * ``GET /projects/{name}/memory/diff?from=<ts>&to=<ts>`` — shows
    added / archived / trashed entries in the window.

Both pages back onto :func:`urika.core.project_memory.list_archive` and
:func:`urika.core.project_memory.diff_between` respectively — the same
helpers the CLI calls. The memory page (``memory.html``) carries
navigation links to both.
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
    proj = _make_project(tmp_path, "proj")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"proj": str(proj)}))
    app = create_app(project_root=tmp_path, auth_token=None)
    return TestClient(app), proj


# ---------------------------------------------------------------------------
# Archive page.
# ---------------------------------------------------------------------------


def test_archive_page_renders_archived_entries(client_and_proj):
    client, proj = client_and_proj
    pm.save_entry(proj, mem_type="user", description="my-archived-thing", body="b")
    target = next(
        e for e in pm.list_entries(proj) if e["description"] == "my-archived-thing"
    )
    pm.archive_entry(proj, target["filename"])

    resp = client.get("/projects/proj/memory/archive")
    assert resp.status_code == 200
    body = resp.text
    # The archive page should surface the archived entry's description.
    assert "my-archived-thing" in body


def test_archive_page_empty_state(client_and_proj):
    client, _proj = client_and_proj
    resp = client.get("/projects/proj/memory/archive")
    assert resp.status_code == 200
    # Empty-state copy: must be distinguishable from a populated page.
    assert "No archived entries" in resp.text


def test_archive_page_404_for_unknown_project(client_and_proj):
    client, _proj = client_and_proj
    resp = client.get("/projects/no-such/memory/archive")
    assert resp.status_code == 404


def test_archive_page_month_filter(client_and_proj):
    """Passing ``?month=2099-01`` filters to a non-existent month —
    should show the empty-state."""
    client, proj = client_and_proj
    # Create + archive an entry. It'll go under archive/<current YYYY-MM>/.
    pm.save_entry(proj, mem_type="user", description="entry-x", body="b")
    target = next(e for e in pm.list_entries(proj) if e["description"] == "entry-x")
    pm.archive_entry(proj, target["filename"])

    # Filter to a known-empty month.
    resp = client.get("/projects/proj/memory/archive?month=2099-01")
    assert resp.status_code == 200
    # The archived entry should NOT appear under the bogus month filter.
    assert "entry-x" not in resp.text


def test_memory_page_links_to_archive(client_and_proj):
    """The main memory page must link to the archive page so users can
    discover it without typing the URL."""
    client, _proj = client_and_proj
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    assert "/projects/proj/memory/archive" in resp.text


# ---------------------------------------------------------------------------
# Diff page.
# ---------------------------------------------------------------------------


def test_diff_page_renders_for_window(client_and_proj):
    """Submitting a from/to window should produce a page with the
    classification headers (added / archived / trashed)."""
    client, proj = client_and_proj
    pm.save_entry(proj, mem_type="user", description="recent-thing", body="b")
    resp = client.get(
        "/projects/proj/memory/diff?from_ts=1w_ago&to_ts=now",
    )
    assert resp.status_code == 200
    # The diff page renders the three section labels regardless of
    # whether any group is non-empty (CLI does the same).
    body = resp.text.lower()
    assert "added" in body
    assert "archived" in body
    assert "trashed" in body


def test_diff_page_added_contains_recent_entry(client_and_proj):
    """A live entry added in the diff window should appear under
    ``added``."""
    client, proj = client_and_proj
    pm.save_entry(proj, mem_type="user", description="just-now", body="b")
    resp = client.get(
        "/projects/proj/memory/diff?from_ts=1h_ago&to_ts=now",
    )
    assert resp.status_code == 200
    # The CLI's diff shows just the filename, so we look for the entry's
    # filename prefix (descriptions get slugified into filenames).
    rows = pm.list_entries(proj)
    target = next(r for r in rows if r["description"] == "just-now")
    assert target["filename"] in resp.text


def test_diff_page_bad_timestamp_returns_422(client_and_proj):
    """Garbage ``from_ts`` should fail validation cleanly."""
    client, _proj = client_and_proj
    resp = client.get(
        "/projects/proj/memory/diff?from_ts=fishpaste&to_ts=now",
    )
    assert resp.status_code == 422


def test_diff_page_404_for_unknown_project(client_and_proj):
    client, _proj = client_and_proj
    resp = client.get(
        "/projects/no-such/memory/diff?from_ts=1d_ago&to_ts=now",
    )
    assert resp.status_code == 404


def test_memory_page_links_to_diff(client_and_proj):
    """The main memory page must link to the diff page."""
    client, _proj = client_and_proj
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    assert "/projects/proj/memory/diff" in resp.text
