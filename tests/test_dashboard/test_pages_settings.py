"""Tests for project settings (read) page."""

from __future__ import annotations


def test_project_settings_returns_200_and_renders_form(client_with_projects):
    r = client_with_projects.get("/projects/alpha/settings")
    assert r.status_code == 200
    body = r.text
    # Form fields with the right name attributes
    assert 'name="question"' in body
    assert 'name="description"' in body
    assert 'name="mode"' in body
    assert 'name="audience"' in body
    # HTMX directive on the form
    assert 'hx-put="/api/projects/alpha/settings"' in body
    # Current mode is selected
    assert "exploratory" in body


def test_project_settings_404_unknown_project(client_with_projects):
    r = client_with_projects.get("/projects/nonexistent/settings")
    assert r.status_code == 404


def test_project_settings_shows_all_valid_modes(client_with_projects):
    r = client_with_projects.get("/projects/alpha/settings")
    body = r.text
    for mode in ("exploratory", "confirmatory", "pipeline"):
        assert mode in body


# ---- 5-tab layout -------------------------------------------------------


def test_project_settings_has_five_tab_buttons(client_with_projects):
    """Page renders with 5 tabs: Basics / Data / Models / Privacy / Notifications."""
    r = client_with_projects.get("/projects/alpha/settings")
    body = r.text
    for label in ("Basics", "Data", "Models", "Privacy", "Notifications"):
        assert f">{label}</button>" in body, f"missing tab button: {label}"


def test_project_settings_data_tab_has_data_paths_and_criteria(client_with_projects):
    """Data tab exposes textareas for data_paths and success_criteria."""
    body = client_with_projects.get("/projects/alpha/settings").text
    assert 'name="data_paths"' in body
    assert 'name="success_criteria"' in body


def test_project_settings_models_tab_has_per_agent_rows(client_with_projects):
    """Models tab renders one row per known agent with model + endpoint inputs."""
    body = client_with_projects.get("/projects/alpha/settings").text
    # Project-wide override
    assert 'name="runtime_model"' in body
    # Hardcoded KNOWN_AGENTS list
    for agent in (
        "planning_agent",
        "task_agent",
        "evaluator",
        "advisor_agent",
        "tool_builder",
        "literature_agent",
        "presentation_agent",
        "report_agent",
        "project_builder",
        "data_agent",
        "finalizer",
    ):
        assert f'name="model[{agent}]"' in body
        assert f'name="endpoint[{agent}]"' in body


def test_project_settings_privacy_tab_links_to_global_settings(client_with_projects):
    """Privacy tab is read-only and links to /settings for editing."""
    body = client_with_projects.get("/projects/alpha/settings").text
    assert 'href="/settings"' in body


def test_project_settings_notifications_tab_has_channels(client_with_projects):
    """Notifications tab exposes channel checkboxes and suppress level."""
    body = client_with_projects.get("/projects/alpha/settings").text
    assert 'name="channels"' in body
    # Suppress level lets users gate which event severities are sent.
    assert 'name="suppress_level"' in body


def test_project_settings_uses_tabs_macro(client_with_projects):
    """The page uses the tabs macro from _macros.html (Alpine x-data scope)."""
    body = client_with_projects.get("/projects/alpha/settings").text
    assert 'x-data="{ active:' in body
    assert "tab-button" in body
