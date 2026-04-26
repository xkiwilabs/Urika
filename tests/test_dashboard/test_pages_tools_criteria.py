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
    # The humanize filter renders 'my_custom_tool' as 'My Custom Tool'
    assert "My Custom Tool" in body
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


# ── Build-tool button + log page ──────────────────────────────────────────


def test_project_tools_page_has_build_tool_button(tools_client):
    """Project Tools page renders the "+ Build tool" button + modal form
    posting to the new endpoint."""
    r = tools_client.get("/projects/alpha/tools")
    assert r.status_code == 200
    body = r.text
    assert "+ Build tool" in body
    assert "/api/projects/alpha/tools/build" in body
    # The textarea name must match what the API reads.
    assert 'name="instructions"' in body


def test_global_tools_page_has_no_build_tool_button(tools_client):
    """The global /tools page must NOT render the Build tool button —
    custom tools belong to a specific project."""
    r = tools_client.get("/tools")
    assert r.status_code == 200
    body = r.text
    assert "+ Build tool" not in body
    assert "/tools/build" not in body


def test_tool_build_log_page_returns_200(tools_client):
    r = tools_client.get("/projects/alpha/tools/build/log")
    assert r.status_code == 200
    body = r.text
    assert "EventSource" in body
    assert "/api/projects/alpha/tools/build/stream" in body
    assert 'id="log"' in body
    # Back link returns to the project Tools page, not project home.
    assert "/projects/alpha/tools" in body


def test_tool_build_log_page_404_unknown_project(tools_client):
    r = tools_client.get("/projects/nonexistent/tools/build/log")
    assert r.status_code == 404


# ── Phase B3: + Build tool button reflects running state ─────────────────

import os  # noqa: E402  — grouped near the Phase B3 tests for locality


def _drop_lock(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")


def test_project_tools_build_button_idle_opens_modal(tools_client):
    """No live tools/.build.lock → button is the idle modal-opener."""
    r = tools_client.get("/projects/alpha/tools")
    assert r.status_code == 200
    body = r.text
    assert "id: 'build-tool'" in body
    assert "Build tool running" not in body
    assert "btn--running" not in body


def test_project_tools_build_button_running_links_to_log(tools_client, tmp_path):
    """Live ``tools/.build.lock`` → button becomes a link to the
    tool-build log page."""
    _drop_lock(tmp_path / "alpha" / "tools" / ".build.lock")
    r = tools_client.get("/projects/alpha/tools")
    assert r.status_code == 200
    body = r.text
    assert 'href="/projects/alpha/tools/build/log"' in body
    assert "Build tool running" in body
    assert "btn--running" in body
    # The build-tool modal-open dispatch must be replaced by the link.
    assert "id: 'build-tool'" not in body


# ── Phase B5.2: completion CTA on tool-build log page ─────────────────────


def test_tool_build_log_has_back_to_tools_cta(tools_client):
    """The tool-build log page must surface a "Back to tools" CTA in
    the completion div — no artifact probe needed (the tool builder
    writes new files into <project>/tools/, not a single canonical
    artifact)."""
    r = tools_client.get("/projects/alpha/tools/build/log")
    assert r.status_code == 200
    body = r.text
    # The CTA targets the project Tools page.
    assert 'href="/projects/alpha/tools"' in body
    assert "Back to tools" in body
    # And the page does NOT call the artifacts probe — the CTA is static.
    assert "/api/projects/alpha/artifacts/projectbook" not in body
