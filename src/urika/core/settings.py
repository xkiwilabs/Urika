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
    model = "claude-opus-4-6"

    [runtime.modes.private]
    model = "qwen3:14b"

    [runtime.modes.hybrid]
    model = "claude-opus-4-6"

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


def get_named_endpoints() -> list[dict[str, str]]:
    """Return every named endpoint defined in ``~/.urika/settings.toml``.

    Each element has shape ``{"name", "base_url", "api_key_env",
    "default_model"}``.  The ``default_model`` field is read from an
    optional ``[privacy.endpoints.<name>].default_model`` key — surfaced
    here so the dashboard can edit it; the runtime loader's per-endpoint
    fallback semantics live elsewhere.

    Reads ``[privacy.endpoints.<name>]``.  Order is sorted by name for
    deterministic UI rendering.  Returns ``[]`` when the settings file
    is missing, unparseable, or has no endpoints block.
    """
    settings = load_settings()
    privacy = settings.get("privacy", {})
    endpoints = privacy.get("endpoints", {})
    if not isinstance(endpoints, dict):
        return []
    out: list[dict[str, str]] = []
    for name in sorted(endpoints):
        cfg = endpoints[name]
        if not isinstance(cfg, dict):
            continue
        out.append(
            {
                "name": name,
                "base_url": cfg.get("base_url", ""),
                "api_key_env": cfg.get("api_key_env", ""),
                "default_model": cfg.get("default_model", ""),
            }
        )
    return out


def get_default_runtime(mode: str | None = None) -> dict[str, Any]:
    """Get default runtime settings for new projects.

    When *mode* is supplied, prefer the per-mode model from
    ``[runtime.modes.<mode>].model`` over the legacy flat
    ``[runtime].model`` key — this matches the canonical write path
    used by the dashboard's Models tab and the new CLI wizard. The
    flat key is kept as a fallback for users still on 0.2.x layouts.
    """
    settings = load_settings()
    runtime = settings.get("runtime", {})

    model: str = ""
    if mode:
        mode_cfg = (runtime.get("modes", {}) or {}).get(mode, {})
        if isinstance(mode_cfg, dict):
            model = mode_cfg.get("model", "") or ""
    if not model:
        model = runtime.get("model", "") or ""

    return {
        "model": model,
        "backend": runtime.get("backend", "claude"),
    }


def get_default_preferences() -> dict[str, Any]:
    """Get default preferences for new projects."""
    settings = load_settings()
    return settings.get("preferences", {})


# ── Migration ─────────────────────────────────────────────────────
#
# Settings written by the v0.3.0/0.3.1 dashboard form pinned every
# agent in open mode to ``claude-opus-4-7``. The bundled ``claude``
# CLI (claude-agent-sdk 0.1.45 ships v2.1.63) sends the deprecated
# ``thinking.type.enabled`` request shape that newer Anthropic models
# reject with HTTP 400, surfacing as the cryptic "Fatal error in
# message reader" symptom. v0.3.2 lowered the dashboard default to
# 4-6, but existing ~/.urika/settings.toml files keep 4-7 pinned and
# stay broken until the user manually re-saves the form. This
# one-shot migration detects 4-7 in any per-mode default or per-agent
# override slot, backs up the original to
# ``settings.toml.pre-0.3.2.bak``, and rewrites the broken positions
# to ``claude-opus-4-6`` (the new default) so users with a stale
# bundled CLI immediately get a working setup. Users who have the
# system ``claude`` CLI installed can re-pin 4-7 from the dashboard
# afterward — the runtime adapter prefers the system CLI on PATH
# (which speaks the current schema). Idempotent via a one-shot
# marker file.

_MIGRATION_MARKER = ".migrated_0.3.2"
_BROKEN_MODEL = "claude-opus-4-7"
_REPLACEMENT_MODEL = "claude-opus-4-6"


