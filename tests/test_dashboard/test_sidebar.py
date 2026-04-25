"""Sidebar shows global links OR project links — never both."""


def test_sidebar_on_projects_list_shows_global_links_only(client_with_projects):
    r = client_with_projects.get("/projects")
    body = r.text
    assert 'href="/projects"' in body
    assert 'href="/settings"' in body
    # No project nav since we're not inside a project
    assert "← Back to projects" not in body


def test_sidebar_on_project_home_shows_project_links_and_back_button(client_with_projects):
    r = client_with_projects.get("/projects/alpha")
    body = r.text
    assert "← Back to projects" in body
    assert 'href="/projects"' in body  # the back link
    # Project-scoped links present
    assert "/projects/alpha/experiments" in body
    assert "/projects/alpha/methods" in body
    # Global Settings link absent — project Settings link present instead
    # Count occurrences carefully: "/settings" appears exactly once for the
    # project-scoped settings link.
    assert body.count('href="/settings"') == 0
    assert "/projects/alpha/settings" in body


def test_sidebar_on_global_settings_shows_global_links_only(settings_client):
    r = settings_client.get("/settings")
    body = r.text
    assert 'href="/projects"' in body
    assert "← Back to projects" not in body
