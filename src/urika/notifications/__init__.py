"""Notification system for Urika — email, Slack, Telegram."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from urika.notifications.bus import NotificationBus


def build_bus(project_path: Path) -> NotificationBus | None:
    """Build a NotificationBus from project and global notification config.

    Returns None if no channels are enabled for this project.
    """
    import logging

    from urika.notifications.bus import NotificationBus

    channels = _load_notification_config(project_path)
    if not channels:
        return None

    bus = NotificationBus(project_name=project_path.name, project_path=project_path)
    log = logging.getLogger(__name__)

    if "email" in channels:
        cfg = channels["email"]
        if cfg.get("to"):
            from urika.notifications.email_channel import EmailChannel

            bus.add_channel(EmailChannel(cfg))
        else:
            log.warning(
                "Email enabled for %s but no recipients configured.",
                project_path.name,
            )

    if "slack" in channels:
        cfg = channels["slack"]
        if cfg.get("channel"):
            from urika.notifications.slack_channel import SlackChannel

            bus.add_channel(SlackChannel(cfg))
        else:
            log.warning(
                "Slack enabled for %s but not configured.", project_path.name
            )

    if "telegram" in channels:
        cfg = channels["telegram"]
        if cfg.get("chat_id"):
            from urika.notifications.telegram_channel import TelegramChannel

            bus.add_channel(TelegramChannel(cfg))
        else:
            log.warning(
                "Telegram enabled for %s but not configured.", project_path.name
            )

    if not bus.channels:
        return None

    return bus


def _load_notification_config(project_path: Path) -> dict[str, dict[str, Any]]:
    """Load notification config: global defaults + project overrides.

    Returns a dict of enabled channel configs, e.g.::

        {
            "email": {"smtp_server": "...", "to": [...], ...},
            "telegram": {"chat_id": "...", "bot_token_env": "...", ...},
        }

    Empty dict means no channels enabled.

    Global ``settings.toml`` provides channel defaults. Project ``urika.toml``
    selects which channels and can override per-channel fields::

        [notifications]
        channels = ["email", "telegram"]

        [notifications.email]
        to = ["extra@lab.edu"]       # added to global recipients

        [notifications.telegram]
        chat_id = "-100999"          # override global chat_id for this project
    """
    import copy
    import tomllib

    # ── Load global channel settings ──
    global_config: dict[str, Any] = {}
    global_path = Path.home() / ".urika" / "settings.toml"
    if global_path.exists():
        try:
            with open(global_path, "rb") as f:
                data = tomllib.load(f)
            global_config = copy.deepcopy(data.get("notifications", {}))
        except Exception:
            pass

    # ── Load project config ──
    project_toml = project_path / "urika.toml"
    project_notif: dict[str, Any] = {}
    if project_toml.exists():
        try:
            with open(project_toml, "rb") as f:
                data = tomllib.load(f)
            project_notif = data.get("notifications", {})
        except Exception:
            pass

    # Determine which channels are enabled
    channels_list = project_notif.get("channels", [])
    if isinstance(channels_list, str):
        channels_list = [channels_list]
    enabled: set[str] = {
        c for c in channels_list if c in ("email", "slack", "telegram")
    }

    # Legacy: enabled = true turns on all globally configured channels
    if not enabled and project_notif.get("enabled", False):
        for ch in ("email", "slack", "telegram"):
            if ch in global_config and isinstance(global_config[ch], dict):
                enabled.add(ch)

    if not enabled:
        return {}

    # Build merged config for each enabled channel
    result: dict[str, dict[str, Any]] = {}
    for ch in enabled:
        # Start with global config for this channel
        cfg = copy.deepcopy(global_config.get(ch, {}))
        if not isinstance(cfg, dict):
            cfg = {}

        # Merge project overrides
        project_ch = project_notif.get(ch, {})
        if isinstance(project_ch, dict) and project_ch:
            if ch == "email" and "to" in project_ch:
                # Email "to": merge (add extra recipients), don't replace
                extra = project_ch["to"]
                if isinstance(extra, str):
                    extra = [extra]
                existing = cfg.get("to", [])
                if isinstance(existing, str):
                    existing = [existing]
                merged = list(existing)
                for addr in extra:
                    if addr not in merged:
                        merged.append(addr)
                cfg["to"] = merged
                # Merge other email fields (not "to")
                for k, v in project_ch.items():
                    if k != "to":
                        cfg[k] = v
            else:
                # All other channels: project overrides global fields
                cfg.update(project_ch)

        result[ch] = cfg

    return result
