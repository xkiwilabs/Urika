from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def client_with_docs(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    """A dashboard whose ``_docs_dir`` is monkeypatched to a tmp dir.

    Easier than fabricating an editable-install layout — we just point
    the resolver at a freshly-created docs/ tree under tmp_path.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "README.md").write_text("# Overview\n\nWelcome.")
    (docs_dir / "01-getting-started.md").write_text("# Getting started\n\nfirst steps")
    (docs_dir / "02-other.md").write_text("# Other\n\nmore content")

    from urika.dashboard.routers import docs as docs_router
    monkeypatch.setattr(docs_router, "_docs_dir", lambda: docs_dir)

    app = create_app(project_root=tmp_path)
    return TestClient(app), docs_dir


def test_docs_index_redirects_to_getting_started_when_present(client_with_docs):
    client, _ = client_with_docs
    r = client.get("/docs", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/docs/01-getting-started"


def test_docs_index_falls_back_to_first_numbered_when_no_getting_started(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "README.md").write_text("# Overview")  # excluded — repo-level
    (docs_dir / "02-other.md").write_text("# Other")
    from urika.dashboard.routers import docs as docs_router
    monkeypatch.setattr(docs_router, "_docs_dir", lambda: docs_dir)
    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    r = client.get("/docs", follow_redirects=False)
    assert r.headers["location"] == "/docs/02-other"


def test_docs_excludes_readme_from_nav(client_with_docs):
    """README.md is the repo overview, not a dashboard doc — never shown."""
    client, _ = client_with_docs
    r = client.get("/docs/01-getting-started")
    body = r.text
    assert "/docs/README" not in body
    # README content should also not appear via /docs/README
    r2 = client.get("/docs/README")
    assert r2.status_code == 404


def test_docs_page_renders_md_file(client_with_docs):
    client, _ = client_with_docs
    r = client.get("/docs/01-getting-started")
    assert r.status_code == 200
    body = r.text
    assert "<h1>Getting started</h1>" in body
    assert "first steps" in body


def test_docs_page_lists_all_docs_in_sidebar(client_with_docs):
    client, _ = client_with_docs
    r = client.get("/docs/01-getting-started")
    body = r.text
    # Docs nav lives in the sidebar, not the main panel.
    import re
    sidebar_match = re.search(
        r'<aside class="sidebar"[^>]*>(.*?)</aside>', body, re.DOTALL
    )
    assert sidebar_match is not None
    sidebar = sidebar_match.group(1)
    assert "/docs/01-getting-started" in sidebar
    assert "/docs/02-other" in sidebar
    # README is the repo-level overview; never in the dashboard docs nav.
    assert "/docs/README" not in sidebar
    # Back to projects link at the top of the docs sidebar
    assert "← Back to projects" in sidebar


def test_docs_page_sidebar_replaces_global_nav(client_with_docs):
    """When viewing docs, the sidebar shows docs (not Projects/Settings)."""
    client, _ = client_with_docs
    r = client.get("/docs/01-getting-started")
    body = r.text
    import re
    sidebar_match = re.search(
        r'<aside class="sidebar"[^>]*>(.*?)</aside>', body, re.DOTALL
    )
    sidebar = sidebar_match.group(1)
    # Global Projects/Settings shortcuts should NOT be in the sidebar on the docs page.
    # (They're replaced by the docs list.)
    assert 'href="/settings"' not in sidebar


def test_docs_page_404_unknown_slug(client_with_docs):
    client, _ = client_with_docs
    r = client.get("/docs/nonexistent")
    assert r.status_code == 404


def test_docs_page_400_traversal(client_with_docs):
    client, _ = client_with_docs
    r = client.get("/docs/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)


def test_docs_page_empty_state_when_no_docs(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    from urika.dashboard.routers import docs as docs_router
    monkeypatch.setattr(docs_router, "_docs_dir", lambda: None)
    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    r = client.get("/docs", follow_redirects=False)
    assert r.status_code == 200
    assert "Documentation not available" in r.text


def test_docs_link_in_sidebar(client_with_docs):
    client, _ = client_with_docs
    r = client.get("/projects")
    body = r.text
    assert ">Documentation</a>" in body
    assert 'href="/docs"' in body
