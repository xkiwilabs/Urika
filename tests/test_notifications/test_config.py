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
        """No global and no project config -> no channels."""
        _fake_home(tmp_path, monkeypatch)
        _global, enabled, _extra = _load_notification_config(tmp_path)
        assert enabled == set()

    def test_global_only_no_project(self, tmp_path, monkeypatch):
        """Global config but project has no [notifications] -> no channels."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text("[project]\nname = 'test'\n")
        _global, enabled, _extra = _load_notification_config(tmp_path)
        assert enabled == set()

    def test_project_enables_email(self, tmp_path, monkeypatch):
        """Project channels = ["email"] -> email enabled."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text(
            '[notifications]\nchannels = ["email"]\n'
        )
        _global, enabled, _extra = _load_notification_config(tmp_path)
        assert enabled == {"email"}

    def test_project_enables_subset(self, tmp_path, monkeypatch):
        """Project picks email + telegram, skips slack."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_ALL)
        (tmp_path / "urika.toml").write_text(
            '[notifications]\nchannels = ["email", "telegram"]\n'
        )
        _global, enabled, _extra = _load_notification_config(tmp_path)
        assert enabled == {"email", "telegram"}
        assert "slack" not in enabled

    def test_project_adds_extra_recipients(self, tmp_path, monkeypatch):
        """Project adds extra to emails."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text("""\
[notifications]
channels = ["email"]

[notifications.email]
to = ["project@example.com"]
""")
        _global, enabled, extra = _load_notification_config(tmp_path)
        assert "email" in enabled
        assert "project@example.com" in extra

    def test_no_duplicate_recipients(self, tmp_path, monkeypatch):
        """build_bus merges without duplicating addresses."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text("""\
[notifications]
channels = ["email"]

[notifications.email]
to = ["global@example.com", "extra@example.com"]
""")
        bus = build_bus(tmp_path)
        assert bus is not None
        from urika.notifications.email_channel import EmailChannel

        email_ch = bus.channels[0]
        assert isinstance(email_ch, EmailChannel)
        assert email_ch._to.count("global@example.com") == 1
        assert "extra@example.com" in email_ch._to

    def test_project_no_channels(self, tmp_path, monkeypatch):
        """Project with empty channels list -> no channels."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text(
            "[notifications]\nchannels = []\n"
        )
        _global, enabled, _extra = _load_notification_config(tmp_path)
        assert enabled == set()

    def test_legacy_enabled_true(self, tmp_path, monkeypatch):
        """Legacy enabled = true turns on all globally configured channels."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_ALL)
        (tmp_path / "urika.toml").write_text(
            "[notifications]\nenabled = true\n"
        )
        _global, enabled, _extra = _load_notification_config(tmp_path)
        assert enabled == {"email", "slack", "telegram"}

    def test_build_bus_returns_none_no_project(self, tmp_path, monkeypatch):
        """No project notifications -> None."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        result = build_bus(tmp_path)
        assert result is None

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
        _fake_home(tmp_path, monkeypatch)  # No global config
        (tmp_path / "urika.toml").write_text(
            '[notifications]\nchannels = ["email"]\n'
        )
        with caplog.at_level(logging.WARNING):
            bus = build_bus(tmp_path)
        assert bus is None
        assert "not configured globally" in caplog.text
