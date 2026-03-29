"""Tests for notification config loading and bus building."""

from __future__ import annotations

import logging
from pathlib import Path

from urika.notifications import _load_notification_config, build_bus


def _fake_home(tmp_path, monkeypatch, global_toml=""):
    """Set up a fake home with optional global settings."""
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    urika_dir = fake_home / ".urika"
    urika_dir.mkdir()
    if global_toml:
        (urika_dir / "settings.toml").write_text(global_toml)
    monkeypatch.setattr(Path, "home", lambda: fake_home)


_GLOBAL_EMAIL = """\
[notifications.email]
smtp_server = "smtp.example.com"
smtp_port = 587
from_addr = "urika@example.com"
to = ["global@example.com"]
password_env = "TEST_EMAIL_PWD"
"""

_GLOBAL_ALL = """\
[notifications.email]
smtp_server = "smtp.example.com"
to = ["global@example.com"]
from_addr = "urika@example.com"

[notifications.slack]
channel = "#urika"
bot_token_env = "SLACK_TOKEN"

[notifications.telegram]
chat_id = "-100123"
bot_token_env = "TG_TOKEN"
"""


class TestLoadConfig:
    def test_no_config_anywhere(self, tmp_path, monkeypatch):
        """No global and no project config -> empty dict."""
        _fake_home(tmp_path, monkeypatch)
        result = _load_notification_config(tmp_path)
        assert result == {}

    def test_global_only_no_project(self, tmp_path, monkeypatch):
        """Global config but project has no [notifications] -> empty."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text("[project]\nname = 'test'\n")
        result = _load_notification_config(tmp_path)
        assert result == {}

    def test_project_enables_email(self, tmp_path, monkeypatch):
        """Project channels = ["email"] -> email config from global."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text(
            '[notifications]\nchannels = ["email"]\n'
        )
        result = _load_notification_config(tmp_path)
        assert "email" in result
        assert result["email"]["smtp_server"] == "smtp.example.com"
        assert result["email"]["to"] == ["global@example.com"]

    def test_project_enables_subset(self, tmp_path, monkeypatch):
        """Project picks email + telegram, skips slack."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_ALL)
        (tmp_path / "urika.toml").write_text(
            '[notifications]\nchannels = ["email", "telegram"]\n'
        )
        result = _load_notification_config(tmp_path)
        assert "email" in result
        assert "telegram" in result
        assert "slack" not in result

    def test_project_adds_extra_email_recipients(self, tmp_path, monkeypatch):
        """Project adds extra to emails merged with global."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text("""\
[notifications]
channels = ["email"]

[notifications.email]
to = ["project@example.com"]
""")
        result = _load_notification_config(tmp_path)
        assert "global@example.com" in result["email"]["to"]
        assert "project@example.com" in result["email"]["to"]

    def test_no_duplicate_email_recipients(self, tmp_path, monkeypatch):
        """Same address in global and project -> no duplicates."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text("""\
[notifications]
channels = ["email"]

[notifications.email]
to = ["global@example.com", "extra@example.com"]
""")
        result = _load_notification_config(tmp_path)
        assert result["email"]["to"].count("global@example.com") == 1
        assert "extra@example.com" in result["email"]["to"]

    def test_project_overrides_telegram_chat_id(self, tmp_path, monkeypatch):
        """Project can override telegram chat_id for project-specific group."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_ALL)
        (tmp_path / "urika.toml").write_text("""\
[notifications]
channels = ["telegram"]

[notifications.telegram]
chat_id = "-100999"
""")
        result = _load_notification_config(tmp_path)
        assert result["telegram"]["chat_id"] == "-100999"
        # Bot token still comes from global
        assert result["telegram"]["bot_token_env"] == "TG_TOKEN"

    def test_project_overrides_slack_channel(self, tmp_path, monkeypatch):
        """Project can override slack channel."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_ALL)
        (tmp_path / "urika.toml").write_text("""\
[notifications]
channels = ["slack"]

[notifications.slack]
channel = "#project-specific"
""")
        result = _load_notification_config(tmp_path)
        assert result["slack"]["channel"] == "#project-specific"
        assert result["slack"]["bot_token_env"] == "SLACK_TOKEN"

    def test_project_no_channels(self, tmp_path, monkeypatch):
        """Empty channels list -> empty."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text(
            "[notifications]\nchannels = []\n"
        )
        result = _load_notification_config(tmp_path)
        assert result == {}

    def test_legacy_enabled_true(self, tmp_path, monkeypatch):
        """Legacy enabled = true turns on all globally configured channels."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_ALL)
        (tmp_path / "urika.toml").write_text(
            "[notifications]\nenabled = true\n"
        )
        result = _load_notification_config(tmp_path)
        assert "email" in result
        assert "slack" in result
        assert "telegram" in result

    def test_build_bus_returns_none_no_project(self, tmp_path, monkeypatch):
        """No project notifications -> None."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        assert build_bus(tmp_path) is None

    def test_build_bus_with_email(self, tmp_path, monkeypatch):
        """Project enables email -> bus with 1 channel."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text(
            '[notifications]\nchannels = ["email"]\n'
        )
        bus = build_bus(tmp_path)
        assert bus is not None
        assert len(bus.channels) == 1
        from urika.notifications.email_channel import EmailChannel

        assert isinstance(bus.channels[0], EmailChannel)

    def test_build_bus_warns_if_not_configured(self, tmp_path, monkeypatch, caplog):
        """Email enabled but no global config -> warning, no bus."""
        _fake_home(tmp_path, monkeypatch)
        (tmp_path / "urika.toml").write_text(
            '[notifications]\nchannels = ["email"]\n'
        )
        with caplog.at_level(logging.WARNING):
            bus = build_bus(tmp_path)
        assert bus is None
        assert "missing required fields" in caplog.text

    def test_build_bus_with_project_telegram_override(self, tmp_path, monkeypatch):
        """Project overrides telegram chat_id -> bus uses project's ID."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_ALL)
        (tmp_path / "urika.toml").write_text("""\
[notifications]
channels = ["telegram"]

[notifications.telegram]
chat_id = "-100999"
""")
        bus = build_bus(tmp_path)
        assert bus is not None
        assert len(bus.channels) == 1
        assert bus.channels[0]._chat_id == "-100999"
