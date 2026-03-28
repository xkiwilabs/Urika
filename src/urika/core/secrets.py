"""Credential store at ~/.urika/secrets.env.

Simple KEY=VALUE file loaded into os.environ at CLI startup. File is
created with mode 0o600 (owner-only) and never committed to git.
"""

from __future__ import annotations

import os
from pathlib import Path

_SECRETS_PATH = Path.home() / ".urika" / "secrets.env"


def load_secrets() -> None:
    """Load ~/.urika/secrets.env into os.environ.

    Only sets variables that are not already set in the environment
    (existing env vars take precedence). Silently skips if file
    doesn't exist.
    """
    if not _SECRETS_PATH.exists():
        return
    try:
        for line in _SECRETS_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Remove surrounding quotes if present
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            # Don't override existing env vars
            if key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass  # Silently ignore read errors


def save_secret(key: str, value: str) -> None:
    """Save or update a single key in secrets.env.

    Creates the file if it doesn't exist. Sets chmod 600.
    """
    _SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    found = False
    if _SECRETS_PATH.exists():
        for line in _SECRETS_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                existing_key = stripped.partition("=")[0].strip()
                if existing_key == key:
                    lines.append(f"{key}={value}")
                    found = True
                    continue
            lines.append(line)

    if not found:
        lines.append(f"{key}={value}")

    _SECRETS_PATH.write_text("\n".join(lines) + "\n")
    _SECRETS_PATH.chmod(0o600)


def get_secret(key: str) -> str:
    """Get a secret value. Checks os.environ first, then secrets.env."""
    val = os.environ.get(key, "")
    if val:
        return val
    # Force reload from file
    load_secrets()
    return os.environ.get(key, "")


def list_secrets() -> dict[str, str]:
    """Return all keys in secrets.env (values masked)."""
    result: dict[str, str] = {}
    if not _SECRETS_PATH.exists():
        return result
    try:
        for line in _SECRETS_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key = line.partition("=")[0].strip()
            result[key] = "****"
    except Exception:
        pass
    return result
