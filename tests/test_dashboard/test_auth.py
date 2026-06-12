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
            f"[project]\n"
            f'name = "{name}"\n'
            f'question = "q for {name}"\n'
            f'mode = "exploratory"\n'
            f'description = ""\n'
            f"\n"
            f"[preferences]\n"
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


# ── Token via query param ──────────────────────────────────────────


def test_projects_with_query_token_returns_200(authed_client: TestClient) -> None:
    r = authed_client.get("/projects?token=secret-token")
    assert r.status_code == 200


def test_projects_with_wrong_query_token_returns_401(authed_client: TestClient) -> None:
    r = authed_client.get("/projects?token=nope")
    assert r.status_code == 401


# ── Token via cookie ───────────────────────────────────────────────


def test_projects_with_cookie_token_returns_200(authed_client: TestClient) -> None:
    authed_client.cookies.set("urika_token", "secret-token")
    r = authed_client.get("/projects")
    assert r.status_code == 200


def test_projects_with_wrong_cookie_token_returns_401(
    authed_client: TestClient,
) -> None:
    authed_client.cookies.set("urika_token", "nope")
    r = authed_client.get("/projects")
    assert r.status_code == 401


# ── Cookie set after a valid ?token= request ───────────────────────


def test_valid_query_token_sets_cookie(authed_client: TestClient) -> None:
    """A successful ?token= request sets a urika_token cookie so that
    subsequent HTMX/Alpine requests (which carry no query param) stay
    authenticated via the cookie."""
    # Disable redirect-following and cookie persistence to inspect the
    # raw Set-Cookie on the first hop.
    r = authed_client.get("/projects?token=secret-token")
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "urika_token=secret-token" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()


def test_no_cookie_set_on_wrong_query_token(authed_client: TestClient) -> None:
    """A failed token must NOT set the cookie."""
    r = authed_client.get("/projects?token=nope")
    assert r.status_code == 401
    assert "urika_token" not in r.headers.get("set-cookie", "")


# ── Friendly HTML 401 for top-level browser navigations ────────────


def test_browser_nav_401_returns_friendly_html(authed_client: TestClient) -> None:
    """A top-level browser navigation (Accept: text/html) to a 401 gets a
    readable HTML page, not the raw JSON error blob."""
    r = authed_client.get("/projects", headers={"Accept": "text/html"})
    assert r.status_code == 401
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text.lower()
    assert "access token" in body
    # Not the raw JSON contract.
    assert '{"detail"' not in r.text


def test_json_client_401_still_returns_json(authed_client: TestClient) -> None:
    """A programmatic client (Accept: application/json) keeps the JSON
    contract on a 401."""
    r = authed_client.get("/projects", headers={"Accept": "application/json"})
    assert r.status_code == 401
    assert r.json() == {"detail": "Invalid or missing token"}


def test_htmx_request_401_returns_json_not_html(authed_client: TestClient) -> None:
    """An HTMX XHR (HX-Request: true) must get JSON even though it sends
    Accept: text/html — otherwise a full HTML doc would be swapped into
    the DOM on an auth failure."""
    r = authed_client.get(
        "/projects",
        headers={"Accept": "text/html", "HX-Request": "true"},
    )
    assert r.status_code == 401
    assert r.json() == {"detail": "Invalid or missing token"}


def test_browser_nav_404_still_returns_json(authed_client: TestClient) -> None:
    """The handler only special-cases 401. A 404 with Accept: text/html
    still returns JSON (the default FastAPI contract)."""
    r = authed_client.get(
        "/no-such-route",
        headers={"Accept": "text/html", "Authorization": "Bearer secret-token"},
    )
    assert r.status_code == 404
    # Still the JSON shape, not the friendly HTML page.
    assert "application/json" in r.headers.get("content-type", "")


def test_browser_nav_with_valid_token_returns_real_page(
    authed_client: TestClient,
) -> None:
    """Regression: a valid token + Accept: text/html returns the real
    page, not the 401 fallback."""
    r = authed_client.get(
        "/projects",
        headers={"Accept": "text/html", "Authorization": "Bearer secret-token"},
    )
    assert r.status_code == 200
    assert "access token required" not in r.text.lower()
