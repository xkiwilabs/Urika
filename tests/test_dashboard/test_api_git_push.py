"""Tests for ``POST /api/projects/{name}/git/push`` (v0.6.0 Task 3.2).

Stages everything, runs the secret scan, returns 409 (without committing)
if any matches are found, otherwise commits + pushes. Mirrors the
URIKA_HOME monkeypatch + ``create_app(project_root=...)`` pattern used in
``test_api_git_status.py`` so the registry is isolated from the real
``~/.urika``.

All state-changing requests carry ``Origin: http://testserver`` to satisfy
the v0.4.5.1 CSRF origin guard. Cross-origin POSTs are exercised in
``test_git_push_csrf_rejection`` to confirm the guard is wired up.
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


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Register a project ``proj`` and run ``urika github init --remote <bare>``.

    Returns ``(project_dir, bare_remote_dir)``.
    """
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
    return proj, remote


def _setup_uninitialised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Register a project that has NOT been ``urika github init``'d."""
    proj_root = tmp_path / "projects"
    proj_root.mkdir()
    proj = _make_project(proj_root, "proj")
    home = tmp_path / "home"
    monkeypatch.setenv("URIKA_HOME", str(home))
    _register(home, "proj", proj)
    return proj


def _client(tmp_path: Path) -> TestClient:
    app = create_app(project_root=tmp_path / "projects", auth_token=None)
    return TestClient(app)


def test_git_push_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj, remote = _setup(tmp_path, monkeypatch)
    (proj / "new.txt").write_text("hello")
    client = _client(tmp_path)
    resp = client.post(
        "/api/projects/proj/git/push",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["pushed_sha"]
    # Confirm remote sees the commit.
    log = subprocess.run(
        ["git", "-C", str(remote), "log", "--oneline"],
        capture_output=True,
        text=True,
    ).stdout
    assert log.strip()  # at least one commit on the bare remote


def test_git_push_aborts_on_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj, remote = _setup(tmp_path, monkeypatch)
    (proj / "leak.py").write_text(
        "K='sk-ant-api03-1234567890abcdefghijklmnopqrstuvwx'\n"
    )
    client = _client(tmp_path)
    resp = client.post(
        "/api/projects/proj/git/push",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["ok"] is False
    assert "secret-detected" in (data.get("error") or "")
    assert "matches" in data
    assert any("leak.py" in (m.get("file") or "") for m in data["matches"])
    # No leak commit on the remote.
    log = subprocess.run(
        ["git", "-C", str(remote), "log", "--oneline"],
        capture_output=True,
        text=True,
    ).stdout
    assert "leak" not in log
    # Index has been reset (file not staged) so the working tree isn't
    # left in a half-staged state.
    status_out = subprocess.run(
        ["git", "-C", str(proj), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
    ).stdout
    assert "leak.py" not in status_out


def test_git_push_csrf_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Foreign Origin → 403 from the CSRF middleware (v0.4.5.1)."""
    _setup(tmp_path, monkeypatch)
    client = _client(tmp_path)
    resp = client.post(
        "/api/projects/proj/git/push",
        headers={"Origin": "http://evil.example"},
    )
    assert resp.status_code == 403


def test_git_push_409_when_not_initialised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project exists but hasn't been ``urika github init``'d → 409."""
    _setup_uninitialised(tmp_path, monkeypatch)
    client = _client(tmp_path)
    resp = client.post(
        "/api/projects/proj/git/push",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 409
    assert "not a git repo" in resp.json()["detail"].lower()


def test_git_push_unknown_project_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Empty registry — the project doesn't exist.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    (tmp_path / "projects").mkdir()
    client = _client(tmp_path)
    resp = client.post(
        "/api/projects/no-such/git/push",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 404
