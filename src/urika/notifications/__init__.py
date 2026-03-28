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

    global_cfg, enabled_channels, extra_email_to = _load_notification_config(
        project_path
    )
    if not enabled_channels:
        return None

    bus = NotificationBus(project_name=project_path.name, project_path=project_path)

    # Add email channel if enabled and configured globally
    if "email" in enabled_channels:
        email_cfg = global_cfg.get("email")
        if email_cfg and email_cfg.get("to"):
            from urika.notifications.email_channel import EmailChannel

            # Merge extra project recipients
            if extra_email_to:
                to_list = list(email_cfg.get("to", []))
                for addr in extra_email_to:
                    if addr not in to_list:
                        to_list.append(addr)
                email_cfg = {**email_cfg, "to": to_list}
            bus.add_channel(EmailChannel(email_cfg))
        else:
            logging.getLogger(__name__).warning(
                "Email enabled for %s but not configured globally. "
                "Run 'urika notifications' to set up email.",
                project_path.name,
            )

    # Add Slack channel if enabled and configured globally
    if "slack" in enabled_channels:
        slack_cfg = global_cfg.get("slack")
        if slack_cfg and slack_cfg.get("channel"):
            try:
                from urika.notifications.slack_channel import SlackChannel

                bus.add_channel(SlackChannel(slack_cfg))
            except ImportError:
                logging.getLogger(__name__).warning(
                    "Slack enabled but slack-sdk not installed. "
                    "Run: pip install urika[notifications]"
                )
        else:
            logging.getLogger(__name__).warning(
                "Slack enabled for %s but not configured globally. "
                "Run 'urika notifications' to set up Slack.",
                project_path.name,
            )

    # Add Telegram channel if enabled and configured globally
    if "telegram" in enabled_channels:
        telegram_cfg = global_cfg.get("telegram")
        if telegram_cfg and telegram_cfg.get("chat_id"):
            try:
                from urika.notifications.telegram_channel import TelegramChannel

                bus.add_channel(TelegramChannel(telegram_cfg))
            except ImportError:
                logging.getLogger(__name__).warning(
                    "Telegram enabled but python-telegram-bot not installed. "
                    "Run: pip install urika[notifications]"
                )
        else:
            logging.getLogger(__name__).warning(
                "Telegram enabled for %s but not configured globally. "
                "Run 'urika notifications' to set up Telegram.",
                project_path.name,
            )

    if not bus.channels:
        return None

    return bus


def _load_notification_config(
    project_path: Path,
) -> tuple[dict[str, Any], set[str], list[str]]:
    """Load notification config: global channels + per-project channel selection.

    Global ``~/.urika/settings.toml`` provides all channel settings
    (SMTP server, tokens, default ``to`` emails, etc.).

    Project ``urika.toml`` selects which channels to use::

        [notifications]
        channels = ["email", "telegram"]  # which channels to enable

        [notifications.email]
        to = ["extra@lab.edu"]  # additional recipients for this project

    Returns:
        (global_config, enabled_channels, extra_email_to)
        - global_config: the full global [notifications] dict
        - enabled_channels: set of channel names enabled for this project
        - extra_email_to: list of extra email recipients from project config
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

    # ── Load project channel selection ──
    project_toml = project_path / "urika.toml"
    project_notif: dict[str, Any] = {}
    if project_toml.exists():
        try:
            with open(project_toml, "rb") as f:
                data = tomllib.load(f)
            project_notif = data.get("notifications", {})
        except Exception:
            pass

    # Determine which channels are enabled via "channels" list
    # e.g. channels = ["email", "telegram"]
    channels_list = project_notif.get("channels", [])
    if isinstance(channels_list, str):
        channels_list = [channels_list]
    enabled: set[str] = {c for c in channels_list if c in ("email", "slack", "telegram")}

    # Also support legacy "enabled = true" (turns on all globally configured channels)
    if not enabled and project_notif.get("enabled", False):
        for channel in ("email", "slack", "telegram"):
            if channel in global_config and isinstance(global_config[channel], dict):
                enabled.add(channel)

    # Extract extra email recipients from project
    extra_email_to: list[str] = []
    project_email = project_notif.get("email", {})
    if isinstance(project_email, dict):
        extra = project_email.get("to", [])
        if isinstance(extra, str):
            extra = [extra]
        extra_email_to = extra

    return global_config, enabled, extra_email_to
