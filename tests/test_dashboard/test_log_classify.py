"""Tests for the per-line agent-header classifier shipped to the
streaming log pages (#122).

The classifier itself is plain JS — we only verify that the static
asset is served and that its source contains the expected pattern
strings, plus that every log page pulls in the script via _base.html.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


CLASSIFIER_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "urika"
    / "dashboard"
    / "static"
    / "urika-log-classify.js"
)


def test_classify_script_is_served():
    app = create_app(project_root=None)
    client = TestClient(app)
    r = client.get("/static/urika-log-classify.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    # Public global so the inline SSE handlers can call it.
    assert "window.urikaClassifyLine" in r.text


@pytest.mark.parametrize(
    "header_text,expected_class",
    [
        ("─── Planning Agent ────────────────", "log-line--planning"),
        ("─── Task Agent ───────────────────", "log-line--task"),
        ("─── Evaluator ────────────────────", "log-line--evaluator"),
        ("─── Advisor Agent ────────────────", "log-line--advisor"),
        ("─── Report Agent ─────────────────", "log-line--report"),
        ("─── Presentation Agent ───────────", "log-line--presentation"),
        ("─── Tool Builder ─────────────────", "log-line--tool-builder"),
        ("─── Data Agent ───────────────────", "log-line--data"),
        ("─── Literature Agent ─────────────", "log-line--literature"),
        ("─── Project Builder ──────────────", "log-line--project-builder"),
        ("─── Project Summarizer ───────────", "log-line--summarizer"),
        ("─── Finalizer ────────────────────", "log-line--finalizer"),
    ],
)
def test_classifier_source_pairs_header_with_class(header_text, expected_class):
    """Every documented agent-header pattern is mapped to its class.

    We're not running JS; instead we extract the (regex, class) tuples
    from the source and check that the regex matches the header text
    AND that the paired class is the expected one.
    """
    src = CLASSIFIER_PATH.read_text(encoding="utf-8")
    # Pattern entries look like:  [/^─── Planning Agent ─/, "log-line--planning"],
    pairs = re.findall(
        r"\[\s*/(\^─── [^/]+?)/\s*,\s*\"(log-line--[a-z-]+)\"\s*\]",
        src,
    )
    assert pairs, "classifier source contains no AGENT_PATTERNS entries"

    matched = None
    for raw_re, cls in pairs:
        # Translate JS-style regex to Python (^ is the only char we use).
        if re.match(raw_re, header_text):
            matched = cls
            break
    assert matched == expected_class, (
        f"{header_text!r} should map to {expected_class}, got {matched}"
    )


def test_classifier_source_includes_banner_and_generic_fallback():
    """The banner-char detector and generic agent-header fallback both ship."""
    src = CLASSIFIER_PATH.read_text(encoding="utf-8")
    # Banner box-drawing chars
    for ch in "╭│╰║╔╚═█╗╝▀":
        assert ch in src, f"banner char {ch!r} missing from classifier"
    assert "log-line--banner" in src
    # Generic fallback for unknown agent names
    assert "log-line--agent" in src


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
def log_pages_client(tmp_path: Path, monkeypatch) -> TestClient:
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    return TestClient(create_app(project_root=tmp_path))


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
def test_log_pages_include_classify_script(log_pages_client, url):
    """Every streaming-log template loads the classifier script."""
    r = log_pages_client.get(url)
    assert r.status_code == 200, url
    assert "/static/urika-log-classify.js" in r.text
