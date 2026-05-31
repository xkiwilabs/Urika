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

import re
import subprocess
from dataclasses import dataclass
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


@dataclass
class CommitResult:
    ok: bool
    sha: str | None = None
    error: str | None = None


@dataclass
class PushResult:
    ok: bool
    pushed_sha: str | None = None
    error: str | None = None


@dataclass
class PullResult:
    ok: bool
    error: str | None = None


@dataclass
class GitStatus:
    branch: str
    dirty_count: int
    remote_url: str | None
    last_commit_sha: str | None
    last_commit_subject: str | None


@dataclass
class GitCommit:
    sha: str
    subject: str
    event: str | None  # populated from ``urika-event:`` trailer when present
    ts: str  # ISO 8601


def commit_all(project_dir: Path, message: str) -> CommitResult:
    """Stage everything and create a commit. Returns ok=False if there's
    nothing to commit (clean working tree)."""
    _git(project_dir, "add", "-A")
    # Detect "nothing to commit" without raising.
    diff = _git(project_dir, "diff", "--cached", "--name-only", check=False)
    if diff.returncode == 0 and not diff.stdout.strip():
        return CommitResult(ok=False, error="nothing to commit (working tree clean)")
    result = _git(project_dir, "commit", "-m", message, check=False)
    if result.returncode != 0:
        return CommitResult(
            ok=False, error=result.stderr.strip() or result.stdout.strip()
        )
    sha = _git(project_dir, "rev-parse", "HEAD").stdout.strip()
    return CommitResult(ok=True, sha=sha[:12])


def push(project_dir: Path, remote: str = "origin") -> PushResult:
    """Push current branch to *remote*. ok=False with verbatim git stderr on failure."""
    result = _git(project_dir, "push", remote, "HEAD", check=False)
    if result.returncode != 0:
        return PushResult(ok=False, error=(result.stderr or result.stdout).strip())
    sha = _git(project_dir, "rev-parse", "HEAD").stdout.strip()
    return PushResult(ok=True, pushed_sha=sha[:12])


