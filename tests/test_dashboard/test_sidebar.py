"""Sidebar shows global links OR project links — never both."""


def test_sidebar_on_projects_list_shows_global_links_only(client_with_projects):
    r = client_with_projects.get("/projects")
    body = r.text
    assert 'href="/projects"' in body
    assert 'href="/settings"' in body
    # No project nav since we're not inside a project
    assert "← Back to projects" not in body


def test_sidebar_on_project_home_shows_project_links_and_back_button(
    client_with_projects,
):
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


def test_project_sidebar_lists_all_ten_links(client_with_projects):
    """Inside a project the sidebar surfaces all ten project-scoped links."""
    r = client_with_projects.get("/projects/alpha")
    body = r.text
    expected = [
        "/projects/alpha",  # Home — full match handled by the active-class logic
        "/projects/alpha/experiments",
        "/projects/alpha/methods",
        "/projects/alpha/tools",
        "/projects/alpha/data",
        "/projects/alpha/knowledge",
        "/projects/alpha/advisor",
        "/projects/alpha/sessions",
        "/projects/alpha/usage",
        "/projects/alpha/settings",
    ]
    for href in expected:
        assert f'href="{href}"' in body, f"missing sidebar link: {href}"


def test_project_sidebar_canonical_order(client_with_projects):
    """Sidebar order is Home / Experiments / Advisor / Sessions / Knowledge /
    Methods / Tools / Data / Usage / Settings — Sessions sits between
    Advisor and Knowledge, with Methods/Tools/Data after, and Usage
    between Data and Settings."""
    r = client_with_projects.get("/projects/alpha")
    body = r.text
    # Use the href anchors as positional markers — they appear once each
    # in the sidebar block.
    pairs = [
        ("/projects/alpha/experiments", "/projects/alpha/advisor"),
        ("/projects/alpha/advisor", "/projects/alpha/sessions"),
        ("/projects/alpha/sessions", "/projects/alpha/knowledge"),
        ("/projects/alpha/knowledge", "/projects/alpha/methods"),
        ("/projects/alpha/methods", "/projects/alpha/tools"),
        ("/projects/alpha/tools", "/projects/alpha/data"),
        ("/projects/alpha/data", "/projects/alpha/usage"),
        ("/projects/alpha/usage", "/projects/alpha/settings"),
    ]
    for earlier, later in pairs:
        ei = body.index(f'href="{earlier}"')
        li = body.index(f'href="{later}"')
        assert ei < li, f"sidebar order broken: {earlier} should precede {later}"
