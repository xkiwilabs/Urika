"""Unit tests for urika.core.git.

All tests run against tmp_path with no network or GitHub access.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(cwd: Path, *args: str) -> str:
    """Helper: shell out to git for test setup/inspection (NOT for the SUT)."""
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def test_is_git_repo_false_for_plain_dir(tmp_path):
    from urika.core.git import is_git_repo

    assert is_git_repo(tmp_path) is False


def test_is_git_repo_true_after_init(tmp_path):
    from urika.core.git import is_git_repo

    _run_git(tmp_path, "init", "-q")
    assert is_git_repo(tmp_path) is True


def test_init_repo_creates_dotgit(tmp_path):
    from urika.core.git import init_repo, is_git_repo

    init_repo(tmp_path)
    assert (tmp_path / ".git").is_dir()
    assert is_git_repo(tmp_path) is True


def test_init_repo_idempotent(tmp_path):
    from urika.core.git import init_repo, is_git_repo

    init_repo(tmp_path)
    init_repo(tmp_path)  # second call must not raise
    assert is_git_repo(tmp_path) is True


def test_add_remote_sets_url(tmp_path):
    from urika.core.git import init_repo, add_remote

    init_repo(tmp_path)
    add_remote(tmp_path, "https://example.com/repo.git")
    out = _run_git(tmp_path, "remote", "get-url", "origin")
    assert out.strip() == "https://example.com/repo.git"


def test_add_remote_replaces_existing(tmp_path):
    from urika.core.git import init_repo, add_remote

    init_repo(tmp_path)
    add_remote(tmp_path, "https://example.com/old.git")
    add_remote(tmp_path, "https://example.com/new.git")
    out = _run_git(tmp_path, "remote", "get-url", "origin")
    assert out.strip() == "https://example.com/new.git"


def test_add_remote_custom_name(tmp_path):
    from urika.core.git import init_repo, add_remote

    init_repo(tmp_path)
    add_remote(tmp_path, "https://example.com/upstream.git", name="upstream")
    out = _run_git(tmp_path, "remote", "get-url", "upstream")
    assert out.strip() == "https://example.com/upstream.git"
