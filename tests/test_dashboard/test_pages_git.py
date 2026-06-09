"""Tests for the dashboard Git tab page (v0.6.0 Task 3.4).

Renders ``/projects/{name}/git`` — branch + remote + dirty count +
recent commits when initialised, an Init form when not. Mirrors the
URIKA_HOME monkeypatch + ``create_app(project_root=...)`` pattern used
in ``test_api_git_status.py`` so the registry is isolated from the
real ``~/.urika``.
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


def test_git_page_renders_for_initialised_project(initialised_project):
    client, _proj, _remote = initialised_project
    resp = client.get("/projects/proj/git")
    assert resp.status_code == 200, resp.text
    text = resp.text.lower()
    assert "branch" in text
    assert "remote" in text
    # Manual push button present
    assert "push now" in text or 'hx-post="/api/projects/proj/git/push"' in resp.text


def test_git_page_has_pull_button_when_initialised(initialised_project):
    """v0.7.1 parity sweep: the Git tab gained a Pull button next to
    Push (the pull endpoint mirrors ``urika github pull``)."""
    client, _proj, _remote = initialised_project
    resp = client.get("/projects/proj/git")
    assert resp.status_code == 200, resp.text
    assert 'hx-post="/api/projects/proj/git/pull"' in resp.text


def test_git_page_offers_init_when_not_initialised(plain_project):
    client, _proj = plain_project
    resp = client.get("/projects/proj/git")
    assert resp.status_code == 200
    text = resp.text
    # Init form offered
    assert "Initialise" in text or "Init" in text
    assert 'hx-post="/api/projects/proj/git/init"' in text


def test_git_page_404_unknown_project(plain_project):
    client, _proj = plain_project
    resp = client.get("/projects/no-such/git")
    assert resp.status_code == 404


def test_sidebar_has_git_link(plain_project):
    """Any per-project page renders the sidebar with a Git link."""
    client, _proj = plain_project
    # Use the memory page since v0.5.0 sidebar links work there
    resp = client.get("/projects/proj/memory")
    assert resp.status_code == 200
    assert "/projects/proj/git" in resp.text


def test_git_page_shows_recent_commits_with_event_tag(initialised_project):
    client, proj, _remote = initialised_project
    # Add a tagged commit
    (proj / "x.txt").write_text("x")
    subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(proj),
            "commit",
            "-m",
            "urika: experiment complete\n\nurika-event: experiment_complete",
        ],
        check=True,
    )
    resp = client.get("/projects/proj/git")
    assert resp.status_code == 200
    text = resp.text
    assert "experiment_complete" in text
    assert "urika: experiment complete" in text
