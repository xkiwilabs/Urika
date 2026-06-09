"""Tests for the cross-origin (CSRF) Origin-guard middleware.

The dashboard runs on a predictable localhost origin, so a malicious
web page could issue cross-origin form POSTs to launch runs, write
secrets, or delete projects. The Origin guard rejects state-changing
requests (non-GET/HEAD/OPTIONS) whose ``Origin`` header netloc differs
from the request ``Host``. Requests with no ``Origin`` header are
allowed (curl / server-side / same-origin navigations omit it; browsers
always send Origin on cross-origin state-changing requests).

The guard is defense-in-depth and applies in BOTH authenticated and
unauthenticated modes, so these tests use ``auth_token=None``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from urika.dashboard.app import create_app

# A real mutating route on the API router (prefix ``/api``).
_MUTATING_ROUTE = "/api/secrets"


def _client(tmp_project_dir: Path) -> TestClient:
    app = create_app(project_root=tmp_project_dir, auth_token=None)
    return TestClient(app)


def test_cross_origin_post_rejected(tmp_project_dir: Path) -> None:
    """A POST carrying a foreign Origin is rejected with 403."""
    client = _client(tmp_project_dir)
    r = client.post(
        _MUTATING_ROUTE,
        headers={"Origin": "http://evil.example"},
        data={"name": "FOO", "value": "bar"},
    )
    assert r.status_code == 403


def test_same_origin_post_allowed(tmp_project_dir: Path) -> None:
    """A POST whose Origin matches the request Host is not blocked by the
    guard. TestClient uses ``testserver`` as its host, so an Origin of
    ``http://testserver`` is same-origin. The route may 4xx/2xx for other
    reasons, but it must not be the 403 from the guard."""
    client = _client(tmp_project_dir)
    r = client.post(
        _MUTATING_ROUTE,
        headers={"Origin": "http://testserver"},
        data={"name": "FOO", "value": "bar"},
    )
    assert r.status_code != 403


def test_origin_guard_case_insensitive_host(tmp_project_dir: Path) -> None:
    """Hostnames are case-insensitive (RFC 3986 §3.2.2) — an Origin of
    ``http://TESTSERVER`` against a ``Host: testserver`` request is
    same-origin and must NOT be rejected with 403."""
    client = _client(tmp_project_dir)
    r = client.post(
        _MUTATING_ROUTE,
        headers={"Origin": "http://TESTSERVER"},
        data={"name": "FOO", "value": "bar"},
    )
    assert r.status_code != 403


def test_post_without_origin_allowed(tmp_project_dir: Path) -> None:
    """A POST with no Origin header passes the guard (curl/server-side)."""
    client = _client(tmp_project_dir)
    r = client.post(_MUTATING_ROUTE, data={"name": "FOO", "value": "bar"})
    assert r.status_code != 403


def test_get_with_foreign_origin_allowed(tmp_project_dir: Path) -> None:
    """A safe-method GET with a foreign Origin is never blocked."""
    client = _client(tmp_project_dir)
    r = client.get("/api/projects", headers={"Origin": "http://evil.example"})
    assert r.status_code != 403
