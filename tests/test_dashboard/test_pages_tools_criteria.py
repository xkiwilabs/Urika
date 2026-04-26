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


def test_global_tools_page_lists_built_in_tools(tools_client):
    """GET /tools shows the built-in (global) tool set."""
    r = tools_client.get("/tools")
    assert r.status_code == 200
    body = r.text
    # At least one well-known built-in should appear
    assert "regression" in body.lower() or "anova" in body.lower() or "Linear" in body
    assert "Built-in tools" in body


def test_project_tools_page_excludes_built_ins(tools_client):
    """Project /tools shows ONLY custom <project>/tools/*.py — not built-ins."""
    r = tools_client.get("/projects/alpha/tools")
    assert r.status_code == 200
    body = r.text
    # No tools/ dir → empty state, NOT the global tool list
    assert "No custom tools yet" in body
    # Heading distinguishes from the global page
    assert "Custom tools" in body


def test_project_tools_page_lists_project_local_tool(tools_client, tmp_path):
    """A custom <project>/tools/foo.py shows up on the project Tools page."""
    proj_tools = tmp_path / "alpha" / "tools"
    proj_tools.mkdir(parents=True, exist_ok=True)
    (proj_tools / "my_custom_tool.py").write_text(
        "from urika.tools.base import ITool\n"
        "class _T(ITool):\n"
        "    def name(self): return 'my_custom_tool'\n"
        "    def description(self): return 'custom for this project'\n"
        "    def category(self): return 'custom'\n"
        "    def default_params(self): return {}\n"
        "    def run(self, *a, **k): return None\n"
        "def get_tool(): return _T()\n"
    )
    r = tools_client.get("/projects/alpha/tools")
    body = r.text
    assert "my_custom_tool" in body or "My custom tool" in body
    assert "custom for this project" in body


def test_project_tools_page_404_unknown_project(tools_client):
    r = tools_client.get("/projects/nonexistent/tools")
    assert r.status_code == 404


def test_global_tools_link_in_sidebar(tools_client):
    """Outside a project the sidebar shows Projects + Tools + Settings."""
    r = tools_client.get("/projects")
    body = r.text
    import re
    sidebar = re.search(
        r'<aside class="sidebar"[^>]*>(.*?)</aside>', body, re.DOTALL
    ).group(1)
    assert 'href="/tools"' in sidebar
    assert 'href="/projects"' in sidebar
    assert 'href="/settings"' in sidebar


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


def test_sidebar_includes_tools_link(tools_client):
    r = tools_client.get("/projects/alpha")
    body = r.text
    assert "/projects/alpha/tools" in body


def test_sidebar_omits_criteria_and_run_links(tools_client):
    """Criteria and Run links were removed — Run is a button on
    /experiments and Criteria is reachable from project settings."""
    r = tools_client.get("/projects/alpha")
    body = r.text
    # The sidebar no longer renders direct links to /criteria or /run.
    assert 'href="/projects/alpha/criteria"' not in body
    assert 'href="/projects/alpha/run"' not in body
