"""`urika notifications` command and its helpers.

Split out of cli/config.py as part of Phase 8 refactoring. Importing
this module registers the @cli.command decorator for ``notifications``.
"""

from __future__ import annotations

from pathlib import Path

import click

from urika.cli._base import cli
from urika.cli._helpers import _resolve_project


@cli.command("notifications")
@click.option("--show", is_flag=True, help="Show current notification config.")
@click.option("--test", "send_test", is_flag=True, help="Send a test notification.")
@click.option("--disable", is_flag=True, help="Disable all notifications.")
@click.option("--project", default=None, help="Configure for a specific project.")
def notifications_command(
    show: bool,
    send_test: bool,
    disable: bool,
    project: str | None,
) -> None:
    """Configure notification channels (email, Slack, Telegram).

    Examples:

        urika notifications              # interactive setup (global)
        urika notifications --show       # show current config
        urika notifications --test       # send test notification
        urika notifications --disable    # disable notifications
        urika notifications --project X  # configure for project X
    """
    from urika.cli_display import print_success
    from urika.cli_helpers import UserCancelled

    # ── Determine target: global or project ──
    is_project = False
    project_path = None
    if project is not None:
        is_project = True
        try:
            project_path, _config = _resolve_project(project)
        except click.ClickException:
            raise

    # ── Load current settings ──
    if is_project:
        import tomllib

        toml_path = project_path / "urika.toml"
        with open(toml_path, "rb") as f:
            settings = tomllib.load(f)
    else:
        from urika.core.settings import load_settings

        settings = load_settings()

    notif = settings.get("notifications", {})

    # ── Disable mode (project-level only) ──
    if disable:
        if not is_project:
            click.echo("  Disable is a project-level setting. Use: urika notifications --disable --project <name>")
            return
        settings.setdefault("notifications", {})["channels"] = []
        _save_notification_settings(settings, is_project, project_path)
        print_success("Notifications disabled for this project.")
        return

    # ── Show mode ──
    if show:
        if is_project:
            # Show merged config (global defaults + project overrides)
            from urika.notifications import _load_notification_config

            merged = _load_notification_config(project_path)
            channels_list = settings.get("notifications", {}).get("channels", [])
            click.echo(f"\n  Project: {project}")
            if channels_list:
                click.echo(f"  Enabled channels: {', '.join(channels_list)}")
            else:
                click.echo("  No channels enabled for this project.")
            # Show the merged channel details from global + project config
            _show_notification_config(merged)
        else:
            _show_notification_config(notif)
        return

    # ── Test mode ──
    if send_test:
        _send_test_notification(notif, project_path=project_path)
        return

    # ── Interactive setup ──
    try:
        _notifications_interactive(
            settings=settings,
            is_project=is_project,
            project_path=project_path,
        )
    except UserCancelled:
        click.echo("\n  Cancelled.")


def _show_notification_config(notif: dict) -> None:
    """Display current notification config with masked credentials."""
    from urika.cli_display import print_step
    from urika.core.secrets import list_secrets

    # "enabled" is a project-level setting; global config just stores channel details
    has_channels = any(
        notif.get(ch, {}).get(key)
        for ch, key in [("email", "to"), ("slack", "channel"), ("telegram", "chat_id")]
    )
    status = "configured" if has_channels else "not configured"
    click.echo(f"\n  Notifications: {status}\n")

    # Email
    email = notif.get("email", {})
    if email.get("to"):
        to_addrs = email["to"] if isinstance(email["to"], list) else [email["to"]]
        from_addr = email.get("from_addr", "")
        server = email.get("smtp_server", "smtp.gmail.com")
        port = email.get("smtp_port", 587)
        print_step(f"Email: {from_addr} -> {', '.join(to_addrs)} (via {server}:{port})")
    else:
        print_step("Email: not configured")

    # Slack
    slack = notif.get("slack", {})
    if slack.get("channel"):
        print_step(f"Slack: {slack['channel']} (configured)")
    else:
        print_step("Slack: not configured")

    # Telegram
    telegram = notif.get("telegram", {})
    if telegram.get("chat_id"):
        print_step(f"Telegram: chat {telegram['chat_id']} (configured)")
    else:
        print_step("Telegram: not configured")

    # Show stored secrets (masked)
    secrets = list_secrets()
    notif_keys = [
        k
        for k in secrets
        if k
        in (
            "URIKA_EMAIL_PASSWORD",
            "SLACK_BOT_TOKEN",
            "SLACK_APP_TOKEN",
            "TELEGRAM_BOT_TOKEN",
        )
    ]
    if notif_keys:
        click.echo()
        print_step("Stored credentials:")
        for k in notif_keys:
            print_step(f"  {k}: ****")

    click.echo()


