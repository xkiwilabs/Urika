"""Tests for the shared thinking placeholder — Phase B5.1.

Covers:
  * The ``_thinking.html`` Jinja partial renders a ``[data-urika-thinking]``
    placeholder div + pulls in the JS helper.
  * ``advisor_chat.html`` references the shared helper script (the
    inline 50-line spinner code was retired in favour of
    ``urikaThinking.start()``).
  * Each project-level log page (run / summarize / finalize / tool-build)
    includes the partial above the log <pre>.
  * The ``/static/urika-thinking.js`` asset is served and exposes
    ``urikaThinking.start``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def thinking_client(tmp_path: Path, monkeypatch) -> TestClient:
    """Project + experiment scaffolding so all four log pages render."""
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-001",
                "name": "baseline",
                "hypothesis": "linear",
                "status": "completed",
                "created_at": "2026-04-25T00:00:00Z",
            }
        )
    )

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_thinking_partial_renders_placeholder(thinking_client):
    """A page that includes _thinking.html must surface a
    ``[data-urika-thinking]`` element + pull in the JS helper.

    We piggyback on summarize_log.html (which includes the partial)
    rather than spinning up a one-off test template — same effect,
    no template-resolution gymnastics. The JS file path is the
    contractual hook the partial exposes."""
    r = thinking_client.get("/projects/alpha/summarize/log")
    assert r.status_code == 200
    body = r.text
    assert "data-urika-thinking" in body
    assert "/static/urika-thinking.js" in body
    # The auto-start script the partial wires up.
    assert "urikaThinking.start" in body


def test_advisor_chat_includes_thinking_js(thinking_client):
    r = thinking_client.get("/projects/alpha/advisor")
    assert r.status_code == 200
    assert "/static/urika-thinking.js" in r.text


def test_run_log_includes_thinking_partial(thinking_client):
    r = thinking_client.get("/projects/alpha/experiments/exp-001/log")
    assert r.status_code == 200
    body = r.text
    assert "data-urika-thinking" in body
    assert "/static/urika-thinking.js" in body


def test_summarize_log_includes_thinking_partial(thinking_client):
    r = thinking_client.get("/projects/alpha/summarize/log")
    assert r.status_code == 200
    body = r.text
    assert "data-urika-thinking" in body
    assert "/static/urika-thinking.js" in body


def test_finalize_log_includes_thinking_partial(thinking_client):
    r = thinking_client.get("/projects/alpha/finalize/log")
    assert r.status_code == 200
    body = r.text
    assert "data-urika-thinking" in body
    assert "/static/urika-thinking.js" in body


def test_tool_build_log_includes_thinking_partial(thinking_client):
    r = thinking_client.get("/projects/alpha/tools/build/log")
    assert r.status_code == 200
    body = r.text
    assert "data-urika-thinking" in body
    assert "/static/urika-thinking.js" in body


def test_static_urika_thinking_js_served(thinking_client):
    r = thinking_client.get("/static/urika-thinking.js")
    assert r.status_code == 200
    ctype = r.headers.get("content-type", "")
    assert "javascript" in ctype.lower(), (
        f"unexpected content-type for urika-thinking.js: {ctype!r}"
    )
    body = r.text
    # Public API on window.
    assert "urikaThinking" in body
    assert "start" in body
    # Shape sanity — frames + verbs are present in the source.
    assert "SPINNER_FRAMES" in body
    assert "ACTIVITY_VERBS" in body
