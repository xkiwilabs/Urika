"""Tests for the optional Bearer-token auth on the dashboard.

When ``create_app(..., auth_token="abc")`` is called, every page and
API route requires ``Authorization: Bearer abc``. ``/healthz`` and
``/static/...`` remain accessible without the header.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def authed_client(tmp_path: Path, monkeypatch) -> TestClient:
    """Dashboard configured with auth_token='secret-token' and a tmp registry."""
    # Two fabricated projects so /projects has something to enumerate.
    for name in ("alpha", "beta"):
        proj = tmp_path / name
        proj.mkdir()
        (proj / "urika.toml").write_text(
            f'[project]\n'
            f'name = "{name}"\n'
            f'question = "q for {name}"\n'
            f'mode = "exploratory"\n'
            f'description = ""\n'
            f'\n'
            f'[preferences]\n'
            f'audience = "expert"\n'
        )

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(
        json.dumps(
            {
                "alpha": str(tmp_path / "alpha"),
                "beta": str(tmp_path / "beta"),
            }
        )
    )

    app = create_app(project_root=tmp_path, auth_token="secret-token")
    return TestClient(app)


def test_projects_without_token_returns_401(authed_client: TestClient) -> None:
    r = authed_client.get("/projects")
    assert r.status_code == 401


def test_projects_with_correct_token_returns_200(authed_client: TestClient) -> None:
    r = authed_client.get(
        "/projects",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert r.status_code == 200


def test_projects_with_wrong_token_returns_401(authed_client: TestClient) -> None:
    r = authed_client.get(
        "/projects",
        headers={"Authorization": "Bearer not-the-token"},
    )
    assert r.status_code == 401


def test_projects_with_wrong_scheme_returns_401(authed_client: TestClient) -> None:
    r = authed_client.get(
        "/projects",
        headers={"Authorization": "Basic secret-token"},
    )
    assert r.status_code == 401


def test_healthz_works_without_token(authed_client: TestClient) -> None:
    r = authed_client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_static_app_css_works_without_token(authed_client: TestClient) -> None:
    r = authed_client.get("/static/app.css")
    assert r.status_code == 200
    # We only care that the static mount bypasses auth; content is opaque.
    assert "text/css" in r.headers.get("content-type", "")


def test_api_route_requires_token(authed_client: TestClient) -> None:
    """A representative API route is also protected."""
    # /api/projects is a JSON list endpoint. Without the header it 401s.
    r = authed_client.get("/api/projects")
    assert r.status_code == 401

    r = authed_client.get(
        "/api/projects",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert r.status_code == 200


def test_no_auth_token_allows_anonymous_requests(tmp_path: Path) -> None:
    """create_app without auth_token (default) permits every request."""
    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    # /healthz works (already covered by the skeleton test, but cheap).
    assert client.get("/healthz").status_code == 200
    # /projects works (no projects → empty list, but the route renders).
    assert client.get("/projects").status_code == 200
