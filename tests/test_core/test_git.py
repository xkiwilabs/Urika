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


def test_write_gitignore_creates_new_file(tmp_path):
    from urika.core.git import write_gitignore

    write_gitignore(tmp_path)
    gitignore = (tmp_path / ".gitignore").read_text()
    # Researcher-safe defaults present:
    assert ".urika/" in gitignore
    assert "data/raw/" in gitignore
    assert "*.parquet" in gitignore
    assert "*.pem" in gitignore
    # Block markers present so we can find/replace later:
    assert "urika: managed block" in gitignore


def test_write_gitignore_preserves_user_content(tmp_path):
    from urika.core.git import write_gitignore

    pre = "# User's own patterns\n*.log\nbuild/\n"
    (tmp_path / ".gitignore").write_text(pre)
    write_gitignore(tmp_path)
    text = (tmp_path / ".gitignore").read_text()
    # User content survives
    assert "*.log" in text
    assert "build/" in text
    # Urika block appended
    assert ".urika/" in text
    assert "urika: managed block" in text


def test_write_gitignore_replaces_existing_block_in_place(tmp_path):
    from urika.core.git import write_gitignore

    initial = (
        "# user header\n"
        "*.log\n"
        "\n"
        "# >>> urika: managed block — do not edit between markers >>>\n"
        ".urika/\n"
        "# old-stale-pattern-from-a-prior-version\n"
        "# <<< urika: managed block <<<\n"
        "\n"
        "# user footer\n"
        "build/\n"
    )
    (tmp_path / ".gitignore").write_text(initial)
    write_gitignore(tmp_path)
    text = (tmp_path / ".gitignore").read_text()
    # User content above + below the block survives
    assert "# user header" in text
    assert "# user footer" in text
    assert "*.log" in text
    assert "build/" in text
    # Stale pattern from the old block is gone
    assert "old-stale-pattern-from-a-prior-version" not in text
    # New defaults present
    assert "data/raw/" in text
    # Exactly one block (not two)
    assert text.count("# >>> urika: managed block") == 1


def test_write_gitignore_honors_extra_patterns(tmp_path):
    from urika.core.git import write_gitignore

    write_gitignore(tmp_path, extra_patterns=["my_secrets.toml", "*.bak"])
    text = (tmp_path / ".gitignore").read_text()
    assert "my_secrets.toml" in text
    assert "*.bak" in text
