"""Privacy mode validation and endpoint checking."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def check_private_endpoint(project_dir: Path) -> tuple[bool, str]:
    """Check if the private endpoint is reachable.

    Returns (reachable, message).
    For open mode, always returns (True, "").
    For hybrid/private, pings the endpoint.
    """
    import tomllib

    toml_path = project_dir / "urika.toml"
    if not toml_path.exists():
        return True, ""

    try:
        with open(toml_path, "rb") as f:
            config = tomllib.load(f)
    except Exception:
        return True, ""

    privacy = config.get("privacy", {})
    mode = privacy.get("mode", "open")

    if mode == "open":
        return True, ""

    # Find the private endpoint URL
    endpoints = privacy.get("endpoints", {})
    private_ep = endpoints.get("private", {})
    base_url = private_ep.get("base_url", "")

    if not base_url:
        return False, f"No private endpoint configured for {mode} mode"

    # Ping the endpoint
    try:
        import urllib.error
        import urllib.request

        # Try /v1/models or just the base URL
        test_url = base_url.rstrip("/")
        if "/v1" not in test_url:
            test_url += "/v1/models"
        elif not test_url.endswith("/models"):
            test_url += "/models"

        req = urllib.request.Request(test_url, method="GET")
        urllib.request.urlopen(req, timeout=5)
        return True, f"Local model connected ({base_url})"
    except urllib.error.URLError:
        return False, f"Local model unreachable ({base_url})"
    except Exception as exc:
        return False, f"Local model check failed: {exc}"


def requires_private_endpoint(project_dir: Path) -> bool:
    """Check if this project requires a private endpoint (hybrid or private mode)."""
    import tomllib

    toml_path = project_dir / "urika.toml"
    if not toml_path.exists():
        return False
    try:
        with open(toml_path, "rb") as f:
            config = tomllib.load(f)
        mode = config.get("privacy", {}).get("mode", "open")
        return mode in ("hybrid", "private")
    except Exception:
        return False
