"""Tests for the live log-page footer markup + driver script (#123)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _make_project(root: Path, name: str) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\n'
        f'mode = "exploratory"\ndescription = ""\n\n'
        f'[preferences]\naudience = "expert"\n'
    )
    return proj


@pytest.fixture
def log_footer_client(tmp_path: Path, monkeypatch) -> TestClient:
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    return TestClient(create_app(project_root=tmp_path))


_FOOTER_FIELDS = (
    "data-log-footer",
    "data-footer-elapsed",
    "data-footer-agent",
    "data-footer-tokens",
    "data-footer-cost",
    "data-footer-model",
)


@pytest.mark.parametrize(
    "url",
    [
        "/projects/alpha/experiments/exp-001/log",
        "/projects/alpha/summarize/log",
        "/projects/alpha/finalize/log",
        "/projects/alpha/tools/build/log",
        "/projects/alpha/advisor/log",
    ],
)
def test_log_page_includes_footer(log_footer_client, url):
    """Each streaming-log page renders the footer + every named cell."""
    r = log_footer_client.get(url)
    assert r.status_code == 200, url
    for token in _FOOTER_FIELDS:
        assert token in r.text, f"{url}: missing {token}"


def test_log_pages_include_footer_script(log_footer_client):
    """Footer driver is wired in via _base.html so every page loads it."""
    r = log_footer_client.get("/projects/alpha/experiments/exp-001/log")
    assert r.status_code == 200
    assert "/static/urika-log-footer.js" in r.text


def test_static_log_footer_js_served():
    """The footer driver is served from /static with a JS content-type."""
    app = create_app(project_root=None)
    client = TestClient(app)
    r = client.get("/static/urika-log-footer.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    # Source contains the polling function the doc-comment promises.
    assert "pollUsage" in r.text
    assert "/usage/totals" in r.text
