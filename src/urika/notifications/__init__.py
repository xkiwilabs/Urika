"""Notification system for Urika — email, Slack, Telegram."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from urika.notifications.bus import NotificationBus


def build_bus(project_path: Path) -> NotificationBus | None:
    """Build a NotificationBus from project and global notification config.

    Returns None if no notifications are configured or enabled.
    """
    from urika.notifications.bus import NotificationBus

    config = _load_notification_config(project_path)
    if not config or not config.get("enabled", False):
        return None

    bus = NotificationBus(project_name=project_path.name, project_path=project_path)

    # Add email channel if configured
    email_cfg = config.get("email")
    if email_cfg and email_cfg.get("to"):
        from urika.notifications.email_channel import EmailChannel

        bus.add_channel(EmailChannel(email_cfg))

    # Add Slack channel if configured
    slack_cfg = config.get("slack")
    if slack_cfg and slack_cfg.get("channel"):
        try:
            from urika.notifications.slack_channel import SlackChannel

            bus.add_channel(SlackChannel(slack_cfg))
        except ImportError:
            pass  # slack-sdk not installed

    # Add Telegram channel if configured
    telegram_cfg = config.get("telegram")
    if telegram_cfg and telegram_cfg.get("chat_id"):
        try:
            from urika.notifications.telegram_channel import TelegramChannel

            bus.add_channel(TelegramChannel(telegram_cfg))
        except ImportError:
            pass  # python-telegram-bot not installed

    if not bus.channels:
        return None

    return bus


def _load_notification_config(project_path: Path) -> dict[str, Any]:
    """Load notification config: global channels + project opt-in.

    Global ``~/.urika/settings.toml`` provides all channel settings
    (SMTP server, tokens, default ``to`` emails, etc.).

    Project ``urika.toml`` controls only:
    - ``[notifications] enabled = true/false`` (default **false**)
    - Extra ``to`` emails that are **added** to global recipients

    A project must have ``enabled = true`` to receive notifications.
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

    # ── Check project opt-in ──
    project_toml = project_path / "urika.toml"
    project_notif: dict[str, Any] = {}
    if project_toml.exists():
        try:
            with open(project_toml, "rb") as f:
                data = tomllib.load(f)
            project_notif = data.get("notifications", {})
        except Exception:
            pass

    # Project must explicitly enable (default is off)
    if not project_notif.get("enabled", False):
        return {}

    # Start from global config
    config = global_config
    config["enabled"] = True

    # Add project-specific extra email recipients (merged, not replaced)
    project_email = project_notif.get("email", {})
    extra_to = project_email.get("to", [])
    if extra_to:
        if isinstance(extra_to, str):
            extra_to = [extra_to]
        global_to = config.get("email", {}).get("to", [])
        if isinstance(global_to, str):
            global_to = [global_to]
        # Merge without duplicates, preserving order
        merged = list(global_to)
        for addr in extra_to:
            if addr not in merged:
                merged.append(addr)
        config.setdefault("email", {})["to"] = merged

    return config
