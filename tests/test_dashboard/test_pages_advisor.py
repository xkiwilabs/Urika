"""Tests for the advisor chat panel at /projects/<n>/advisor.

Reads ``projectbook/advisor-history.json`` via
``urika.core.advisor_memory.load_history`` and renders alternating
user/advisor message bubbles plus an input form. The form POSTs via
HTMX to ``/api/projects/<n>/advisor`` which spawns the advisor as a
subprocess and HX-Redirects to the live log page (covered by
test_api_advisor.py).
"""

import os
from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _make_project_with_history(tmp_path: Path, name: str, history: list[dict]) -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    book = proj / "projectbook"
    book.mkdir(parents=True)
    (book / "advisor-history.json").write_text(json.dumps(history))
    return proj


@pytest.fixture
def advisor_client(tmp_path: Path, monkeypatch) -> TestClient:
    history = [
        {
            "role": "user",
            "text": "Suggest a good baseline approach",
            "source": "repl",
            "timestamp": "2026-04-25T00:00:00Z",
        },
        {
            "role": "advisor",
            "text": "Try OLS first.",
            "source": "repl",
            "timestamp": "2026-04-25T00:01:00Z",
        },
    ]
    _make_project_with_history(tmp_path, "alpha", history)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_advisor_page_renders_history(advisor_client):
    r = advisor_client.get("/projects/alpha/advisor")
    assert r.status_code == 200
    body = r.text
    assert "Suggest a good baseline approach" in body
    assert "Try OLS first." in body
    # User and advisor message classes
    assert "message--user" in body
    assert "message--advisor" in body


def test_advisor_page_renders_input_form(advisor_client):
    r = advisor_client.get("/projects/alpha/advisor")
    body = r.text
    assert 'name="question"' in body
    assert "advisor-form" in body


def test_advisor_page_404_unknown_project(advisor_client):
    r = advisor_client.get("/projects/nonexistent/advisor")
    assert r.status_code == 404


def test_advisor_page_renders_empty_when_no_history(tmp_path, monkeypatch):
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
    r = client.get("/projects/alpha/advisor")
    assert r.status_code == 200
    # No history but page still renders
    body = r.text
    assert 'name="question"' in body


def test_advisor_link_in_sidebar(advisor_client):
    r = advisor_client.get("/projects/alpha")
    body = r.text
    assert "/projects/alpha/advisor" in body
    assert ">Advisor</a>" in body


def test_advisor_page_composer_posts_via_htmx(advisor_client):
    """The composer form POSTs to /api/projects/<n>/advisor via HTMX
    so the spawn endpoint can HX-Redirect to the live log page. The
    inline "thinking" placeholder is gone — the streaming log page
    owns the activity indicator now."""
    r = advisor_client.get("/projects/alpha/advisor")
    body = r.text
    # The form uses hx-post, not the old fetch+JSON inline JS.
    assert 'hx-post="/api/projects/alpha/advisor"' in body
    # No more static or animated placeholder on this page — it lives
    # on the /advisor/log streaming view instead.
    assert "appendMessage('advisor', 'Thinking…')" not in body
    assert "urikaThinking.start" not in body


def test_advisor_page_shows_view_running_when_lock_active(advisor_client, tmp_path):
    """When a live ``.advisor.lock`` exists for the project, the
    composer is replaced by a "View running advisor" link to the live
    log so the user rejoins the in-flight session instead of starting
    a parallel one."""
    proj = tmp_path / "alpha"
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    (book / ".advisor.lock").write_text(str(os.getpid()))

    r = advisor_client.get("/projects/alpha/advisor")
    assert r.status_code == 200
    body = r.text
    # The composer must be hidden — no submit form, no question textarea.
    assert 'hx-post="/api/projects/alpha/advisor"' not in body
    assert "advisor-form" not in body
    # The "view running" link must be present and point at the log page.
    assert "View running advisor" in body
    assert 'href="/projects/alpha/advisor/log"' in body


def test_advisor_log_page_renders_with_sse_url(advisor_client):
    """GET /projects/<n>/advisor/log returns the streaming page that
    references the advisor SSE endpoint."""
    r = advisor_client.get("/projects/alpha/advisor/log")
    assert r.status_code == 200
    body = r.text
    # Streaming page scaffolding present.
    assert 'id="log"' in body
    assert "EventSource" in body
    # Points at the advisor SSE stream specifically.
    assert "/api/projects/alpha/advisor/stream" in body


def test_advisor_log_page_404_unknown_project(advisor_client):
    r = advisor_client.get("/projects/nonexistent/advisor/log")
    assert r.status_code == 404
