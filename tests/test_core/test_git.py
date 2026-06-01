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
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
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
    (tmp_path / ".gitignore").write_text(pre, encoding="utf-8")
    write_gitignore(tmp_path)
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
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
    (tmp_path / ".gitignore").write_text(initial, encoding="utf-8")
    write_gitignore(tmp_path)
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
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
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "my_secrets.toml" in text
    assert "*.bak" in text


def _make_bare_remote(tmp_path) -> Path:
    """Create a bare git repo at tmp_path/remote.git suitable as `origin`."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    return remote


def _setup_work_repo(tmp_path) -> Path:
    """Create a non-bare repo with a remote configured, ready for commit/push."""
    from urika.core.git import init_repo, add_remote, write_gitignore

    work = tmp_path / "work"
    work.mkdir()
    init_repo(work)
    # Identity (CI / fresh tmp dirs have no global git config)
    subprocess.run(
        ["git", "-C", str(work), "config", "user.email", "test@urika"], check=True
    )
    subprocess.run(["git", "-C", str(work), "config", "user.name", "test"], check=True)
    remote = _make_bare_remote(tmp_path)
    add_remote(work, str(remote))
    write_gitignore(work)
    return work


def test_commit_all_creates_commit(tmp_path):
    from urika.core.git import commit_all

    work = _setup_work_repo(tmp_path)
    (work / "hello.txt").write_text("world")
    result = commit_all(work, message="initial")
    assert result.ok is True
    assert result.sha is not None and len(result.sha) >= 7
    out = _run_git(work, "log", "--oneline")
    assert "initial" in out


def test_commit_all_returns_ok_false_when_nothing_to_commit(tmp_path):
    from urika.core.git import commit_all

    work = _setup_work_repo(tmp_path)
    # First commit succeeds (adds .gitignore)
    first = commit_all(work, message="initial")
    assert first.ok is True
    # Second with no changes returns ok=False with a clear reason.
    second = commit_all(work, message="empty")
    assert second.ok is False
    assert "nothing to commit" in (second.error or "").lower()


def test_push_succeeds_to_local_bare_remote(tmp_path):
    from urika.core.git import commit_all, push

    work = _setup_work_repo(tmp_path)
    (work / "f.txt").write_text("x")
    commit_all(work, message="initial")
    result = push(work)
    assert result.ok is True
    # Confirm the remote sees the commit
    remote = tmp_path / "remote.git"
    out = subprocess.run(
        ["git", "-C", str(remote), "log", "--oneline"], capture_output=True, text=True
    ).stdout
    assert "initial" in out


def test_push_failure_returns_error(tmp_path):
    """Push to a nonexistent remote returns ok=False with stderr."""
    from urika.core.git import init_repo, add_remote, commit_all, push

    work = tmp_path / "work"
    work.mkdir()
    init_repo(work)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True)
    add_remote(work, "/nonexistent/path/that/does/not/exist.git")
    (work / "a.txt").write_text("a")
    commit_all(work, message="x")
    result = push(work)
    assert result.ok is False
    assert result.error  # non-empty stderr from git


def test_pull_ff_only_succeeds_when_local_clean(tmp_path):
    from urika.core.git import commit_all, push, pull

    work = _setup_work_repo(tmp_path)
    (work / "a.txt").write_text("a")
    commit_all(work, message="first")
    push(work)
    # Simulate a remote commit landing (clone, commit, push)
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(tmp_path / "remote.git"), str(clone)], check=True
    )
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    (clone / "b.txt").write_text("b")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-m", "second"], check=True)
    subprocess.run(["git", "-C", str(clone), "push"], check=True)
    # Now pull from the original work tree
    result = pull(work)
    assert result.ok is True
    assert (work / "b.txt").exists()


def test_status_returns_dirty_count_and_branch(tmp_path):
    from urika.core.git import commit_all, status

    work = _setup_work_repo(tmp_path)
    commit_all(work, message="initial")  # need a commit so HEAD exists
    (work / "untracked.txt").write_text("x")
    (work / "modified.txt").write_text("a")
    subprocess.run(["git", "-C", str(work), "add", "modified.txt"], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "add modified"], check=True)
    (work / "modified.txt").write_text("changed")
    st = status(work)
    assert st.branch  # non-empty (whatever the default is — main / master)
    assert st.dirty_count >= 2  # untracked + modified


def test_recent_commits_returns_list(tmp_path):
    from urika.core.git import commit_all, recent_commits

    work = _setup_work_repo(tmp_path)
    (work / "a.txt").write_text("a")
    commit_all(work, message="urika: first\n\nurika-event: experiment_complete")
    (work / "b.txt").write_text("b")
    commit_all(work, message="urika: second\n\nurika-event: finalize_complete")
    commits = recent_commits(work, limit=10)
    assert len(commits) == 2
    # Most recent first
    assert "second" in commits[0].subject
    assert commits[0].event == "finalize_complete"
    assert commits[1].event == "experiment_complete"
