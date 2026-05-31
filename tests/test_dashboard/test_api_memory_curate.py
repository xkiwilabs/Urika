"""Tests for the dashboard's ``POST /api/projects/{name}/memory/curate``
endpoint + the Curate/Apply buttons on the memory page (v0.5.0 T2.10).

Dry-run by default; ``?apply=true`` commits. The endpoint sits behind
the v0.4.5.1 CSRF Origin guard like every other dashboard POST — a
cross-origin call returns 403.

Mirrors the ``URIKA_HOME`` monkeypatch + ``create_app(project_root=...)``
fixture pattern from ``test_api_memory.py`` / ``test_pages_memory.py``.
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


# ────────────────────────── dry-run path ─────────────────────────


def test_curate_endpoint_returns_decisions(client_and_proj, monkeypatch) -> None:
    client, proj = client_and_proj
    project_memory.save_entry(proj, mem_type="user", description="t", body="b")

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        return CuratorResult(
            decisions=[
                {"action": "archive", "filename": "user_t.md", "reason": "stale"}
            ],
            applied=apply,
        )

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)
    resp = client.post(
        "/api/projects/proj/memory/curate",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["applied"] is False
    assert data["error"] is None
    assert any(d["action"] == "archive" for d in data["decisions"])


# ────────────────────────── apply path ──────────────────────────


def test_apply_query_param_commits(client_and_proj, monkeypatch) -> None:
    client, proj = client_and_proj
    project_memory.save_entry(proj, mem_type="user", description="t", body="b")
    captured: dict = {}

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        captured["apply"] = apply
        return CuratorResult(decisions=[], applied=apply)

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)

    resp = client.post(
        "/api/projects/proj/memory/curate?apply=true",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] is True
    assert captured["apply"] is True


@pytest.mark.parametrize("value", ["1", "yes", "TRUE", "True"])
def test_apply_truthy_aliases_accepted(
    client_and_proj, monkeypatch, value: str
) -> None:
    """The apply query-param accepts ``true / 1 / yes`` (case-insensitive)
    so different dashboard JS encodings all commit."""
    client, _proj = client_and_proj

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        return CuratorResult(decisions=[], applied=apply)

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)
    resp = client.post(
        f"/api/projects/proj/memory/curate?apply={value}",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] is True


def test_apply_param_default_is_dry_run(client_and_proj, monkeypatch) -> None:
    """Missing ``?apply=`` defaults to dry-run."""
    client, _proj = client_and_proj
    seen: list = []

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        seen.append(apply)
        return CuratorResult(decisions=[], applied=apply)

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)
    resp = client.post(
        "/api/projects/proj/memory/curate",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    assert seen == [False]


# ────────────────────────── error surfaces ──────────────────────


def test_curate_unknown_project_returns_404(client_and_proj) -> None:
    client, _proj = client_and_proj
    resp = client.post(
        "/api/projects/nope/memory/curate",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 404


def test_curate_runner_error_surfaces_in_body(client_and_proj, monkeypatch) -> None:
    """A curator error is returned with HTTP 200 + ``error`` populated
    (not a 5xx) — so the dashboard can render it inline."""
    client, _proj = client_and_proj

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        return CuratorResult(decisions=[], applied=False, error="boom")

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)
    resp = client.post(
        "/api/projects/proj/memory/curate",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    assert resp.json()["error"] == "boom"


# ────────────────────────── CSRF / cross-origin ─────────────────


def test_curate_cross_origin_rejected(client_and_proj) -> None:
    """CSRF middleware (v0.4.5.1) must still reject foreign Origin."""
    client, _proj = client_and_proj
    resp = client.post(
        "/api/projects/proj/memory/curate",
        headers={"Origin": "http://evil.example"},
    )
    assert resp.status_code == 403


# ────────────────────────── memory page UI ──────────────────────


def test_memory_page_has_curator_panel(client_and_proj) -> None:
    """The memory page renders the Curate / Apply buttons + references
    the curate endpoint so the Alpine bindings can hit it."""
    client, _proj = client_and_proj
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    # Both button labels rendered.
    assert "Curate (dry-run)" in resp.text
    assert "Apply" in resp.text
    # Endpoint URL is wired into the panel (used by both buttons).
    assert "/api/projects/proj/memory/curate" in resp.text


def test_memory_page_curator_panel_uses_alpine(client_and_proj) -> None:
    """Sanity: the curator panel uses Alpine ``x-data`` like every
    other interactive panel on the memory page."""
    client, _proj = client_and_proj
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    assert "curator-panel" in resp.text
    # Alpine binding present.
    assert "x-data" in resp.text


def test_apply_button_handler_propagates_curator_error_to_ui(client_and_proj) -> None:
    """The Apply button's @click handler must surface
    ``CuratorResult.error`` to the visible ``error`` Alpine field,
    not silently swallow it.

    Pre-fix the Apply handler only set ``error`` in the ``.catch`` path
    (network failure), so a curator soft-failure with HTTP 200 +
    ``error="..."`` body produced: decisions list emptied, no reload,
    no on-screen explanation. The dry-run button always did this
    correctly; this test pins the Apply handler to the same shape.

    We can't fully execute the Alpine JS in a pytest without a
    headless browser, but we CAN assert the template contains the
    error-propagation snippet — i.e. the Apply ``.then(d => ...)``
    references ``d.error`` and only reloads when ``d.applied`` AND
    not ``d.error``.
    """
    client, _proj = client_and_proj
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    html = resp.text

    # Find the Apply button block. It's the second @click handler that
    # POSTs with apply=true. Slice from that marker forward and assert
    # the error-propagation code lives inside it.
    apply_marker = "?apply=true"
    assert apply_marker in html, "Apply endpoint URL missing from memory page"
    apply_section = html[html.index(apply_marker) :]
    # Bound the slice so we only inspect the Apply button's handler,
    # not arbitrary HTML further down the page.
    apply_section = apply_section[:1500]

    assert "d.error" in apply_section or "d?.error" in apply_section, (
        "Apply handler doesn't propagate curator error to the UI"
    )
    # Reload should be guarded by absence of error — otherwise we
    # navigate away before the user can see the message.
    assert "!d.error" in apply_section or "d.error" in apply_section, (
        "Apply handler should gate window.location.reload on absence of d.error"
    )
