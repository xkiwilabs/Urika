"""Check for new Urika releases on GitHub."""

from __future__ import annotations

import json
import time
from pathlib import Path


_CACHE_DIR = Path.home() / ".urika"
_CACHE_FILE = _CACHE_DIR / "update_cache.json"
_CHECK_INTERVAL = 86400  # 24 hours between checks
_REPO = "xkiwilabs/Urika"


def _installed_version() -> str:
    """Get the currently installed version."""
    try:
        from importlib.metadata import version

        return version("urika")
    except Exception:
        return "0.0.0"


def _parse_version(v: str) -> "Version":
    """Parse a version string like '0.2.1' or 'v0.4.0rc1' into a comparable
    :class:`packaging.version.Version`.

    Pre-v0.4.2 used a hand-rolled tuple parser that ``break``ed on the
    first non-int token: ``"0.4.0rc1".split(".")`` → ``["0","4","0rc1"]``,
    ``int("0rc1")`` raised, and the parser returned ``(0, 4)`` — so
    ``"0.4.0rc1"`` was treated as *less than* ``"0.4.0"``, defeating
    pre-release ordering. ``packaging.version.Version`` understands
    PEP 440 (alpha/beta/rc/dev) so the comparison is correct.

    Returns the lowest comparable Version (``0.0.0``) for inputs that
    even ``packaging`` can't parse, preserving the prior contract that
    update checks never crash the CLI on a malformed tag.
    """
    from packaging.version import InvalidVersion, Version

    v = v.lstrip("v").strip()
    if not v:
        return Version("0.0.0")
    try:
        return Version(v)
    except InvalidVersion:
        return Version("0.0.0")


# Re-export so the type hint above resolves without an import-time
# circular dependency.
from packaging.version import Version  # noqa: E402


def _load_cache() -> dict:
    """Load cached update check result."""
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(data: dict) -> None:
    """Save update check result to cache."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def check_for_updates(*, force: bool = False) -> dict | None:
    """Check GitHub for a newer release.

    Returns a dict with 'latest', 'current', 'update_available'
    if an update is found. Returns None if up-to-date or check
    fails. Uses a 24-hour cache to avoid repeated network calls.
    """
    current = _installed_version()

    # Check cache first (unless forced)
    if not force:
        cache = _load_cache()
        last_check = cache.get("checked_at", 0)
        if time.time() - last_check < _CHECK_INTERVAL:
            if cache.get("update_available"):
                return {
                    "latest": cache["latest"],
                    "current": current,
                    "update_available": True,
                }
            return None

    # Fetch latest release from GitHub API
    latest = _fetch_latest_release()
    if latest is None:
        return None

    update_available = _parse_version(latest) > _parse_version(current)

    # Cache result
    _save_cache(
        {
            "latest": latest,
            "current": current,
            "update_available": update_available,
            "checked_at": time.time(),
        }
    )

    if update_available:
        return {
            "latest": latest,
            "current": current,
            "update_available": True,
        }
    return None


def _fetch_latest_release() -> str | None:
    """Fetch latest release tag from GitHub API.

    Uses urllib to avoid external dependencies. Times out after
    3 seconds to avoid blocking the CLI/REPL startup.
    """
    import urllib.request
    import urllib.error

    url = f"https://api.github.com/repos/{_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "urika-update-check",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            return data.get("tag_name", "")
    except Exception:
        # Also try tags endpoint (works if no "releases" exist)
        try:
            tags_url = f"https://api.github.com/repos/{_REPO}/tags?per_page=1"
            tags_req = urllib.request.Request(
                tags_url,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "urika-update-check",
                },
            )
            with urllib.request.urlopen(tags_req, timeout=3) as resp:
                tags = json.loads(resp.read())
                if tags:
                    return tags[0].get("name", "")
        except Exception:
            pass
    return None


def _strip_v_prefix(version: str) -> str:
    """Strip a leading 'v' from a version string. GitHub tags are 'v0.3.0';
    pyproject + parsed versions are '0.3.0'."""
    return version[1:] if version.startswith("v") else version


def format_update_message(info: dict) -> str:
    """Format a user-friendly update notification."""
    current = _strip_v_prefix(str(info.get("current", "")))
    latest = _strip_v_prefix(str(info.get("latest", "")))
    return f"Update available: v{current} → v{latest}  (git pull or pip install -e .)"
