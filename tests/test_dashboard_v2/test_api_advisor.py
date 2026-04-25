"""Tests for POST /api/projects/<name>/advisor.

The advisor agent is called inline (not as a subprocess), so tests
stub ``_run_advisor_inline`` via monkeypatch to avoid touching the
real Claude SDK. We assert: (a) the inline runner gets called with
the project path / question and its return value is shaped into a
JSON ``{"response": ...}`` payload, (b) form validation rejects an
empty question, (c) 404 is returned for unknown projects, and
(d) RuntimeError surfaces as 500.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard_v2.app import create_app
from urika.dashboard_v2.routers import api as api_module


def _make_project(tmp_path: Path, name: str = "alpha") -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    return proj


@pytest.fixture
def advisor_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, list[dict], Path]:
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    calls: list[dict] = []

    async def fake_run_advisor(project_path, project_name, question):
        calls.append(
            {
                "project_path": project_path,
                "project_name": project_name,
                "question": question,
            }
        )
        return f"# Advice\n\nFor question '{question}': try X, then Y."

    monkeypatch.setattr(api_module, "_run_advisor_inline", fake_run_advisor)

    app = create_app(project_root=tmp_path)
    return TestClient(app), calls, proj


def test_advisor_post_returns_response(advisor_client):
    client, calls, proj = advisor_client
    r = client.post(
        "/api/projects/alpha/advisor",
        data={"question": "what next?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "response" in body
    assert "what next?" in body["response"]
    assert body["response"].startswith("# Advice")

    assert len(calls) == 1
    assert calls[0]["project_path"] == proj
    assert calls[0]["project_name"] == "alpha"
    assert calls[0]["question"] == "what next?"


def test_advisor_post_404_unknown_project(advisor_client):
    client, calls, _ = advisor_client
    r = client.post(
        "/api/projects/nonexistent/advisor",
        data={"question": "anything"},
    )
    assert r.status_code == 404
    assert calls == []


def test_advisor_post_missing_question(advisor_client):
    client, calls, _ = advisor_client
    r = client.post("/api/projects/alpha/advisor", data={})
    assert r.status_code == 422
    assert "question" in r.json()["detail"]
    assert calls == []


def test_advisor_post_blank_question(advisor_client):
    client, calls, _ = advisor_client
    r = client.post("/api/projects/alpha/advisor", data={"question": "   "})
    assert r.status_code == 422
    assert calls == []


def test_advisor_post_runtime_error_returns_500(tmp_path, monkeypatch):
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    async def fake_run_advisor(*_, **__):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(api_module, "_run_advisor_inline", fake_run_advisor)

    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    r = client.post(
        "/api/projects/alpha/advisor",
        data={"question": "what next?"},
    )
    assert r.status_code == 500
    assert "LLM unavailable" in r.json()["detail"]