def pull(project_dir: Path, remote: str = "origin") -> PullResult:
    """Fetch + ff-only merge from *remote*. Refuses on divergence.

    Fetches the current branch explicitly so FETCH_HEAD is marked
    for-merge even when no upstream tracking is configured.
    """
    branch = _git(project_dir, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    if branch.returncode != 0 or not branch.stdout.strip():
        return PullResult(ok=False, error=(branch.stderr or branch.stdout).strip())
    branch_name = branch.stdout.strip()
    fetch = _git(project_dir, "fetch", remote, branch_name, check=False)
    if fetch.returncode != 0:
        return PullResult(ok=False, error=(fetch.stderr or fetch.stdout).strip())
    merge = _git(project_dir, "merge", "--ff-only", "FETCH_HEAD", check=False)
    if merge.returncode != 0:
        return PullResult(ok=False, error=(merge.stderr or merge.stdout).strip())
    return PullResult(ok=True)


def status(project_dir: Path) -> GitStatus:
    """Snapshot of current branch, dirty file count, remote URL, last commit."""
    branch = _git(project_dir, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    branch_name = branch.stdout.strip() if branch.returncode == 0 else ""
    porcelain = _git(project_dir, "status", "--porcelain", check=False)
    dirty = (
        len([line for line in porcelain.stdout.splitlines() if line.strip()])
        if porcelain.returncode == 0
        else 0
    )
    remote = _git(project_dir, "remote", "get-url", "origin", check=False)
    remote_url = remote.stdout.strip() if remote.returncode == 0 else None
    last = _git(project_dir, "log", "-1", "--format=%H%n%s", check=False)
    last_sha = None
    last_subject = None
    if last.returncode == 0 and last.stdout.strip():
        parts = last.stdout.strip().split("\n", 1)
        last_sha = parts[0][:12]
        last_subject = parts[1] if len(parts) > 1 else ""
    return GitStatus(
        branch=branch_name,
        dirty_count=dirty,
        remote_url=remote_url,
        last_commit_sha=last_sha,
        last_commit_subject=last_subject,
    )


def recent_commits(project_dir: Path, limit: int = 10) -> list[GitCommit]:
    """Last *limit* commits, newest first. Parses ``urika-event:`` from the body."""
    fmt = "%H%x00%s%x00%aI%x00%b%x1e"  # NUL-separated fields, RS-separated records
    out = _git(
        project_dir,
        "log",
        f"-{limit}",
        f"--format={fmt}",
        check=False,
    )
    if out.returncode != 0 or not out.stdout.strip():
        return []
    commits: list[GitCommit] = []
    for rec in out.stdout.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        fields = rec.split("\x00")
        if len(fields) < 4:
            continue
        sha, subject, ts, body = fields[0], fields[1], fields[2], fields[3]
        event = None
        for line in body.splitlines():
            if line.startswith("urika-event:"):
                event = line.split(":", 1)[1].strip()
                break
        commits.append(GitCommit(sha=sha[:12], subject=subject, event=event, ts=ts))
    return commits


@dataclass
class SecretMatch:
    file: str
    line: int
    pattern_name: str
    preview: str  # masked: first 8 + last 4 chars of the matched token


# Patterns ordered most-specific first so e.g. ``sk-ant-`` doesn't get
# overshadowed by the generic ``sk-`` openai pattern.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{32,}")),
    ("github_pat", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("github_oauth", re.compile(r"gho_[A-Za-z0-9]{36}")),
    ("github_user_to_server", re.compile(r"ghu_[A-Za-z0-9]{36}")),
    ("github_server_to_server", re.compile(r"ghs_[A-Za-z0-9]{36}")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # OpenAI-shape last because ``sk-ant-`` would also match a permissive
    # ``sk-...{40,}`` pattern. The earlier anthropic entry will be tried
    # first and reported as ``anthropic_api_key``.
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{40,}\b")),
]


def _mask_token(token: str) -> str:
    """Return a masked preview: first 8 chars + ``...`` + last 4."""
    if len(token) <= 12:
        return token  # too short to mask meaningfully
    return f"{token[:8]}...{token[-4:]}"


def _is_binary(content: bytes) -> bool:
    """Heuristic: contains a NUL byte in the first 8KB -> binary."""
    return b"\x00" in content[:8192]


def scan_for_secrets(project_dir: Path) -> list[SecretMatch]:
    """Scan staged files for known secret patterns.

    Reads each staged file's CONTENT (``git show :<path>``) rather than
    the working-tree version, so a secret that the user has since
    removed locally but already staged is still caught.

    Returns a list of :class:`SecretMatch` (empty when clean). Binary
    files are skipped - random bytes can match a regex by chance, and
    we don't want to waste time on PNGs.
    """
    staged = _git(project_dir, "diff", "--cached", "--name-only", check=False)
    if staged.returncode != 0:
        return []
    matches: list[SecretMatch] = []
    for path in staged.stdout.splitlines():
        path = path.strip()
        if not path:
            continue
        # Read the staged blob as raw bytes so binary content doesn't blow
        # up the utf-8 decoder. The text-mode ``_git`` helper would raise
        # ``UnicodeDecodeError`` on PNG/parquet bytes here.
        blob = subprocess.run(
            ["git", "show", f":{path}"],
            cwd=str(project_dir),
            capture_output=True,
            check=False,
        )
        if blob.returncode != 0:
            continue
        raw_bytes = blob.stdout
        if _is_binary(raw_bytes):
            continue
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = raw_bytes.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern_name, pattern in _SECRET_PATTERNS:
                for m in pattern.finditer(line):
                    matches.append(
                        SecretMatch(
                            file=path,
                            line=lineno,
                            pattern_name=pattern_name,
                            preview=_mask_token(m.group(0)),
                        )
                    )
                    break  # one match per line is enough; the user gets the file:line
    return matches
