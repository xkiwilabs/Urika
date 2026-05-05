"""Tests for v0.4.2 H2 — Compare + Criteria sidebar links.

Pre-fix ``experiment_compare.html`` and ``criteria.html`` rendered
correctly and the routes were registered, but ``_sidebar.html`` had
no link to either — both pages were reachable only via deeplink.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def client_with_project(tmp_path: Path, monkeypatch) -> TestClient:
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\n'
        'name = "alpha"\n'
        'question = "q"\n'
        'mode = "exploratory"\n'
        'description = ""\n'
        '\n'
        '[preferences]\n'
        'audience = "expert"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    return TestClient(create_app(project_root=tmp_path))


class TestSidebarLinks:
    def test_compare_link_in_sidebar(self, client_with_project: TestClient) -> None:
        resp = client_with_project.get("/projects/alpha")
        assert resp.status_code == 200
        # The href must point at the compare page.
        assert "/projects/alpha/compare" in resp.text, (
            "Pre-v0.4.2 the Compare page existed but had no nav link — "
            "users could only reach it by deeplink."
        )

    def test_criteria_link_in_sidebar(self, client_with_project: TestClient) -> None:
        resp = client_with_project.get("/projects/alpha")
        assert resp.status_code == 200
        assert "/projects/alpha/criteria" in resp.text

    def test_compare_route_returns_200(self, client_with_project: TestClient) -> None:
        # Sanity: the route the new link points to actually responds.
        resp = client_with_project.get("/projects/alpha/compare")
        assert resp.status_code == 200

    def test_criteria_route_returns_200(self, client_with_project: TestClient) -> None:
        resp = client_with_project.get("/projects/alpha/criteria")
        assert resp.status_code == 200
