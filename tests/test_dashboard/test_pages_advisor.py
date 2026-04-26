"""Tests for the advisor chat panel at /projects/<n>/advisor.

Reads ``projectbook/advisor-history.json`` via
``urika.core.advisor_memory.load_history`` and renders alternating
user/advisor message bubbles plus an input form. Submission goes
through the existing POST /api/projects/<n>/advisor endpoint via
inline JS (not tested here — that's covered by test_api_advisor.py
plus a JS-heavy end-to-end harness we don't run in CI).
"""

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


def test_advisor_page_has_rotating_spinner_and_verbs(advisor_client):
    """The advisor chat must load the shared thinking helper so the
    placeholder animates instead of being a static "Thinking…" string.
    Mirrors the CLI/TUI's _spinner_frames / _activity_verbs in
    urika.repl.main — the frames + verbs themselves now live in
    /static/urika-thinking.js, but the page must reference it and call
    urikaThinking.start() to spin up the placeholder."""
    r = advisor_client.get("/projects/alpha/advisor")
    body = r.text
    # The shared helper script is included.
    assert "/static/urika-thinking.js" in body
    # The page calls into the helper to start a placeholder.
    assert "urikaThinking.start" in body
    # No more static placeholder text.
    assert "appendMessage('advisor', 'Thinking…')" not in body
