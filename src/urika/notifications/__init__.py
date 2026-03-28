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

    bus = NotificationBus(project_name=project_path.name)

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
    """Load notification config from project urika.toml, falling back to global settings."""
    import tomllib

    config: dict[str, Any] = {}

    # Global defaults
    global_path = Path.home() / ".urika" / "settings.toml"
    if global_path.exists():
        try:
            with open(global_path, "rb") as f:
                data = tomllib.load(f)
            config = data.get("notifications", {})
        except Exception:
            pass

    # Project overrides
    project_toml = project_path / "urika.toml"
    if project_toml.exists():
        try:
            with open(project_toml, "rb") as f:
                data = tomllib.load(f)
            project_notif = data.get("notifications", {})
            if project_notif:
                config.update(project_notif)
        except Exception:
            pass

    return config
