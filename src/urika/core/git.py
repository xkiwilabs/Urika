"""Pure ``git`` shell-out wrapper for the v0.6.0 GitHub auto-backup feature.

Design:

- All functions are stateless wrappers around the system ``git`` binary
  invoked via ``subprocess.run``. No in-memory state, no caching.
- Errors come back as values (boolean ``ok`` + ``error`` message in
  result dataclasses) rather than exceptions. Callers print remediation
  hints cleanly.
- The user's existing ``git`` auth (HTTPS+PAT, SSH key, gh-stored
  credential — anything that makes ``git push`` work in their shell)
  does all the authentication. Urika never sees a credential.

See ``dev/plans/2026-05-31-v0.6.0-github-design.md`` for the locked
design decisions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run ``git`` with ``cwd`` set to *cwd*. Returns the completed process.

    ``check=True`` (default) raises ``CalledProcessError`` on non-zero
    exit. Callers that want to inspect failures themselves pass
    ``check=False``.
    """
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
    )


def is_git_repo(project_dir: Path) -> bool:
    """True if *project_dir* contains a ``.git`` directory at its root."""
    return (project_dir / ".git").is_dir()


def init_repo(project_dir: Path) -> None:
    """Initialise *project_dir* as a git repo. Idempotent."""
    if is_git_repo(project_dir):
        return
    _git(project_dir, "init", "-q")


def add_remote(project_dir: Path, url: str, name: str = "origin") -> None:
    """Set the remote *name* to *url*. Creates if absent, updates if present."""
    result = _git(project_dir, "remote", "get-url", name, check=False)
    if result.returncode == 0:
        _git(project_dir, "remote", "set-url", name, url)
    else:
        _git(project_dir, "remote", "add", name, url)
