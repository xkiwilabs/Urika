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


# ── Regex-pinning tests ──────────────────────────────────────────
#
# The agent + model parsers live in the JS driver
# (`urika-log-footer.js`). We pin their behaviour here by exercising
# Python regexes that mirror the JS ones exactly, against the actual
# log-line shapes ``cli_display.print_agent`` and the SDK adapter
# emit. Pre-fix the JS regex was anchored at ``^───`` which never
# matched because the orchestrator prefixes every agent header with
# two spaces (``"\n  ─── Planning Agent ───…"``). The dashboard
# footer model + agent fields therefore stayed at "—" forever
# during a running experiment, even though the rest of the run-log
# panel was rendering the headers correctly.

import re


# JS:  /^─── ([\w ]+?)(?: Agent)? ─/
_AGENT_PY = re.compile(r"^─── ([\w ]+?)(?: Agent)? ─")
# JS: /\b(claude-…|gpt-…|gemini-…|qwen…|llama…|mistral…)\b/i
_MODEL_PY = re.compile(
    r"\b(claude-[a-z0-9.-]+|gpt-[a-z0-9.-]+|gemini-[a-z0-9.-]+|"
    r"qwen[a-z0-9.:_-]+|llama[a-z0-9.:_-]+|mistral[a-z0-9.:_-]+)\b",
    re.IGNORECASE,
)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _normalise(line: str) -> str:
    """Mirror the JS ``raw.replace(ANSI_RE, "").trimStart()`` step."""
    return _ANSI.sub("", line).lstrip()


@pytest.mark.parametrize(
    "raw_line, expected_agent",
    [
        # cli_display.print_agent for each role — note the two-space
        # prefix that broke the original regex.
        ("  ─── Planning Agent ─────────────────────────────────────",
         "planning"),
        ("  ─── Task Agent ─────────────────────────────────────",
         "task"),
        ("  ─── Evaluator ─────────────────────────────────────",
         "evaluator"),
        ("  ─── Advisor Agent ─────────────────────────────────────",
         "advisor"),
        ("  ─── Tool Builder ─────────────────────────────────────",
         "tool builder"),
        ("  ─── Literature Agent ─────────────────────────────────────",
         "literature"),
        ("  ─── Report Agent ─────────────────────────────────────",
         "report"),
        ("  ─── Presentation Agent ─────────────────────────────────────",
         "presentation"),
        ("  ─── Finalizer ─────────────────────────────────────",
         "finalizer"),
        # ANSI-coloured form (older urika builds; still arrives this
        # way when stdout was a TTY at orchestrator-spawn time).
        ("  \x1b[36m─── Planning Agent \x1b[0m─────────────────",
         "planning"),
    ],
)
def test_agent_regex_extracts_role_from_realistic_log_lines(
    raw_line: str, expected_agent: str
):
    text = _normalise(raw_line)
    match = _AGENT_PY.search(text)
    assert match is not None, f"agent regex did not match {raw_line!r}"
    assert match.group(1).lower() == expected_agent


@pytest.mark.parametrize(
    "raw_line, expected_model",
    [
        # SDK init JSON line — the bundled CLI emits this once per
        # session, contains the model name as a quoted string.
        ('{"type":"system","subtype":"init","model":"claude-opus-4-6"}',
         "claude-opus-4-6"),
        # Status-bar / debug print formats.
        ("  model: claude-sonnet-4-5",  "claude-sonnet-4-5"),
        ("  model: claude-haiku-4-5",   "claude-haiku-4-5"),
        # Local / private endpoint model names.
        ("  loaded model qwen2.5:14b on private",  "qwen2.5:14b"),
        ("  loaded model llama-3.2:8b on private", "llama-3.2:8b"),
    ],
)
def test_model_regex_recognises_cloud_and_local_model_names(
    raw_line: str, expected_model: str
):
    text = _normalise(raw_line)
    match = _MODEL_PY.search(text)
    assert match is not None, f"model regex did not match {raw_line!r}"
    assert match.group(1).lower() == expected_model.lower()


def test_agent_regex_does_not_match_tool_use_lines():
    """Tool-use lines like ``▸ Read /path`` must NOT be matched as
    agent headers — they appear far more often than agent headers
    and would otherwise overwrite the footer's agent field on every
    tool invocation."""
    for line in (
        "    ▸ Read /home/me/project/urika.toml",
        "    ▸ Bash ls -la",
        "    ▸ Glob **/*.csv",
        "    ▸ Write methods/baseline.py",
    ):
        text = _normalise(line)
        assert _AGENT_PY.search(text) is None, (
            f"agent regex unexpectedly matched tool-use line: {line!r}"
        )


def test_static_js_uses_the_pinned_regexes():
    """If anyone edits ``urika-log-footer.js`` they should keep the
    regex shapes in sync with these Python pins. Verify the JS
    file still contains the recognisable substrings.
    """
    static = (
        Path(__file__).parent.parent.parent
        / "src" / "urika" / "dashboard" / "static"
        / "urika-log-footer.js"
    )
    js = static.read_text(encoding="utf-8")
    # Agent regex with optional ``Agent`` suffix.
    assert "─── ([\\w ]+?)(?: Agent)? ─" in js
    # Model regex covers cloud + local endpoint model names.
    assert "claude-[a-z0-9.-]+" in js
    assert "qwen" in js
    assert "llama" in js
    # ANSI strip + trimStart pattern is in place.
    assert "ANSI_RE" in js
    assert "trimStart()" in js
