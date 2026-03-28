"""Tests for notification config loading and bus building."""

from __future__ import annotations

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
[notifications]
enabled = true

[notifications.email]
to = ["global@example.com"]
smtp_server = "smtp.example.com"
from_addr = "urika@example.com"
"""


class TestLoadConfig:
    def test_no_config_anywhere(self, tmp_path, monkeypatch):
        """No global and no project config -> empty dict."""
        _fake_home(tmp_path, monkeypatch)
        config = _load_notification_config(tmp_path)
        assert config == {}

    def test_global_only_no_project_opt_in(self, tmp_path, monkeypatch):
        """Global config exists but project has no [notifications] -> off."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        # Project toml with no notifications section
        (tmp_path / "urika.toml").write_text("[project]\nname = 'test'\n")
        config = _load_notification_config(tmp_path)
        assert config == {}

    def test_project_opt_in_uses_global(self, tmp_path, monkeypatch):
        """Project enabled = true inherits global channel settings."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text(
            "[notifications]\nenabled = true\n"
        )
        config = _load_notification_config(tmp_path)
        assert config["enabled"] is True
        assert config["email"]["to"] == ["global@example.com"]
        assert config["email"]["smtp_server"] == "smtp.example.com"

    def test_project_adds_extra_recipients(self, tmp_path, monkeypatch):
        """Project adds extra to emails without replacing global ones."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text("""\
[notifications]
enabled = true

[notifications.email]
to = ["project@example.com"]
""")
        config = _load_notification_config(tmp_path)
        assert "global@example.com" in config["email"]["to"]
        assert "project@example.com" in config["email"]["to"]

    def test_project_no_duplicate_recipients(self, tmp_path, monkeypatch):
        """Same address in global and project -> no duplicates."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text("""\
[notifications]
enabled = true

[notifications.email]
to = ["global@example.com", "extra@example.com"]
""")
        config = _load_notification_config(tmp_path)
        assert config["email"]["to"].count("global@example.com") == 1
        assert "extra@example.com" in config["email"]["to"]

    def test_project_disabled_overrides_global(self, tmp_path, monkeypatch):
        """Project enabled = false -> off even if global is on."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text(
            "[notifications]\nenabled = false\n"
        )
        config = _load_notification_config(tmp_path)
        assert config == {}

    def test_project_enabled_no_global(self, tmp_path, monkeypatch):
        """Project has full config, no global -> works standalone."""
        _fake_home(tmp_path, monkeypatch)
        (tmp_path / "urika.toml").write_text("""\
[notifications]
enabled = true

[notifications.email]
to = ["solo@example.com"]
smtp_server = "smtp.solo.com"
from_addr = "urika@solo.com"
""")
        config = _load_notification_config(tmp_path)
        assert config["enabled"] is True
        assert config["email"]["to"] == ["solo@example.com"]

    def test_build_bus_returns_none_when_disabled(self, tmp_path, monkeypatch):
        """enabled = false -> None."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text(
            "[notifications]\nenabled = false\n"
        )
        result = build_bus(tmp_path)
        assert result is None

    def test_build_bus_returns_none_when_no_config(self, tmp_path, monkeypatch):
        """No config at all -> None."""
        _fake_home(tmp_path, monkeypatch)
        result = build_bus(tmp_path)
        assert result is None

    def test_build_bus_with_email(self, tmp_path, monkeypatch):
        """Project opts in with global email config -> bus with 1 channel."""
        _fake_home(tmp_path, monkeypatch, _GLOBAL_EMAIL)
        (tmp_path / "urika.toml").write_text(
            "[notifications]\nenabled = true\n"
        )
        bus = build_bus(tmp_path)
        assert bus is not None
        assert len(bus.channels) == 1
        from urika.notifications.email_channel import EmailChannel

        assert isinstance(bus.channels[0], EmailChannel)
