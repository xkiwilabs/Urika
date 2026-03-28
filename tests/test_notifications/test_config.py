"""Tests for notification config loading and bus building."""

from __future__ import annotations

from pathlib import Path

from urika.notifications import _load_notification_config, build_bus


class TestLoadConfig:
    def test_no_config(self, tmp_path):
        """No urika.toml -> empty dict."""
        config = _load_notification_config(tmp_path)
        assert config == {}

    def test_project_config(self, tmp_path):
        """urika.toml with [notifications] section."""
        toml_content = """\
[notifications]
enabled = true

[notifications.email]
to = ["test@example.com"]
smtp_server = "smtp.example.com"
from_addr = "urika@example.com"
"""
        (tmp_path / "urika.toml").write_text(toml_content)
        config = _load_notification_config(tmp_path)

        assert config["enabled"] is True
        assert config["email"]["to"] == ["test@example.com"]
        assert config["email"]["smtp_server"] == "smtp.example.com"

    def test_build_bus_returns_none_when_disabled(self, tmp_path):
        """enabled = false -> None."""
        toml_content = """\
[notifications]
enabled = false

[notifications.email]
to = ["test@example.com"]
smtp_server = "smtp.example.com"
from_addr = "urika@example.com"
"""
        (tmp_path / "urika.toml").write_text(toml_content)
        result = build_bus(tmp_path)
        assert result is None

    def test_build_bus_returns_none_when_no_channels(self, tmp_path):
        """enabled = true but no channel config -> None."""
        toml_content = """\
[notifications]
enabled = true
"""
        (tmp_path / "urika.toml").write_text(toml_content)
        result = build_bus(tmp_path)
        assert result is None

    def test_build_bus_with_email(self, tmp_path):
        """Configure email channel -> bus with 1 channel."""
        toml_content = """\
[notifications]
enabled = true

[notifications.email]
to = ["test@example.com"]
smtp_server = "smtp.example.com"
from_addr = "urika@example.com"
"""
        (tmp_path / "urika.toml").write_text(toml_content)
        bus = build_bus(tmp_path)

        assert bus is not None
        assert len(bus.channels) == 1
        from urika.notifications.email_channel import EmailChannel

        assert isinstance(bus.channels[0], EmailChannel)

    def test_build_bus_returns_none_when_no_config(self, tmp_path):
        """No config file at all -> None."""
        result = build_bus(tmp_path)
        assert result is None

    def test_global_config_fallback(self, tmp_path, monkeypatch):
        """Global settings.toml is loaded when no project config exists."""
        # Create a fake home directory with settings.toml
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        urika_dir = fake_home / ".urika"
        urika_dir.mkdir()

        global_toml = """\
[notifications]
enabled = true

[notifications.email]
to = ["global@example.com"]
smtp_server = "smtp.global.com"
from_addr = "urika@global.com"
"""
        (urika_dir / "settings.toml").write_text(global_toml)
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        config = _load_notification_config(tmp_path)
        assert config["enabled"] is True
        assert config["email"]["to"] == ["global@example.com"]

    def test_project_overrides_global(self, tmp_path, monkeypatch):
        """Project config overrides global config."""
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        urika_dir = fake_home / ".urika"
        urika_dir.mkdir()

        global_toml = """\
[notifications]
enabled = true

[notifications.email]
to = ["global@example.com"]
smtp_server = "smtp.global.com"
from_addr = "urika@global.com"
"""
        (urika_dir / "settings.toml").write_text(global_toml)
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        project_toml = """\
[notifications]
enabled = true

[notifications.email]
to = ["project@example.com"]
smtp_server = "smtp.project.com"
from_addr = "urika@project.com"
"""
        (tmp_path / "urika.toml").write_text(project_toml)

        config = _load_notification_config(tmp_path)
        assert config["email"]["to"] == ["project@example.com"]