def _send_test_notification(notif: dict, project_path: Path | None = None) -> None:
    """Send a test notification through all configured channels."""
    from urika.cli_display import print_error, print_success, print_warning
    from urika.notifications.events import NotificationEvent

    # Use build_bus for proper global+project config resolution
    if project_path is not None:
        from urika.notifications import build_bus

        bus = build_bus(project_path)
        if bus is None:
            print_warning("No notification channels enabled for this project.")
            return

        event = NotificationEvent(
            event_type="test",
            project_name=project_path.name,
            summary="Test notification from Urika",
            priority="medium",
        )
        for ch in bus.channels:
            try:
                ch.send(event)
                print_success(f"Test sent via {type(ch).__name__}")
            except Exception as exc:
                print_error(f"{type(ch).__name__} failed: {exc}")
        return

    # Global test (no project) — test each channel from raw config
    event = NotificationEvent(
        event_type="test",
        project_name="test",
        summary="Test notification from Urika",
        priority="medium",
    )

    sent = False

    # Test email
    email_cfg = notif.get("email", {})
    if email_cfg.get("to"):
        try:
            from urika.notifications.email_channel import EmailChannel

            ch = EmailChannel(email_cfg)
            ch.send(event)
            to_addrs = email_cfg["to"]
            if isinstance(to_addrs, list):
                to_addrs = ", ".join(to_addrs)
            print_success(f"Test email sent to {to_addrs}")
            sent = True
        except Exception as exc:
            print_error(f"Email failed: {exc}")

    # Test Slack
    slack_cfg = notif.get("slack", {})
    if slack_cfg.get("channel"):
        try:
            from urika.notifications.slack_channel import SlackChannel

            ch = SlackChannel(slack_cfg)
            ch.send(event)
            print_success(f"Test Slack message sent to {slack_cfg['channel']}")
            sent = True
        except ImportError:
            print_warning("slack-sdk not installed: pip install slack-sdk")
        except Exception as exc:
            print_error(f"Slack failed: {exc}")

    # Test Telegram
    telegram_cfg = notif.get("telegram", {})
    if telegram_cfg.get("chat_id"):
        try:
            from urika.notifications.telegram_channel import TelegramChannel

            ch = TelegramChannel(telegram_cfg)
            ch.send(event)
            print_success(
                f"Test Telegram message sent to chat {telegram_cfg['chat_id']}"
            )
            sent = True
        except ImportError:
            print_warning(
                "python-telegram-bot not installed: pip install python-telegram-bot"
            )
        except Exception as exc:
            print_error(f"Telegram failed: {exc}")

    if not sent:
        print_warning("No channels configured. Run: urika notifications")


def _notifications_interactive(*, settings, is_project, project_path):
    """Interactive notification setup. Raises UserCancelled on cancel/ESC."""
    if is_project:
        _notifications_project_setup(settings=settings, project_path=project_path)
        return

    _notifications_global_setup(settings=settings, project_path=project_path)


