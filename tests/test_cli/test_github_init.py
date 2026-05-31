"""Tests for ``urika github init`` (v0.6.0 Tasks 2.1 + 2.2).

The CLI sub-command initialises a project as a git repo, writes the
researcher-safe ``.gitignore`` managed block, optionally configures the
remote, and creates the initial commit. The ``--create`` flag shells
out to ``gh repo create`` (via :func:`urika.core.git.gh_create_repo`)
and falls back gracefully when ``gh`` is missing or unauthenticated.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from urika.cli import cli
from urika.core.models import ProjectConfig
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace


def _setup(tmp_path: Path, monkeypatch) -> Path:
    """Register a project named ``proj`` rooted at ``tmp_path/proj``."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    project_dir = tmp_path / "proj"
    config = ProjectConfig(
        name="proj",
        question="q",
        mode="exploratory",
        data_paths=[],
    )
    create_project_workspace(project_dir, config)
    ProjectRegistry().register("proj", project_dir)
    return project_dir


def _make_bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    return remote


def test_github_init_no_remote_writes_gitignore(tmp_path: Path, monkeypatch) -> None:
    """``urika github init <project>`` with no --remote: init the repo, write
    the .gitignore managed block, create the initial commit. No remote
    configured."""
    proj = _setup(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["github", "init", "proj"])
    assert result.exit_code == 0, result.output
    assert (proj / ".git").is_dir()
    assert (proj / ".gitignore").exists()
    # Initial commit landed.
    log = subprocess.run(
        ["git", "-C", str(proj), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "urika: initial" in log.lower()


def test_github_init_with_remote(tmp_path: Path, monkeypatch) -> None:
    """--remote sets origin to the given URL."""
    proj = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)

    result = CliRunner().invoke(
        cli, ["github", "init", "proj", "--remote", str(remote)]
    )
    assert result.exit_code == 0, result.output
    url = subprocess.run(
        ["git", "-C", str(proj), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert url == str(remote)


def test_github_init_idempotent(tmp_path: Path, monkeypatch) -> None:
    """Running ``urika github init`` twice is safe — the second run exits 0
    and reports that there's nothing new to commit."""
    _setup(tmp_path, monkeypatch)

    CliRunner().invoke(cli, ["github", "init", "proj"])
    result = CliRunner().invoke(cli, ["github", "init", "proj"])
    assert result.exit_code == 0, result.output


def test_github_init_unknown_project_exits_nonzero(tmp_path: Path, monkeypatch) -> None:
    """An unregistered project name must exit non-zero."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    result = CliRunner().invoke(cli, ["github", "init", "no-such-project"])
    assert result.exit_code != 0


def test_github_init_create_invokes_gh(tmp_path: Path, monkeypatch) -> None:
    """--create with default visibility (private) invokes gh_create_repo correctly."""
    _setup(tmp_path, monkeypatch)

    from urika.core.git import GhCreateResult

    with patch(
        "urika.core.git.gh_create_repo",
        return_value=GhCreateResult(ok=True, repo_url="https://github.com/u/proj"),
    ) as spy:
        result = CliRunner().invoke(cli, ["github", "init", "proj", "--create"])
    assert result.exit_code == 0, result.output
    assert spy.called
    kwargs = spy.call_args.kwargs
    assert kwargs.get("public") is False
    assert kwargs.get("name") == "proj"


def test_github_init_create_public(tmp_path: Path, monkeypatch) -> None:
    """--create --public passes public=True."""
    _setup(tmp_path, monkeypatch)

    from urika.core.git import GhCreateResult

    with patch(
        "urika.core.git.gh_create_repo",
        return_value=GhCreateResult(ok=True, repo_url="https://github.com/u/proj"),
    ) as spy:
        CliRunner().invoke(cli, ["github", "init", "proj", "--create", "--public"])
    assert spy.call_args.kwargs.get("public") is True


def test_github_init_create_prints_install_hint_when_gh_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """When gh_create_repo returns ok=False with install_hint, exit 2 + show hint."""
    _setup(tmp_path, monkeypatch)

    from urika.core.git import GhCreateResult

    with patch(
        "urika.core.git.gh_create_repo",
        return_value=GhCreateResult(
            ok=False,
            error="gh CLI not found",
            install_hint="Install: brew install gh ...",
        ),
    ):
        result = CliRunner().invoke(cli, ["github", "init", "proj", "--create"])
    assert result.exit_code == 2  # usage / dependency error
    assert "gh CLI not found" in result.output
    assert "Install:" in result.output
