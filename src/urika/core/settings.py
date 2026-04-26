"""Global user settings at ~/.urika/settings.toml.

These provide defaults for new projects. Users can override
per-project during `urika new` or by editing urika.toml.

Globals configure connection details and per-mode model defaults.
There is no system-wide default privacy mode — each project picks
its own mode at creation time and the loader live-inherits the
matching ``[runtime.modes.<mode>]`` block.

Example ~/.urika/settings.toml:

    [privacy.endpoints.private]
    base_url = "http://localhost:11434"
    api_key_env = ""

    [runtime.modes.open]
    model = "claude-opus-4-7"

    [runtime.modes.private]
    model = "qwen3:14b"

    [runtime.modes.hybrid]
    model = "claude-opus-4-7"

    [runtime.modes.hybrid.models.data_agent]
    model = "qwen3:14b"
    endpoint = "private"

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

    Returns endpoints only — there is no system default mode.  Each
    project picks its own mode at creation time (via ``urika new`` or
    POST /api/projects).  The returned dict has a single key,
    ``endpoints``, mapping endpoint names to ``{base_url, api_key_env}``
    dicts.
    """
    settings = load_settings()
    privacy = settings.get("privacy", {})
    return {"endpoints": privacy.get("endpoints", {})}


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


def get_default_notifications_auto_enable() -> dict[str, bool]:
    """For each channel, return whether new projects should auto-enable it.

    Read from ``[notifications.<channel>].auto_enable``. Defaults to
    ``False`` per channel when the flag is missing or no settings file
    exists. The flag is a creation-time hint only — the runtime
    notification loader does not consult it.
    """
    settings = load_settings()
    notif = settings.get("notifications", {})
    out: dict[str, bool] = {}
    for channel in ("email", "slack", "telegram"):
        ch_cfg = notif.get(channel, {})
        if not isinstance(ch_cfg, dict):
            ch_cfg = {}
        out[channel] = bool(ch_cfg.get("auto_enable", False))
    return out
