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
