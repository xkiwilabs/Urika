"""Tests for /projects/<n>/usage — Phase 13F.1."""

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


def _write_usage(proj: Path, sessions: list[dict]) -> None:
    """Write a usage.json with given sessions and recomputed totals."""
    totals = {
        "sessions": len(sessions),
        "total_duration_ms": sum(s.get("duration_ms", 0) for s in sessions),
        "total_tokens_in": sum(s.get("tokens_in", 0) for s in sessions),
        "total_tokens_out": sum(s.get("tokens_out", 0) for s in sessions),
        "total_cost_usd": round(sum(s.get("cost_usd", 0) for s in sessions), 4),
        "total_agent_calls": sum(s.get("agent_calls", 0) for s in sessions),
        "total_experiments": sum(s.get("experiments_run", 0) for s in sessions),
    }
    (proj / "usage.json").write_text(
        json.dumps({"sessions": sessions, "totals": totals}, indent=2),
        encoding="utf-8",
    )


@pytest.fixture
def usage_client(tmp_path: Path, monkeypatch) -> TestClient:
    proj = _make_project(tmp_path, "alpha")
    _write_usage(
        proj,
        [
            {
                "started": "2026-04-01T10:00:00+00:00",
                "ended": "2026-04-01T10:05:00+00:00",
                "duration_ms": 300_000,
                "tokens_in": 1000,
                "tokens_out": 2000,
                "cost_usd": 0.05,
                "agent_calls": 3,
                "experiments_run": 1,
            },
            {
                "started": "2026-04-02T11:00:00+00:00",
                "ended": "2026-04-02T11:10:00+00:00",
                "duration_ms": 600_000,
                "tokens_in": 2000,
                "tokens_out": 3000,
                "cost_usd": 0.10,
                "agent_calls": 5,
                "experiments_run": 0,
            },
        ],
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_usage_page_returns_200(usage_client):
    r = usage_client.get("/projects/alpha/usage")
    assert r.status_code == 200


def test_usage_page_404_unknown_project(usage_client):
    r = usage_client.get("/projects/nope/usage")
    assert r.status_code == 404


def test_usage_page_renders_totals(usage_client):
    r = usage_client.get("/projects/alpha/usage")
    body = r.text
    # Sessions card
    assert ">2<" in body  # totals.sessions == 2
    # Total tokens = 1000+2000+2000+3000 = 8000
    assert "8000" in body
    # Total cost = 0.15
    assert "0.15" in body
    # Agent calls total
    assert ">8<" in body  # 3+5 == 8
    # Experiments total
    assert ">1<" in body  # 1+0 == 1


def test_usage_page_renders_chart_canvases(usage_client):
    r = usage_client.get("/projects/alpha/usage")
    body = r.text
    assert 'id="chart-tokens"' in body
    assert 'id="chart-cost"' in body
    # Pinned Chart.js version, NOT @latest.
    assert "chart.js@4.4.1" in body
    assert "@latest" not in body
    # JSON data block the chart script reads from.
    assert 'id="usage-data"' in body


def test_usage_page_empty_state_when_no_usage_json(tmp_path, monkeypatch):
    """No usage.json on disk → empty state, not a crash."""
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    r = client.get("/projects/alpha/usage")
    assert r.status_code == 200
    assert "No usage recorded yet" in r.text
    # Charts should not render when there are no sessions.
    assert 'id="chart-tokens"' not in r.text


def test_usage_page_empty_state_when_sessions_empty(tmp_path, monkeypatch):
    """usage.json with sessions=[] → empty state."""
    proj = _make_project(tmp_path, "alpha")
    _write_usage(proj, [])
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    r = client.get("/projects/alpha/usage")
    assert r.status_code == 200
    assert "No usage recorded yet" in r.text


def test_usage_page_caps_recent_sessions_at_50(tmp_path, monkeypatch):
    """60 sessions on disk → the recent table shows only 50 rows."""
    proj = _make_project(tmp_path, "alpha")
    sessions = []
    for i in range(60):
        sessions.append(
            {
                "started": f"2026-04-{(i % 28) + 1:02d}T10:00:00+00:00",
                "ended": f"2026-04-{(i % 28) + 1:02d}T10:05:00+00:00",
                "duration_ms": 1000 * (i + 1),
                "tokens_in": 100,
                "tokens_out": 200,
                "cost_usd": 0.001,
                "agent_calls": 1,
                "experiments_run": 0,
            }
        )
    _write_usage(proj, sessions)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    r = client.get("/projects/alpha/usage")
    assert r.status_code == 200
    body = r.text
    # Find the recent-sessions <tbody> and count the <tr> entries inside.
    # The page has multiple tables, but only the recent-sessions one
    # comes after the "Recent sessions" heading. Slice from there.
    idx = body.find("Recent sessions")
    assert idx != -1
    tail = body[idx:]
    # Cheap row count via "<tr>" occurrences after the heading. The
    # recent-sessions table is the last one on the page.
    assert tail.count("<tr>") == 51  # 1 header + 50 body rows


def test_usage_page_single_session_renders_charts(tmp_path, monkeypatch):
    """Single session — charts still render with one data point."""
    proj = _make_project(tmp_path, "alpha")
    _write_usage(
        proj,
        [
            {
                "started": "2026-04-01T10:00:00+00:00",
                "ended": "2026-04-01T10:05:00+00:00",
                "duration_ms": 300_000,
                "tokens_in": 1000,
                "tokens_out": 2000,
                "cost_usd": 0.05,
                "agent_calls": 3,
                "experiments_run": 1,
            },
        ],
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    r = client.get("/projects/alpha/usage")
    assert r.status_code == 200
    body = r.text
    assert 'id="chart-tokens"' in body
    assert 'id="chart-cost"' in body
