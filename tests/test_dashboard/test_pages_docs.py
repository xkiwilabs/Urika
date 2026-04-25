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


def test_docs_index_redirects_to_first_doc(client_with_docs):
    client, _ = client_with_docs
    r = client.get("/docs", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] in ("/docs/README", "/docs/01-getting-started")


def test_docs_page_renders_md_file(client_with_docs):
    client, _ = client_with_docs
    r = client.get("/docs/01-getting-started")
    assert r.status_code == 200
    body = r.text
    assert "<h1>Getting started</h1>" in body
    assert "first steps" in body


def test_docs_page_lists_all_docs_in_nav(client_with_docs):
    client, _ = client_with_docs
    r = client.get("/docs/01-getting-started")
    body = r.text
    assert "/docs/README" in body
    assert "/docs/01-getting-started" in body
    assert "/docs/02-other" in body


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
