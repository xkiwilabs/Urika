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


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string like '0.2.1' into a tuple."""
    v = v.lstrip("v").strip()
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    return tuple(parts) if parts else (0,)


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


def format_update_message(info: dict) -> str:
    """Format a user-friendly update notification."""
    return (
        f"Update available: v{info['current']} → "
        f"v{info['latest']}  "
        f"(git pull or pip install -e .)"
    )