def _notifications_project_setup(*, settings, project_path):
    """Project-level notification setup — select channels + extra recipients."""
    import click
    import tomllib
    from urika.cli_display import print_step, print_success, print_warning
    from urika.cli_helpers import interactive_confirm, interactive_prompt

    # Load global config to show what's available
    global_notif: dict = {}
    global_path = Path.home() / ".urika" / "settings.toml"
    if global_path.exists():
        try:
            with open(global_path, "rb") as f:
                data = tomllib.load(f)
            global_notif = data.get("notifications", {})
        except Exception:
            pass

    # Check what's configured globally
    has_email = bool(global_notif.get("email", {}).get("to"))
    has_slack = bool(global_notif.get("slack", {}).get("channel"))
    has_telegram = bool(global_notif.get("telegram", {}).get("chat_id"))

    if not has_email and not has_slack and not has_telegram:
        print_warning(
            "No notification channels configured globally.\n"
            "  Run 'urika notifications' (without --project) to set up channels first."
        )
        return

    click.echo("\n  Project notification setup\n")

    # Show available global channels
    click.echo("  Available channels (from global settings):")
    if has_email:
        to = global_notif["email"]["to"]
        if isinstance(to, list):
            to = ", ".join(to)
        click.echo(
            f"    Email:    {global_notif['email'].get('from_addr', '?')} -> {to}"
        )
    if has_slack:
        click.echo(f"    Slack:    {global_notif['slack']['channel']}")
    if has_telegram:
        click.echo(f"    Telegram: chat {global_notif['telegram']['chat_id']}")
    click.echo()

    # Ask which channels to enable
    channels = []
    if has_email and interactive_confirm("Enable email notifications?", default=True):
        channels.append("email")
    if has_slack and interactive_confirm("Enable Slack notifications?", default=True):
        channels.append("slack")
    if has_telegram and interactive_confirm(
        "Enable Telegram notifications?", default=True
    ):
        channels.append("telegram")

    if not channels:
        print_step("No channels enabled.")
        return

    # Ask for per-project overrides
    extra_to: list[str] = []
    if "email" in channels:
        extra_raw = interactive_prompt(
            "Extra email recipients for this project (comma-separated, or blank)",
            default="",
        )
        if extra_raw.strip():
            extra_to = [a.strip() for a in extra_raw.split(",") if a.strip()]

    override_chat_id = ""
    if "telegram" in channels:
        global_chat = global_notif.get("telegram", {}).get("chat_id", "")
        override_raw = interactive_prompt(
            f"Telegram chat ID for this project (blank to use global: {global_chat})",
            default="",
        )
        if override_raw.strip():
            override_chat_id = override_raw.strip()

    # Save to project urika.toml
    notif: dict = {"channels": channels}
    if extra_to:
        notif["email"] = {"to": extra_to}
    if override_chat_id:
        notif["telegram"] = {"chat_id": override_chat_id}
    settings["notifications"] = notif
    _save_notification_settings(settings, is_project=True, project_path=project_path)

    print_success(f"Notifications enabled: {', '.join(channels)}")
    if extra_to:
        click.echo(f"  Extra recipients: {', '.join(extra_to)}")
    if override_chat_id:
        click.echo(f"  Telegram chat: {override_chat_id} (project-specific)")
    click.echo()


