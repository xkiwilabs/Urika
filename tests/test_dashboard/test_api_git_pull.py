"""Tests for ``POST /api/projects/{name}/git/pull`` (v0.7.1 parity sweep).

The pull endpoint mirrors ``urika github pull`` CLI semantics: fetch +
fast-forward-only merge from origin, refusing on divergence. Mirrors the
``test_api_git_push.py`` setup (URIKA_HOME monkeypatch +
``create_app(project_root=...)`` + a bare remote initialised via the CLI)
so the registry is isolated from the real ``~/.urika``.

All state-changing requests carry ``Origin: http://testserver`` to satisfy
the v0.4.5.1 CSRF origin guard. Cross-origin POSTs are exercised in
``test_git_pull_csrf_rejection`` to confirm the guard is wired up.
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


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def test_git_pull_succeeds_with_new_remote_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit landed on the remote by another clone is fast-forwarded
    into the project working tree."""
    proj, remote = _setup(tmp_path, monkeypatch)
    # Publish the project's branch to the remote first.
    _git(proj, "push", "origin", "HEAD")
    branch = _git(proj, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    # Second clone adds a commit and pushes it.
    other = tmp_path / "other-clone"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(other)],
        check=True,
        capture_output=True,
    )
    _git(other, "checkout", "-q", branch)
    (other / "from-elsewhere.txt").write_text("hello")
    _git(other, "add", "-A")
    _git(
        other,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "-m",
        "remote work",
    )
    _git(other, "push", "-q", "origin", branch)

    client = _client(tmp_path)
    resp = client.post(
        "/api/projects/proj/git/pull",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["error"] is None
    # The remote commit landed in the project working tree.
    assert (proj / "from-elsewhere.txt").exists()


def test_git_pull_calls_core_helper_and_returns_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The endpoint routes through ``urika.core.git.pull`` (single source
    of truth, same helper the CLI uses) and serialises its result."""
    proj, _remote = _setup(tmp_path, monkeypatch)

    from urika.core import git as git_module
    from urika.core.git import PullResult

    calls: list[Path] = []

    def fake_pull(project_dir, remote="origin"):
        calls.append(project_dir)
        return PullResult(ok=True, error=None)

    monkeypatch.setattr(git_module, "pull", fake_pull)

    client = _client(tmp_path)
    resp = client.post(
        "/api/projects/proj/git/pull",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "error": None}
    assert calls == [proj]


def test_git_pull_reports_failure_in_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed pull (e.g. divergence) surfaces as 200 + ok=False with
    the verbatim git error — same envelope shape as /git/push."""
    _setup(tmp_path, monkeypatch)

    from urika.core import git as git_module
    from urika.core.git import PullResult

    monkeypatch.setattr(
        git_module,
        "pull",
        lambda project_dir, remote="origin": PullResult(
            ok=False, error="fatal: Not possible to fast-forward, aborting."
        ),
    )

    client = _client(tmp_path)
    resp = client.post(
        "/api/projects/proj/git/pull",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is False
    assert "fast-forward" in data["error"]


def test_git_pull_csrf_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Foreign Origin → 403 from the CSRF middleware (v0.4.5.1)."""
    _setup(tmp_path, monkeypatch)
    client = _client(tmp_path)
    resp = client.post(
        "/api/projects/proj/git/pull",
        headers={"Origin": "http://evil.example"},
    )
    assert resp.status_code == 403


def test_git_pull_requires_auth_token_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``auth_token`` configured, a POST without the Bearer header
    is rejected before the handler runs."""
    _setup(tmp_path, monkeypatch)
    app = create_app(project_root=tmp_path / "projects", auth_token="secret-token")
    client = TestClient(app)
    resp = client.post(
        "/api/projects/proj/git/pull",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 401


def test_git_pull_409_when_not_initialised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project exists but hasn't been ``urika github init``'d → 409."""
    _setup_uninitialised(tmp_path, monkeypatch)
    client = _client(tmp_path)
    resp = client.post(
        "/api/projects/proj/git/pull",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 409
    assert "not a git repo" in resp.json()["detail"].lower()


def test_git_pull_unknown_project_404(
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
        "/api/projects/no-such/git/pull",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 404
