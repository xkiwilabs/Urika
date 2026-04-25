"""Tests for tools listing + criteria viewer pages — Task 11E.4."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def tools_client(tmp_path: Path, monkeypatch) -> TestClient:
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\nsuccess_criteria = { rmse_max = 0.5 }\n\n'
        '[preferences]\naudience = "expert"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_tools_page_lists_built_in_tools(tools_client):
    r = tools_client.get("/projects/alpha/tools")
    assert r.status_code == 200
    body = r.text
    # Built-in tools registered via auto-discovery
    # At least one of the well-known built-ins should appear
    assert "regression" in body.lower() or "anova" in body.lower() or "Linear" in body


def test_tools_page_404_unknown_project(tools_client):
    r = tools_client.get("/projects/nonexistent/tools")
    assert r.status_code == 404


def test_criteria_page_renders_set_criteria(tools_client):
    r = tools_client.get("/projects/alpha/criteria")
    assert r.status_code == 200
    body = r.text
    assert "rmse_max" in body or "Rmse Max" in body  # humanized OR raw
    assert "0.5" in body


def test_criteria_page_empty_state(tmp_path, monkeypatch):
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    r = client.get("/projects/alpha/criteria")
    assert r.status_code == 200
    assert "No success criteria" in r.text


def test_criteria_page_404_unknown_project(tools_client):
    r = tools_client.get("/projects/nonexistent/criteria")
    assert r.status_code == 404


def test_sidebar_includes_tools_and_criteria_links(tools_client):
    r = tools_client.get("/projects/alpha")
    body = r.text
    assert "/projects/alpha/tools" in body
    assert "/projects/alpha/criteria" in body
