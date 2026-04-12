"""Config-related CLI commands: config, notifications, setup, dashboard."""

from __future__ import annotations

import os
from pathlib import Path

import click

from urika.cli._base import cli

from urika.cli._helpers import (
    _resolve_project,
    _ensure_project,
    _prompt_numbered,
)


@cli.command("dashboard")
@click.argument("project", required=False, default=None)
@click.option("--port", default=8420, type=int, help="Server port (default: 8420)")
def dashboard(project: str | None, port: int) -> None:
    """Open the project dashboard in your browser."""
    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    click.echo(f"\n  Starting dashboard for {_config.name}...")

    from urika.dashboard.server import start_dashboard

    try:
        start_dashboard(project_path, port=port)
    except KeyboardInterrupt:
        pass

    click.echo("  Dashboard stopped.")



@cli.command("config")
@click.argument("project", required=False, default=None)
@click.option("--show", is_flag=True, help="Show current settings.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def config_command(
    project: str | None,
    show: bool,
    json_output: bool,
) -> None:
    """View or configure privacy mode and models.

    Without PROJECT, configures global defaults (~/.urika/settings.toml).
    With PROJECT, configures that project's urika.toml.

    Examples:

        urika config --show              # show global defaults
        urika config                     # interactive setup (global)
        urika config my-project --show   # show project settings
        urika config my-project          # interactive setup (project)
    """
    from urika.cli_display import print_step
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

    # ── Show mode ──
    if show:
        if json_output:
            from urika.cli_helpers import output_json

            output_json(settings)
            return

        label = f"Project: {project}" if is_project else "Global defaults"
        click.echo(f"\n  {label}\n")
        p = settings.get("privacy", {})
        r = settings.get("runtime", {})
        mode = p.get("mode", "open")
        print_step(f"Privacy mode: {mode}")
        eps = p.get("endpoints", {})
        for ep_name, ep in eps.items():
            if isinstance(ep, dict):
                url = ep.get("base_url", "")
                key = ep.get("api_key_env", "")
                label_ep = f"  {ep_name}: {url}"
                if key:
                    label_ep += f" (key: ${key})"
                print_step(label_ep)
        if r.get("model"):
            print_step(f"Default model: {r['model']}")
        models = r.get("models", {})
        for agent_name, agent_cfg in models.items():
            if isinstance(agent_cfg, dict):
                m = agent_cfg.get("model", "")
                ep = agent_cfg.get("endpoint", "open")
                print_step(f"  {agent_name}: {m} (endpoint: {ep})")
            elif isinstance(agent_cfg, str):
                print_step(f"  {agent_name}: {agent_cfg}")
        click.echo()
        return

    # ── Interactive setup ──
    current_mode = settings.get("privacy", {}).get("mode", "open")
    scope = f"project ({project})" if is_project else "global default"
    click.echo(f"\n  Current {scope} privacy mode: {current_mode}\n")

    try:
        _config_interactive(
            session=settings,
            current_mode=current_mode,
            is_project=is_project,
            project_path=project_path,
        )
    except UserCancelled:
        click.echo("\n  Cancelled.")
        return