def _notifications_global_setup(*, settings, project_path):
    """Global notification setup — configure channel settings."""

    import click
    from urika.cli_display import print_success
    from urika.cli_helpers import (
        interactive_confirm,
        interactive_numbered,
        interactive_prompt,
    )
    from urika.core.secrets import save_secret

    notif = settings.get("notifications", {})

    click.echo("\n  Notification setup\n")

    # Show current state
    email_cfg = notif.get("email", {})
    slack_cfg = notif.get("slack", {})
    telegram_cfg = notif.get("telegram", {})

    click.echo("  Current channels:")
    if email_cfg.get("to"):
        to_list = email_cfg["to"]
        if isinstance(to_list, list):
            to_list = ", ".join(to_list)
        click.echo(
            f"    Email:    {email_cfg.get('from_addr', '?')} -> {to_list} (configured)"
        )
    else:
        click.echo("    Email:    not configured")

    if slack_cfg.get("channel"):
        click.echo(f"    Slack:    {slack_cfg['channel']} (configured)")
    else:
        click.echo("    Slack:    not configured")

    if telegram_cfg.get("chat_id"):
        click.echo(f"    Telegram: chat {telegram_cfg['chat_id']} (configured)")
    else:
        click.echo("    Telegram: not configured")

    click.echo()

    while True:
        choice = interactive_numbered(
            "  Configure:",
            [
                "Email",
                "Slack",
                "Telegram",
                "Send test notification",
                "Done",
            ],
            default=5,
            allow_cancel=False,
        )

        if choice == "Done":
            break

        if choice == "Send test notification":
            _send_test_notification(settings.get("notifications", {}))
            continue

        if choice == "Email":
            click.echo("\n  Email setup\n")

            smtp_server = interactive_prompt(
                "SMTP server",
                default=email_cfg.get("smtp_server", "smtp.gmail.com"),
            )
            smtp_port = interactive_prompt(
                "SMTP port",
                default=str(email_cfg.get("smtp_port", 587)),
            )
            from_addr = interactive_prompt(
                "From address",
                default=email_cfg.get("from_addr", ""),
            )
            to_raw = interactive_prompt(
                "To addresses (comma-separated)",
                default=", ".join(email_cfg.get("to", [])),
            )
            to_addrs = [a.strip() for a in to_raw.split(",") if a.strip()]

            # App password / SMTP password (shown — these are generated tokens, not personal passwords)
            password = interactive_prompt(
                "App password (e.g. Gmail app password)",
                default="",
            )

            if password:
                save_secret("URIKA_EMAIL_PASSWORD", password)
                click.echo("  Saved! Password stored in ~/.urika/secrets.env")

            # Ask about auto-enabling for new projects. Default True
            # because the most common case (user sets up email globally
            # → wants new projects to use it) needs no extra typing.
            auto_enable = interactive_confirm(
                "Auto-enable for new projects?",
                default=bool(email_cfg.get("auto_enable", True)),
            )

            notif.setdefault("email", {}).update(
                {
                    "smtp_server": smtp_server,
                    "smtp_port": int(smtp_port),
                    "from_addr": from_addr,
                    "username": from_addr,
                    "to": to_addrs,
                    "password_env": "URIKA_EMAIL_PASSWORD",
                    "auto_enable": auto_enable,
                }
            )
            settings["notifications"] = notif
            _save_notification_settings(settings, False, project_path)
            print_success("Email configured.")

            if interactive_confirm("Send test email?", default=True):
                _send_test_notification(settings.get("notifications", {}))

            click.echo()
            continue

        if choice == "Slack":
            click.echo("\n  Slack setup\n")

            channel = interactive_prompt(
                "Channel (e.g. #urika-results)",
                default=slack_cfg.get("channel", ""),
            )

            bot_token = interactive_prompt(
                "Bot token (from Slack app settings)",
                default="",
            )

            if bot_token:
                save_secret("SLACK_BOT_TOKEN", bot_token)

            app_token = interactive_prompt(
                "App token (for interactive buttons, optional)",
                default="",
            )

            if app_token:
                save_secret("SLACK_APP_TOKEN", app_token)

            auto_enable = interactive_confirm(
                "Auto-enable for new projects?",
                default=bool(slack_cfg.get("auto_enable", True)),
            )

            notif.setdefault("slack", {}).update(
                {
                    "channel": channel,
                    "bot_token_env": "SLACK_BOT_TOKEN",
                    "app_token_env": "SLACK_APP_TOKEN" if app_token else "",
                    "auto_enable": auto_enable,
                }
            )
            settings["notifications"] = notif
            _save_notification_settings(settings, False, project_path)

            tokens_saved = []
            if bot_token:
                tokens_saved.append("bot token")
            if app_token:
                tokens_saved.append("app token")
            if tokens_saved:
                click.echo(
                    f"  Saved! {', '.join(tokens_saved).capitalize()}"
                    " stored in ~/.urika/secrets.env"
                )
            print_success("Slack configured.")
            click.echo()
            continue

        if choice == "Telegram":
            click.echo("\n  Telegram setup\n")

            chat_id = interactive_prompt(
                "Chat ID (e.g. -100123456789)",
                default=str(telegram_cfg.get("chat_id", "")),
            )

            bot_token = interactive_prompt(
                "Bot token (from @BotFather)",
                default="",
            )

            if bot_token:
                save_secret("TELEGRAM_BOT_TOKEN", bot_token)
                click.echo("  Saved! Token stored in ~/.urika/secrets.env")

            auto_enable = interactive_confirm(
                "Auto-enable for new projects?",
                default=bool(telegram_cfg.get("auto_enable", True)),
            )

            notif.setdefault("telegram", {}).update(
                {
                    "chat_id": chat_id,
                    "bot_token_env": "TELEGRAM_BOT_TOKEN",
                    "auto_enable": auto_enable,
                }
            )
            settings["notifications"] = notif
            _save_notification_settings(settings, False, project_path)
            print_success("Telegram configured.")
            click.echo()
            continue


def _save_notification_settings(settings, is_project, project_path):
    """Save settings back to the appropriate TOML file."""
    if is_project:
        from urika.core.workspace import _write_toml

        _write_toml(project_path / "urika.toml", settings)
    else:
        from urika.core.settings import save_settings

        save_settings(settings)


def seed_project_notifications_from_global(project_path: Path) -> list[str]:
    """Seed a freshly created project's [notifications].channels list
    from the global per-channel ``auto_enable`` flags.

    Non-interactive — used by ``urika new`` (and mirrors the dashboard's
    POST /api/projects). Channels with ``auto_enable=true`` get added
    to the new project's channels list; channels with ``auto_enable=false``
    (or unset) stay out, and the user can opt-in later via
    ``urika notifications --project <name>``.

    Returns the list of channels that were seeded (empty list if none).
    """
    import tomllib

    from urika.core.settings import get_default_notifications_auto_enable
    from urika.core.workspace import _write_toml

    auto = get_default_notifications_auto_enable()
    auto_channels = [ch for ch, on in auto.items() if on]
    if not auto_channels:
        return []

    toml_path = project_path / "urika.toml"
    if not toml_path.exists():
        return []
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    data.setdefault("notifications", {})["channels"] = auto_channels
    _write_toml(toml_path, data)
    return auto_channels