def _walk_4_7_pins(runtime: dict[str, Any]) -> int:
    """Return the count of ``claude-opus-4-7`` pins under ``[runtime]``.

    Used by :func:`migrate_settings` to decide whether the migration
    has anything to do; the same walk is used by the rewrite path.
    """
    count = 0
    modes = runtime.get("modes", {}) or {}
    if not isinstance(modes, dict):
        return 0
    for _mode_name, mode_cfg in modes.items():
        if not isinstance(mode_cfg, dict):
            continue
        if mode_cfg.get("model") == _BROKEN_MODEL:
            count += 1
        for _agent, agent_cfg in (mode_cfg.get("models", {}) or {}).items():
            if isinstance(agent_cfg, dict) and agent_cfg.get("model") == _BROKEN_MODEL:
                count += 1
    return count


def _rewrite_4_7_pins(runtime: dict[str, Any]) -> dict[str, Any]:
    """Return a new runtime dict with 4-7 pins rewritten to 4-6.

    Mutates a deep-copied structure to keep the input untouched.
    """
    import copy

    out = copy.deepcopy(runtime)
    modes = out.get("modes", {}) or {}
    for mode_cfg in modes.values():
        if not isinstance(mode_cfg, dict):
            continue
        if mode_cfg.get("model") == _BROKEN_MODEL:
            mode_cfg["model"] = _REPLACEMENT_MODEL
        for agent_cfg in (mode_cfg.get("models", {}) or {}).values():
            if isinstance(agent_cfg, dict) and agent_cfg.get("model") == _BROKEN_MODEL:
                agent_cfg["model"] = _REPLACEMENT_MODEL
    return out


def migrate_settings() -> None:
    """One-shot migration of stale 4-7 model pins on first load.

    Called from CLI startup (``cli._base.cli``) and dashboard startup
    (``dashboard.app``). Idempotent: a marker file at
    ``~/.urika/.migrated_0.3.2`` records that the migration has run
    and short-circuits subsequent calls. Safe to call repeatedly.

    On rewrite, the original file is backed up to
    ``settings.toml.pre-0.3.2.bak`` (only on the first rewrite — we
    never overwrite an existing backup) so the user can always recover
    their pre-migration values.
    """
    import logging
    import shutil
    import sys

    home = _urika_home()
    marker = home / _MIGRATION_MARKER
    if marker.exists():
        return

    settings_path = _settings_path()
    if not settings_path.exists():
        # Nothing to migrate; mark complete so we don't keep checking.
        home.mkdir(parents=True, exist_ok=True)
        marker.write_text("nothing-to-migrate\n", encoding="utf-8")
        return

    try:
        data = load_settings()
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Settings migration: load failed (%s); skipping", exc
        )
        return

    runtime = data.get("runtime", {}) or {}
    if not isinstance(runtime, dict):
        marker.write_text("non-dict-runtime\n", encoding="utf-8")
        return

    pins = _walk_4_7_pins(runtime)
    if pins == 0:
        marker.write_text("no-broken-pins\n", encoding="utf-8")
        return

    backup = settings_path.with_suffix(".toml.pre-0.3.2.bak")
    if not backup.exists():
        try:
            shutil.copy2(settings_path, backup)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "Settings migration: backup write failed (%s); aborting", exc
            )
            return

    data["runtime"] = _rewrite_4_7_pins(runtime)

    try:
        save_settings(data)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Settings migration: save failed (%s); leaving file unchanged", exc
        )
        return

    marker.write_text(f"rewrote {pins} pin(s)\n", encoding="utf-8")

    sys.stderr.write(
        f"\n  \033[33m⚠ Migrated {pins} stale "
        f"`{_BROKEN_MODEL}` pin(s) in ~/.urika/settings.toml → "
        f"`{_REPLACEMENT_MODEL}`.\033[0m\n"
        f"  Original settings backed up at {backup}.\n"
        f"  If you have the public `claude` CLI installed (v2.1.100+) "
        f"and want to use 4-7, re-pin it from the dashboard's Models tab.\n\n"
    )


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
