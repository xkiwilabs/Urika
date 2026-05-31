"""Tests for ``POST /api/projects/{name}/git/init`` (v0.6.0 Task 3.3).

The dashboard's ``init`` endpoint accepts ONLY ``remote=<URL>``.
``--create`` is CLI-only for v0.6 because it shells out to ``gh``,
which isn't reliably available in the dashboard process's env.

Mirrors the URIKA_HOME monkeypatch + ``create_app(project_root=...)``
pattern used in ``test_api_git_status.py`` so the registry is isolated
from the real ``~/.urika``. All state-changing requests carry
``Origin: http://testserver`` to satisfy the v0.4.5.1 CSRF origin guard.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
    """Register a project ``proj`` (NOT git-initialised).

    Returns ``(project_dir, project_root)`` — ``project_root`` is the
    directory passed to ``create_app(project_root=...)``.
    """
    proj_root = tmp_path / "projects"
    proj_root.mkdir()
    proj = _make_project(proj_root, "proj")
    home = tmp_path / "home"
    monkeypatch.setenv("URIKA_HOME", str(home))
    _register(home, "proj", proj)
    return proj, proj_root


def _client(proj_root: Path) -> TestClient:
    app = create_app(project_root=proj_root, auth_token=None)
    return TestClient(app)


def test_git_init_with_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj, proj_root = _setup(tmp_path, monkeypatch)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    client = _client(proj_root)
    resp = client.post(
        "/api/projects/proj/git/init",
        data={"remote": str(remote)},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert (proj / ".git").is_dir()
    url = subprocess.run(
        ["git", "-C", str(proj), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert url == str(remote)
    # Initial commit landed.
    log = subprocess.run(
        ["git", "-C", str(proj), "log", "--oneline"],
        capture_output=True,
        text=True,
    ).stdout
    assert "urika:" in log.lower()


def test_git_init_create_not_supported_via_dashboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``create=true`` returns 400 pointing user to the CLI."""
    _proj, proj_root = _setup(tmp_path, monkeypatch)
    client = _client(proj_root)
    resp = client.post(
        "/api/projects/proj/git/init",
        data={"create": "true"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"].lower()
    assert "cli" in detail
    assert "--create" in detail


def test_git_init_missing_remote_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No remote AND no create → 400."""
    _proj, proj_root = _setup(tmp_path, monkeypatch)
    client = _client(proj_root)
    resp = client.post(
        "/api/projects/proj/git/init",
        data={},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 400
    assert "remote" in resp.json()["detail"].lower()


def test_git_init_unknown_project_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    # Empty registry — the project doesn't exist.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    proj_root = tmp_path / "projects"
    proj_root.mkdir()
    client = _client(proj_root)
    resp = client.post(
        "/api/projects/no-such/git/init",
        data={"remote": str(remote)},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 404


def test_git_init_cross_origin_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Foreign Origin → 403 from the CSRF middleware (v0.4.5.1)."""
    _proj, proj_root = _setup(tmp_path, monkeypatch)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    client = _client(proj_root)
    resp = client.post(
        "/api/projects/proj/git/init",
        data={"remote": str(remote)},
        headers={"Origin": "http://evil.example"},
    )
    assert resp.status_code == 403
