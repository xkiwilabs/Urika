"""Shared test fixtures."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _git_identity_for_subprocess_commits():
    """Give every `git commit` a default author/committer for CI runners.

    Tests under `tests/test_cli/test_github_*` and `tests/test_dashboard/test_*git*`
    run `git commit` via subprocess against repos created by `urika github init`,
    which deliberately doesn't write per-repo identity. Locally these tests rely
    on the developer's `~/.gitconfig`, but CI runners have no global identity, so
    `git` refuses with `fatal: empty ident name`. Setting these env vars (which
    git honors above the config lookup chain) keeps prod behavior unchanged while
    making the suite portable.
    """
    mp = pytest.MonkeyPatch()
    mp.setenv("GIT_AUTHOR_NAME", "Urika Tests")
    mp.setenv("GIT_AUTHOR_EMAIL", "tests@urika.local")
    mp.setenv("GIT_COMMITTER_NAME", "Urika Tests")
    mp.setenv("GIT_COMMITTER_EMAIL", "tests@urika.local")
    yield
    mp.undo()


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory with minimal structure."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def tmp_urika_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary ~/.urika directory and patch URIKA_HOME."""
    urika_home = tmp_path / ".urika"
    urika_home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(urika_home))
    return urika_home
