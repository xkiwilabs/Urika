"""Tests for ``GET /api/projects/<n>/usage/totals`` — backs the live
log-page footer (#123)."""

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


def _write_usage(proj: Path, totals: dict) -> None:
    (proj / "usage.json").write_text(
        json.dumps({"sessions": [], "totals": totals}, indent=2),
        encoding="utf-8",
    )


@pytest.fixture
def usage_totals_client(tmp_path: Path, monkeypatch) -> TestClient:
    proj = _make_project(tmp_path, "alpha")
    _write_usage(
        proj,
        {
            "sessions": 2,
            "total_duration_ms": 900_000,
            "total_tokens_in": 1234,
            "total_tokens_out": 5678,
            "total_cost_usd": 0.42,
            "total_agent_calls": 7,
            "total_experiments": 1,
        },
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    return TestClient(create_app(project_root=tmp_path))


def test_usage_totals_404_unknown_project(usage_totals_client):
    r = usage_totals_client.get("/api/projects/nope/usage/totals")
    assert r.status_code == 404


def test_usage_totals_returns_expected_keys(usage_totals_client):
    r = usage_totals_client.get("/api/projects/alpha/usage/totals")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "agent_calls",
    }


def test_usage_totals_reflects_disk_values(usage_totals_client):
    r = usage_totals_client.get("/api/projects/alpha/usage/totals")
    assert r.status_code == 200
    body = r.json()
    assert body["tokens_in"] == 1234
    assert body["tokens_out"] == 5678
    assert body["cost_usd"] == 0.42
    assert body["agent_calls"] == 7


def test_usage_totals_zero_when_no_usage_json(tmp_path, monkeypatch):
    """Project with no usage.json on disk → all zeros, not a crash."""
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    r = client.get("/api/projects/alpha/usage/totals")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "agent_calls": 0,
    }
