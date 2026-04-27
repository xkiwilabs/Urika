"""Tests for the JSON active-ops endpoint used by the client poller."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _write_lock(path: Path, pid: int | str) -> None:
    """Write a PID lock file at ``path``, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def _write_project(root: Path, name: str = "alpha") -> Path:
    proj = root / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "urika.toml").write_text(
        f"[project]\n"
        f'name = "{name}"\n'
        f'question = "q for {name}"\n'
        f'mode = "exploratory"\n'
        f'description = ""\n'
        f"\n"
        f"[preferences]\n"
        f'audience = "expert"\n'
    )
    return proj


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    """A dashboard whose registry points at a single tmp project ``alpha``.

    Returns ``(client, project_path)`` so tests can drop lock files into
    the project on demand.
    """
    project = _write_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(project)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app), project


def test_active_ops_endpoint_404_unknown_project(api_client) -> None:
    client, _ = api_client
    r = client.get("/api/projects/nonexistent/active-ops")
    assert r.status_code == 404


def test_active_ops_endpoint_returns_empty_list_when_idle(api_client) -> None:
    client, _ = api_client
    r = client.get("/api/projects/alpha/active-ops")
    assert r.status_code == 200
    assert r.json() == []


def test_active_ops_endpoint_returns_summarize_op_shape(api_client) -> None:
    client, project = api_client
    _write_lock(project / "projectbook" / ".summarize.lock", os.getpid())

    r = client.get("/api/projects/alpha/active-ops")
    assert r.status_code == 200
    payload = r.json()
    assert payload == [
        {
            "type": "summarize",
            "experiment_id": None,
            "log_url": "/projects/alpha/summarize/log",
        }
    ]


def test_active_ops_endpoint_returns_evaluate_with_experiment_id_and_query(
    api_client,
) -> None:
    client, project = api_client
    _write_lock(project / "experiments" / "exp-001" / ".evaluate.lock", os.getpid())

    r = client.get("/api/projects/alpha/active-ops")
    assert r.status_code == 200
    payload = r.json()
    assert len(payload) == 1
    entry = payload[0]
    assert entry["type"] == "evaluate"
    assert entry["experiment_id"] == "exp-001"
    assert entry["log_url"].endswith("?type=evaluate")
    assert "/projects/alpha/experiments/exp-001/log" in entry["log_url"]


def test_active_ops_endpoint_returns_multiple_concurrent(api_client) -> None:
    client, project = api_client
    _write_lock(project / "projectbook" / ".summarize.lock", os.getpid())
    _write_lock(project / "experiments" / "exp-001" / ".lock", os.getpid())

    r = client.get("/api/projects/alpha/active-ops")
    assert r.status_code == 200
    payload = r.json()
    types = sorted(entry["type"] for entry in payload)
    assert types == ["run", "summarize"]
    # Field shape for both entries.
    for entry in payload:
        assert set(entry.keys()) == {"type", "experiment_id", "log_url"}


def test_active_ops_endpoint_ignores_stale_locks(api_client) -> None:
    client, project = api_client
    # Empty lock — matches the helper's "ignore non-live" contract.
    lock = project / "projectbook" / ".summarize.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()

    r = client.get("/api/projects/alpha/active-ops")
    assert r.status_code == 200
    assert r.json() == []