def _config_interactive(*, session, current_mode, is_project, project_path):
    """Interactive config setup. Raises UserCancelled on cancel/ESC."""
    import click
    from urika.cli_display import print_step, print_success, print_warning
    from urika.cli_helpers import (
        interactive_confirm,
        interactive_numbered,
        interactive_prompt,
    )

    _CLOUD_MODELS = [
        ("claude-sonnet-4-5", "Best balance of speed and quality (recommended)"),
        ("claude-opus-4-6", "Most capable, slower, higher cost"),
        ("claude-haiku-4-5", "Fastest, lowest cost, less capable"),
    ]

    settings = session

    mode = interactive_numbered(
        "  Privacy mode:",
        [
            "open — all agents use Claude API (cloud models only)",
            "private — all agents use local/server models (nothing leaves your network)",
            "hybrid — most agents use Claude API, data agents use local models",
        ],
        default={"open": 1, "private": 2, "hybrid": 3}.get(current_mode, 1),
    )
    mode = mode.split(" —")[0].strip()

    # Warn if changing from private/hybrid to less private
    if current_mode == "private" and mode in ("open", "hybrid"):
        print_warning(
            f"Changing from private to {mode} — agents will send data to cloud APIs."
        )
        if not interactive_confirm("  Continue?", default=False):
            click.echo("  Cancelled.")
            return
    elif current_mode == "hybrid" and mode == "open":
        print_warning(
            "Changing from hybrid to open — "
            "ALL agents (including data agent) will use cloud APIs."
        )
        if not interactive_confirm("  Continue?", default=False):
            click.echo("  Cancelled.")
            return

    settings.setdefault("privacy", {})["mode"] = mode

    # ── Open mode: pick cloud model ──
    if mode == "open":
        click.echo()
        options = [f"{m} — {desc}" for m, desc in _CLOUD_MODELS]
        choice = interactive_numbered(
            "  Default model for all agents:",
            options,
            default=1,
        )
        model_name = choice.split(" —")[0].strip()
        settings.setdefault("runtime", {})["model"] = model_name
        # Clear any private endpoints
        settings.get("privacy", {}).pop("endpoints", None)
        print_success(f"Mode: open · Model: {model_name}")

    # ── Private mode: configure endpoint + model ──
    elif mode == "private":
        click.echo()
        ep_type = interactive_numbered(
            "  Private endpoint type:",
            [
                "Ollama (localhost:11434)",
                "LM Studio (localhost:1234)",
                "vLLM / LiteLLM server (network)",
                "Custom server URL",
            ],
            default=1,
        )
        if ep_type.startswith("Ollama"):
            ep_url = "http://localhost:11434"
        elif ep_type.startswith("LM Studio"):
            ep_url = "http://localhost:1234"
        elif ep_type.startswith("vLLM"):
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt(
                "  Server URL without /v1 (e.g. http://192.168.1.100:4200)"
            )
        else:
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt("  Server URL")

        p = settings.setdefault("privacy", {})
        ep = p.setdefault("endpoints", {}).setdefault("private", {})
        ep["base_url"] = ep_url

        # API key only for remote servers (not needed for Ollama/LM Studio)
        if "localhost" not in ep_url and "127.0.0.1" not in ep_url:
            from urika.cli_helpers import interactive_prompt

            key_env = interactive_prompt(
                "  API key env var NAME, not the key itself (e.g. INFERENCE_HUB_KEY)",
                default="",
            )
            if key_env:
                ep["api_key_env"] = key_env

        from urika.cli_helpers import interactive_prompt
        from urika.core.settings import load_settings

        global_settings = load_settings()
        global_model = global_settings.get("runtime", {}).get("model", "")

        model_name = interactive_prompt(
            "  Model name" + (f" [{global_model}]" if global_model else " (e.g. qwen3:14b)"),
            default=global_model if global_model else "",
            required=True,
        )
        settings.setdefault("runtime", {})["model"] = model_name
        print_success(f"Mode: private · Endpoint: {ep_url} · Model: {model_name}")

    # ── Hybrid mode: cloud model + private endpoint for data agents ──
    elif mode == "hybrid":
        # Cloud model for most agents
        click.echo()
        options = [f"{m} — {desc}" for m, desc in _CLOUD_MODELS]
        choice = interactive_numbered(
            "  Cloud model for most agents:",
            options,
            default=1,
        )
        cloud_model = choice.split(" —")[0].strip()
        settings.setdefault("runtime", {})["model"] = cloud_model

        # Private endpoint for data agents
        click.echo()
        click.echo("  Data Agent and Tool Builder must use a private model.")
        ep_type = interactive_numbered(
            "  Private endpoint type:",
            [
                "Ollama (localhost:11434)",
                "LM Studio (localhost:1234)",
                "vLLM / LiteLLM server (network)",
                "Custom server URL",
            ],
            default=1,
        )
        if ep_type.startswith("Ollama"):
            ep_url = "http://localhost:11434"
        elif ep_type.startswith("LM Studio"):
            ep_url = "http://localhost:1234"
        elif ep_type.startswith("vLLM"):
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt(
                "  Server URL without /v1 (e.g. http://192.168.1.100:4200)"
            )
        else:
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt("  Server URL")

        p = settings.setdefault("privacy", {})
        ep = p.setdefault("endpoints", {}).setdefault("private", {})
        ep["base_url"] = ep_url

        if "localhost" not in ep_url and "127.0.0.1" not in ep_url:
            from urika.cli_helpers import interactive_prompt

            key_env = interactive_prompt(
                "  API key environment variable name",
                default="",
            )
            if key_env:
                ep["api_key_env"] = key_env

        from urika.cli_helpers import interactive_prompt
        from urika.core.settings import load_settings

        # Default from global settings if configured
        global_settings = load_settings()
        global_data_model = (
            global_settings.get("runtime", {})
            .get("models", {})
            .get("data_agent", {})
            .get("model", "")
        )

        private_model = interactive_prompt(
            "  Private model for data agents"
            + (f" [{global_data_model}]" if global_data_model else " (e.g. qwen3:14b)"),
            default=global_data_model if global_data_model else "",
            required=True,
        )

        # Set per-agent overrides
        models = settings.setdefault("runtime", {}).setdefault("models", {})
        models["data_agent"] = {"model": private_model, "endpoint": "private"}
        # tool_builder uses cloud by default in hybrid (doesn't touch raw data)

        print_success(
            f"Mode: hybrid · Cloud: {cloud_model} · "
            f"Data agents: {private_model} via {ep_url}"
        )

    # ── Save ──
    if is_project:
        from urika.core.workspace import _write_toml

        _write_toml(project_path / "urika.toml", settings)
        print_step(f"Saved to {project_path / 'urika.toml'}")
    else:
        from urika.core.settings import save_settings

        save_settings(settings)
        from urika.core.settings import _settings_path

        print_step(f"Saved to {_settings_path()}")

    click.echo()
    click.echo(
        "  Tip: for per-agent model overrides, edit the [runtime.models] "
        "section in urika.toml directly."
    )
    click.echo()


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

            notif.setdefault("email", {}).update(
                {
                    "smtp_server": smtp_server,
                    "smtp_port": int(smtp_port),
                    "from_addr": from_addr,
                    "username": from_addr,
                    "to": to_addrs,
                    "password_env": "URIKA_EMAIL_PASSWORD",
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

            notif.setdefault("slack", {}).update(
                {
                    "channel": channel,
                    "bot_token_env": "SLACK_BOT_TOKEN",
                    "app_token_env": "SLACK_APP_TOKEN" if app_token else "",
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

            notif.setdefault("telegram", {}).update(
                {
                    "chat_id": chat_id,
                    "bot_token_env": "TELEGRAM_BOT_TOKEN",
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



@cli.command("setup")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def setup_command(json_output: bool) -> None:
    """Check installation and install optional packages."""
    from urika.cli_display import (
        print_error,
        print_step,
        print_success,
        print_warning,
    )

    if json_output:
        # Collect package status and hardware info as JSON
        _all_packages = {
            "numpy": "numpy",
            "pandas": "pandas",
            "scipy": "scipy",
            "scikit-learn": "sklearn",
            "statsmodels": "statsmodels",
            "pingouin": "pingouin",
            "click": "click",
            "claude-agent-sdk": "claude_agent_sdk",
            "matplotlib": "matplotlib",
            "seaborn": "seaborn",
            "xgboost": "xgboost",
            "lightgbm": "lightgbm",
            "optuna": "optuna",
            "shap": "shap",
            "imbalanced-learn": "imblearn",
            "pypdf": "pypdf",
            "torch": "torch",
            "transformers": "transformers",
            "torchvision": "torchvision",
            "torchaudio": "torchaudio",
        }
        pkg_status = {}
        for name, imp in _all_packages.items():
            try:
                __import__(imp)
                pkg_status[name] = True
            except Exception:
                pkg_status[name] = False

        hw_data: dict = {}
        try:
            from urika.core.hardware import detect_hardware as _dh

            hw_data = dict(_dh())
        except Exception:
            pass

        from urika.cli_helpers import output_json

        output_json(
            {
                "packages": pkg_status,
                "hardware": hw_data,
                "anthropic_api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            }
        )
        return

    click.echo()
    click.echo("  Urika Setup")
    click.echo("  " + "─" * 40)
    click.echo()

    # Check core packages
    core_packages = {
        "numpy": "numpy",
        "pandas": "pandas",
        "scipy": "scipy",
        "scikit-learn": "sklearn",
        "statsmodels": "statsmodels",
        "pingouin": "pingouin",
        "click": "click",
        "claude-agent-sdk": "claude_agent_sdk",
    }
    print_step("Core packages:")
    all_core = True
    for name, imp in core_packages.items():
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")
            all_core = False
    if not all_core:
        print_warning("Some core packages missing. Run: pip install -e .")
        click.echo()

    # Check viz
    print_step("Visualization:")
    for name, imp in [
        ("matplotlib", "matplotlib"),
        ("seaborn", "seaborn"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")

    # Check ML
    print_step("Machine Learning:")
    for name, imp in [
        ("xgboost", "xgboost"),
        ("lightgbm", "lightgbm"),
        ("optuna", "optuna"),
        ("shap", "shap"),
        ("imbalanced-learn", "imblearn"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")

    # Check knowledge
    print_step("Knowledge pipeline:")
    try:
        __import__("pypdf")
        print_success("  pypdf")
    except ImportError:
        print_error("  pypdf — NOT INSTALLED")

    # Check DL
    print_step("Deep Learning:")
    dl_installed = True
    for name, imp in [
        ("torch", "torch"),
        ("transformers", "transformers"),
        ("torchvision", "torchvision"),
        ("torchaudio", "torchaudio"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — not installed")
            dl_installed = False
        except Exception as exc:
            # RuntimeError from CUDA version mismatches, etc.
            short = str(exc).split(".")[0]
            print_error(f"  {name} — {short}")
            dl_installed = False

    # Check hardware
    click.echo()
    print_step("Hardware:")
    try:
        from urika.core.hardware import detect_hardware

        hw = detect_hardware()
        cpu = hw["cpu_count"]
        ram = hw["ram_gb"]
        print_success(f"  CPU: {cpu} cores")
        if ram:
            print_success(f"  RAM: {ram} GB")
        if hw["gpu"]:
            gpu = hw["gpu_name"]
            vram = hw.get("gpu_vram", "")
            label = f"  GPU: {gpu}"
            if vram:
                label += f" ({vram})"
            print_success(label)
        else:
            print_step("  GPU: none detected")
    except Exception:
        print_step("  Could not detect hardware")

    # Offer DL install
    if not dl_installed:
        click.echo()
        click.echo("  " + "─" * 40)
        click.echo()
        print_step("Deep learning packages are not installed.")
        print_step(
            "These are large (~2 GB) and only needed for neural network experiments."
        )
        click.echo()
        choice = click.prompt(
            "  Install deep learning packages?",
            type=click.Choice(
                ["yes", "no", "gpu", "cpu"],
                case_sensitive=False,
            ),
            default="no",
        )
        if choice == "no":
            click.echo("  Skipped.")
        else:
            import subprocess
            import sys

            def _torch_install_args(*, want_gpu: bool = True) -> tuple[list[str], str]:
                """Build pip install args for PyTorch based on platform.

                Returns (args_list, description_string).

                - macOS: default PyPI (includes MPS for Apple Silicon)
                - ARM (any OS without NVIDIA): default PyPI
                - x86 + NVIDIA: detect CUDA version, use matching wheel
                - No GPU / want_gpu=False: CPU-only wheels (x86) or default (ARM)
                """
                import platform

                # Use --force-reinstall if torchaudio has a CUDA mismatch
                force = False
                try:
                    r = subprocess.run(
                        [sys.executable, "-c", "import torchaudio"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if r.returncode != 0 and "CUDA version" in r.stderr:
                        force = True
                except Exception:
                    pass

                base = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    *(["--force-reinstall"] if force else []),
                    "torch",
                    "torchvision",
                    "torchaudio",
                ]
                arch = platform.machine().lower()
                is_arm = arch in ("arm64", "aarch64", "armv8l")

                # macOS — default PyPI includes MPS for Apple Silicon
                if sys.platform == "darwin":
                    desc = "MPS" if is_arm else "CPU"
                    return base, desc

                # ARM Linux/Windows — no CUDA index, default PyPI
                if is_arm:
                    cuda_tag = _detect_cuda_tag() if want_gpu else None
                    if cuda_tag:
                        # ARM + NVIDIA (Jetson) — use default pip, torch auto-detects
                        return base, f"ARM + CUDA ({cuda_tag})"
                    return base, "ARM CPU"

                # x86 Linux/Windows
                if want_gpu:
                    cuda_tag = _detect_cuda_tag()
                    if cuda_tag:
                        return (
                            base
                            + [
                                "--index-url",
                                f"https://download.pytorch.org/whl/{cuda_tag}",
                            ],
                            f"CUDA {cuda_tag}",
                        )
                return (
                    base + ["--index-url", "https://download.pytorch.org/whl/cpu"],
                    "CPU",
                )

            def _detect_cuda_tag() -> str | None:
                """Detect CUDA version, return wheel tag (e.g. 'cu124') or None."""
                # 1. Check existing torch installation
                try:
                    import torch

                    cv = torch.version.cuda
                    if cv:
                        parts = cv.split(".")
                        return f"cu{parts[0]}{parts[1]}"
                except Exception:
                    pass
                # 2. Check nvcc
                try:
                    import re

                    r = subprocess.run(
                        ["nvcc", "--version"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if r.returncode == 0:
                        m = re.search(r"release (\d+)\.(\d+)", r.stdout)
                        if m:
                            return f"cu{m.group(1)}{m.group(2)}"
                except Exception:
                    pass
                # 3. Check nvidia-smi exists (GPU present but no toolkit)
                try:
                    r = subprocess.run(
                        ["nvidia-smi"],
                        capture_output=True,
                        timeout=5,
                    )
                    if r.returncode == 0:
                        return "cu124"  # Default to latest stable
                except Exception:
                    pass
                return None

            if choice == "gpu":
                args, desc = _torch_install_args(want_gpu=True)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                # Then the rest
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            elif choice == "cpu":
                args, desc = _torch_install_args(want_gpu=False)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            else:
                # "yes" — auto-detect
                try:
                    from urika.core.hardware import (
                        detect_hardware,
                    )

                    hw_info = detect_hardware()
                    has_gpu = hw_info.get("gpu", False)
                except Exception:
                    has_gpu = False

                args, desc = _torch_install_args(want_gpu=has_gpu)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            print_success("Deep learning packages installed.")
    else:
        # Check GPU availability with torch
        click.echo()
        try:
            import torch

            if torch.cuda.is_available():
                dev = torch.cuda.get_device_name(0)
                print_success(f"  PyTorch CUDA: {dev}")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                print_success("  PyTorch MPS: available")
            else:
                print_step("  PyTorch: CPU only")
        except Exception:
            pass

    click.echo()
    print_step("Claude access:")
    if os.environ.get("ANTHROPIC_API_KEY"):
        print_success("  ANTHROPIC_API_KEY is set")
    else:
        print_warning(
            "  ANTHROPIC_API_KEY not set — needed unless using Claude Max/Pro"
        )

    click.echo()
    # Check for updates
    print_step("Updates:")
    try:
        from urika.core.updates import (
            check_for_updates,
            format_update_message,
        )

        update_info = check_for_updates(force=True)
        if update_info:
            msg = format_update_message(update_info)
            print_warning(f"  {msg}")
        else:
            print_success("  You are on the latest version")
    except Exception:
        print_step("  Could not check for updates")

    click.echo()
    print_success("Setup check complete.")
    click.echo()


