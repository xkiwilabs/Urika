"""Global user settings at ~/.urika/settings.toml.

These provide defaults for new projects. Users can override
per-project during `urika new` or by editing urika.toml.

Example ~/.urika/settings.toml:

    [privacy]
    mode = "private"

    [privacy.endpoints.private]
    base_url = "http://localhost:11434"
    api_key_env = ""

    [privacy.endpoints.university]
    base_url = "https://claude.myuni.edu/v1"
    api_key_env = "UNI_API_KEY"

    [runtime]
    model = "qwen3-coder"

    [preferences]
    web_search = false
    venv = true
    max_turns_per_experiment = 10
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from urika.core.registry import _urika_home


def _settings_path() -> Path:
    return _urika_home() / "settings.toml"


def load_settings() -> dict[str, Any]:
    """Load global settings. Returns empty dict if not configured."""
    import tomllib

    path = _settings_path()
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def save_settings(data: dict[str, Any]) -> None:
    """Save global settings to ~/.urika/settings.toml."""
    from urika.core.workspace import _write_toml

    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_toml(path, data)


def get_default_privacy() -> dict[str, Any]:
    """Get default privacy settings for new projects.

    Returns a dict with keys: mode, endpoints (dict of name -> {base_url, api_key_env}).
    """
    settings = load_settings()
    privacy = settings.get("privacy", {})
    return {
        "mode": privacy.get("mode", "open"),
        "endpoints": privacy.get("endpoints", {}),
    }


def get_default_runtime() -> dict[str, Any]:
    """Get default runtime settings for new projects."""
    settings = load_settings()
    runtime = settings.get("runtime", {})
    return {
        "model": runtime.get("model", ""),
        "backend": runtime.get("backend", "claude"),
    }


def get_default_preferences() -> dict[str, Any]:
    """Get default preferences for new projects."""
    settings = load_settings()
    return settings.get("preferences", {})
