"""Tests for v0.4.2 H1 — vendored htmx / alpine / chart.js.

Pre-fix the dashboard loaded htmx and Alpine from unpkg.com and
Chart.js from cdn.jsdelivr.net, so any user without internet got a
non-functional UI (no HTMX swaps, no Alpine reactivity, no usage
charts). Now the assets ship under
``src/urika/dashboard/static/vendor/`` and the templates reference
``/static/vendor/...``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    return TestClient(create_app(project_root=tmp_path))


class TestVendoredFilesShipped:
    def test_htmx_file_exists(self) -> None:
        from urika.dashboard import __file__ as dashboard_init
        vendor_dir = Path(dashboard_init).parent / "static" / "vendor"
        assert (vendor_dir / "htmx-1.9.10.min.js").exists()

    def test_alpine_file_exists(self) -> None:
        from urika.dashboard import __file__ as dashboard_init
        vendor_dir = Path(dashboard_init).parent / "static" / "vendor"
        assert (vendor_dir / "alpine-3.13.5.min.js").exists()

    def test_chart_file_exists(self) -> None:
        from urika.dashboard import __file__ as dashboard_init
        vendor_dir = Path(dashboard_init).parent / "static" / "vendor"
        assert (vendor_dir / "chart-4.4.1.min.js").exists()


class TestTemplatesReferenceVendoredPaths:
    def test_base_template_uses_vendored_htmx(self, client: TestClient) -> None:
        # GET / lands on either the projects index or a redirect.
        resp = client.get("/projects")
        assert resp.status_code == 200
        # The vendored path must appear in the HTML.
        assert "/static/vendor/htmx-1.9.10.min.js" in resp.text
        # The CDN URL must NOT appear.
        assert "unpkg.com/htmx" not in resp.text

    def test_base_template_uses_vendored_alpine(self, client: TestClient) -> None:
        resp = client.get("/projects")
        assert "/static/vendor/alpine-3.13.5.min.js" in resp.text
        assert "unpkg.com/alpinejs" not in resp.text


class TestVendorEndpointServes:
    def test_vendored_htmx_servable(self, client: TestClient) -> None:
        resp = client.get("/static/vendor/htmx-1.9.10.min.js")
        assert resp.status_code == 200
        # Sanity: real htmx ships with a recognizable signature.
        assert "htmx" in resp.text.lower()

    def test_vendored_alpine_servable(self, client: TestClient) -> None:
        resp = client.get("/static/vendor/alpine-3.13.5.min.js")
        assert resp.status_code == 200

    def test_vendored_chart_servable(self, client: TestClient) -> None:
        resp = client.get("/static/vendor/chart-4.4.1.min.js")
        assert resp.status_code == 200
