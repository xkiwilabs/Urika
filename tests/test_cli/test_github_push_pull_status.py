"""Tests for ``urika github push / status / pull`` (v0.6.0 Task 2.3).

These CLI sub-commands operate on a project that has already been
``urika github init``'d. The ``push`` flow runs the secret scanner
before committing — a detected secret aborts with exit code 3, leaving
the working tree un-staged.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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


def _git_init_project(project_dir: Path, remote: Path | None = None) -> None:
    """Run ``urika github init`` for the project, optionally with a remote."""
    args = ["github", "init", "proj"]
    if remote is not None:
        args += ["--remote", str(remote)]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output


def test_github_status_after_init(tmp_path: Path, monkeypatch) -> None:
    """``urika github status`` prints branch + remote + dirty count after init."""
    proj = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)
    _git_init_project(proj, remote=remote)

    result = CliRunner().invoke(cli, ["github", "status", "proj"])
    assert result.exit_code == 0, result.output
    assert "branch:" in result.output
    assert "remote:" in result.output
    assert str(remote) in result.output
    assert "uncommitted:" in result.output


def test_github_push_clean_tree(tmp_path: Path, monkeypatch) -> None:
    """``urika github push`` succeeds to a local bare remote when tree is clean."""
    proj = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)
    _git_init_project(proj, remote=remote)

    result = CliRunner().invoke(cli, ["github", "push", "proj"])
    assert result.exit_code == 0, result.output
    assert "pushed" in result.output.lower()

    # Verify the bare remote actually has at least one ref now.
    refs = subprocess.run(
        ["git", "--git-dir", str(remote), "for-each-ref"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert refs, "bare remote received no refs"


def test_github_push_aborts_on_secret(tmp_path: Path, monkeypatch) -> None:
    """``urika github push`` aborts with exit code 3 when a secret is staged."""
    proj = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)
    _git_init_project(proj, remote=remote)

    # Drop a fake-but-pattern-matching anthropic key into a file.
    secret_file = proj / "leak.txt"
    secret_file.write_text(
        "API_KEY = 'sk-ant-api03-1234567890abcdefghijklmnopqrstuvwx'\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["github", "push", "proj"])
    assert result.exit_code == 3, result.output
    assert "[urika:secret-detected]" in result.output
    assert "leak.txt" in result.output

    # The remote must not have received the leaked commit.
    log = subprocess.run(
        ["git", "--git-dir", str(remote), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "leak" not in log.lower()

    # Working tree should have been un-staged so the user can fix things.
    diff_cached = subprocess.run(
        ["git", "-C", str(proj), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert "leak.txt" not in diff_cached


def test_github_push_unreachable_remote(tmp_path: Path, monkeypatch) -> None:
    """``urika github push`` to an unreachable remote returns nonzero + stderr."""
    proj = _setup(tmp_path, monkeypatch)
    bogus = tmp_path / "does-not-exist.git"
    _git_init_project(proj, remote=bogus)

    result = CliRunner().invoke(cli, ["github", "push", "proj"])
    assert result.exit_code != 0, result.output
    # Some hint that the push failed should surface.
    assert "failed" in result.output.lower() or "fatal" in result.output.lower()


def test_github_pull_ff_from_remote(tmp_path: Path, monkeypatch) -> None:
    """``urika github pull`` succeeds when the remote is ahead of local."""
    proj = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)
    _git_init_project(proj, remote=remote)

    # Push the initial state so the bare remote has the same starting commit.
    push_result = CliRunner().invoke(cli, ["github", "push", "proj"])
    assert push_result.exit_code == 0, push_result.output

    # Clone the bare remote in a sibling dir, add a commit, push it back.
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(clone)],
        check=True,
    )
    # Give the clone a user identity so commit doesn't fail in CI sandboxes.
    subprocess.run(
        ["git", "-C", str(clone), "config", "user.email", "ci@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(clone), "config", "user.name", "ci"],
        check=True,
    )
    (clone / "hello.txt").write_text("hello from clone\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(clone), "add", "hello.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(clone), "commit", "-q", "-m", "from clone"],
        check=True,
    )
    subprocess.run(["git", "-C", str(clone), "push", "-q"], check=True)

    # Now pull from the original project — should ff-merge the new commit.
    result = CliRunner().invoke(cli, ["github", "pull", "proj"])
    assert result.exit_code == 0, result.output
    assert (proj / "hello.txt").exists()
