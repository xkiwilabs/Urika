"""Tests for POST /api/projects/<name>/suggest-experiment.

The endpoint runs the advisor synchronously to suggest a next
experiment. Tests stub the agent runner via monkeypatch so we never
invoke a real Claude Agent SDK call. We assert: (a) 404 for unknown
projects, (b) a parseable suggestion JSON is round-tripped to the
client, (c) the privacy gate fires before the runner when the
project is in private mode without an endpoint, (d) advisor failures
surface as 500 with a clear detail, (e) the user's seed instructions
are merged into the response's instructions field for the Review
step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _make_project(tmp_path: Path, name: str = "alpha") -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    return proj


def _make_private_project(tmp_path: Path, name: str = "alpha") -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n\n'
        f'[privacy]\nmode = "private"\n'
    )
    return proj


@dataclass
class _FakeResult:
    success: bool = True
    text_output: str = ""
    error: str | None = None


class _FakeRole:
    def build_config(self, **_: Any) -> dict:
        return {}


class _FakeRegistry:
    def discover(self) -> None: ...
    def get(self, _name: str) -> _FakeRole:
        return _FakeRole()


def _install_fake_runner(
    monkeypatch, *, text_output: str, success: bool = True
) -> None:
    """Patch the runner factory + agent registry to return a fixed suggestion."""

    class _FakeRunner:
        async def run(self, _config, _prompt, **_):
            return _FakeResult(success=success, text_output=text_output)

    from urika.dashboard.routers import api as api_module  # noqa: F401

    # The advisor lookup is done via lazy imports inside the endpoint, so
    # we patch at the source modules.
    import urika.agents.runner as runner_mod
    import urika.agents.registry as registry_mod

    monkeypatch.setattr(runner_mod, "get_runner", lambda *a, **kw: _FakeRunner())
    monkeypatch.setattr(registry_mod, "AgentRegistry", _FakeRegistry)


@pytest.fixture
def suggest_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app), proj


def test_suggest_404_unknown_project(suggest_client):
    client, _ = suggest_client
    r = client.post(
        "/api/projects/nonexistent/suggest-experiment",
        data={"instructions": ""},
    )
    assert r.status_code == 404


def test_suggest_returns_structured_suggestion(suggest_client, monkeypatch):
    """Happy path: runner returns a JSON suggestion with name + method,
    endpoint parses it and returns {name, hypothesis, instructions}."""
    client, _ = suggest_client
    # The advisor's text_output must contain a JSON block with a
    # ``suggestions`` key (parse_suggestions extracts the first match).
    suggestion_json = json.dumps(
        {
            "suggestions": [
                {
                    "name": "Kaya Decomposition Counterfactual",
                    "method": "Decompose energy intensity using Kaya identity.",
                    "instructions": "Start with OECD members only.",
                }
            ]
        }
    )
    text_output = f"Here is my plan:\n```json\n{suggestion_json}\n```\n"
    _install_fake_runner(monkeypatch, text_output=text_output)

    r = client.post(
        "/api/projects/alpha/suggest-experiment",
        data={"instructions": "focus on developed economies"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Kaya Decomposition Counterfactual"
    assert "Kaya identity" in body["hypothesis"]
    # The user's seed instructions must be preserved in the merged
    # instructions field so the Review step's textarea has full context.
    assert "focus on developed economies" in body["instructions"]
    assert "OECD members" in body["instructions"]


def test_suggest_privacy_gate(tmp_path: Path, monkeypatch):
    """Private mode without an endpoint must 422 before invoking the runner."""
    proj = _make_private_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    (home / "settings.toml").write_text("", encoding="utf-8")

    # Even if the runner were called, fail loudly to make the bug visible.
    def _boom(*_a, **_kw):
        raise AssertionError("runner must NOT be invoked when privacy gate fires")

    import urika.agents.runner as runner_mod

    monkeypatch.setattr(runner_mod, "get_runner", _boom)

    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    r = client.post(
        "/api/projects/alpha/suggest-experiment",
        data={"instructions": ""},
    )
    assert r.status_code == 422
    detail = r.json()["detail"].lower()
    assert "private" in detail
    assert "endpoint" in detail


def test_suggest_handles_advisor_failure(suggest_client, monkeypatch):
    """Runner success=False or no parseable JSON → 500 with detail."""
    client, _ = suggest_client
    _install_fake_runner(monkeypatch, text_output="", success=False)

    r = client.post(
        "/api/projects/alpha/suggest-experiment",
        data={"instructions": ""},
    )
    assert r.status_code == 500
    assert "advisor" in r.json()["detail"].lower()


def test_suggest_handles_unparseable_output(suggest_client, monkeypatch):
    """Runner succeeds but returns no JSON suggestions block → 500."""
    client, _ = suggest_client
    _install_fake_runner(monkeypatch, text_output="some prose with no json")

    r = client.post(
        "/api/projects/alpha/suggest-experiment",
        data={"instructions": ""},
    )
    assert r.status_code == 500
    assert (
        "parse" in r.json()["detail"].lower() or "advisor" in r.json()["detail"].lower()
    )
