"""Tests for ``GET /api/projects/{name}/git/status`` (v0.6.0 Task 3.1).

Returns a JSON snapshot of the project's git state — branch, remote,
dirty count, last-commit, recent commits — so the dashboard's project
page can show a small "GitHub" panel without invoking the CLI.

Mirrors the URIKA_HOME monkeypatch + ``create_app(project_root=...)``
pattern used in ``test_api_memory.py`` so the registry is isolated
from the real ``~/.urika``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from urika.cli import cli
from urika.dashboard.app import create_app


def _make_project(root: Path, name: str = "proj") -> Path:
    proj = root / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    return proj


def _register(home: Path, name: str, path: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "projects.json").write_text(json.dumps({name: str(path)}))


@pytest.fixture
def plain_project(tmp_path: Path, monkeypatch):
    """A registered project that has NOT been ``urika github init``'d."""
    proj_root = tmp_path / "projects"
    proj_root.mkdir()
    proj = _make_project(proj_root, "proj")
    home = tmp_path / "home"
    monkeypatch.setenv("URIKA_HOME", str(home))
    _register(home, "proj", proj)
    app = create_app(project_root=proj_root, auth_token=None)
    return TestClient(app), proj


@pytest.fixture
def initialised_project(tmp_path: Path, monkeypatch):
    """A registered project with ``urika github init --remote <bare>``."""
    proj_root = tmp_path / "projects"
    proj_root.mkdir()
    proj = _make_project(proj_root, "proj")
    home = tmp_path / "home"
    monkeypatch.setenv("URIKA_HOME", str(home))
    _register(home, "proj", proj)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    result = CliRunner().invoke(
        cli, ["github", "init", "proj", "--remote", str(remote)]
    )
    assert result.exit_code == 0, result.output
    app = create_app(project_root=proj_root, auth_token=None)
    return TestClient(app), proj, remote


def test_git_status_returns_remote_branch_dirty(initialised_project):
    client, _proj, remote = initialised_project
    resp = client.get("/api/projects/proj/git/status")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("initialized") is True
    assert "branch" in data
    assert data["branch"]  # non-empty branch name
    assert data["remote"] is not None
    assert str(remote) in data["remote"]
    assert "dirty_count" in data
    assert isinstance(data["dirty_count"], int)
    assert "recent" in data
    assert isinstance(data["recent"], list)


def test_git_status_returns_initialized_false_for_plain_project(plain_project):
    """A project that exists but hasn't been ``urika github init``'d yet."""
    client, _proj = plain_project
    resp = client.get("/api/projects/proj/git/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("initialized") is False
    assert data["branch"] is None
    assert data["remote"] is None
    assert data["dirty_count"] == 0
    assert data["recent"] == []


def test_git_status_404_for_unknown_project(plain_project):
    client, _proj = plain_project
    resp = client.get("/api/projects/no-such/git/status")
    assert resp.status_code == 404


def test_git_status_includes_recent_commits(initialised_project):
    """``recent`` is a list of {sha, subject, event, ts} dicts, newest first."""
    client, proj, _remote = initialised_project
    # Add a tagged commit with an ``urika-event:`` trailer.
    (proj / "x.txt").write_text("x")
    subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(proj),
            "commit",
            "-m",
            "urika: test\n\nurika-event: experiment_complete",
        ],
        check=True,
    )
    resp = client.get("/api/projects/proj/git/status")
    data = resp.json()
    assert len(data["recent"]) >= 1
    first = data["recent"][0]
    assert {"sha", "subject", "event", "ts"} <= set(first.keys())
    assert first["event"] == "experiment_complete"
