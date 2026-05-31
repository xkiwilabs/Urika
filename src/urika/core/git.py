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


_GITIGNORE_TEMPLATE = """\
# Urika internal state — never commit (secrets, sessions, meta)
.urika/
*.lock

# Python
__pycache__/
*.pyc
.venv/
venv/
.tox/

# Credentials / private keys (never commit, even if you remove other
# patterns from this list)
.env
*.pem
*.key
*_rsa
*_ed25519

# Research data — researcher-safe default exclusion. Remove the lines
# below (or override via [github] gitignore_extra in urika.toml) if
# your project's raw data is safe to commit.
data/raw/
*.parquet
*.h5
*.pkl
*.joblib
"""

_BLOCK_START = "# >>> urika: managed block — do not edit between markers >>>"
_BLOCK_END = "# <<< urika: managed block <<<"


def write_gitignore(project_dir: Path, extra_patterns: list[str] | None = None) -> None:
    """Write or update the project's ``.gitignore`` with researcher-safe defaults.

    Behaviour:
    - Fresh project: writes a new ``.gitignore`` containing the managed
      block (between BLOCK_START / BLOCK_END markers) and no other content.
    - Existing ``.gitignore`` without an Urika block: appends the
      managed block at the end, preserving user content.
    - Existing ``.gitignore`` WITH an Urika block: replaces the block
      in place, preserving content above and below it.

    ``extra_patterns`` are user-provided lines appended inside the
    managed block. Comes from ``[github] gitignore_extra`` in urika.toml.
    """
    extra = list(extra_patterns or [])
    block_lines = [_BLOCK_START, _GITIGNORE_TEMPLATE.rstrip("\n")]
    if extra:
        block_lines.append("\n# Extra patterns from urika.toml")
        block_lines.extend(extra)
    block_lines.append(_BLOCK_END)
    block = "\n".join(block_lines) + "\n"

    path = project_dir / ".gitignore"
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        return

    existing = path.read_text(encoding="utf-8")
    if _BLOCK_START in existing and _BLOCK_END in existing:
        # Replace the existing block in place.
        before, _, rest = existing.partition(_BLOCK_START)
        _old_block, _, after = rest.partition(_BLOCK_END)
        new_text = before.rstrip() + "\n\n" + block + after.lstrip()
        # Collapse runs of >=3 newlines that the slicing may have produced.
        while "\n\n\n" in new_text:
            new_text = new_text.replace("\n\n\n", "\n\n")
        path.write_text(new_text, encoding="utf-8")
    else:
        # Append the block at the end, preserving everything else.
        sep = "" if existing.endswith("\n") else "\n"
        path.write_text(existing + sep + "\n" + block, encoding="utf-8")
