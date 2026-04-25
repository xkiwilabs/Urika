"""Tests for ``urika.core.settings`` — global ~/.urika/settings.toml.

Covers the default-getter helpers and the ``auto_enable`` notification
flag introduced for the unified global-auto-enable + 2-state per-project
notification model.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def urika_home(tmp_path: Path, monkeypatch) -> Path:
    """Point ``URIKA_HOME`` at a tmp dir so settings round-trip there."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    return home


def test_load_settings_returns_empty_dict_when_no_file(urika_home):
    from urika.core.settings import load_settings

    assert load_settings() == {}


def test_save_then_load_roundtrips(urika_home):
    from urika.core.settings import load_settings, save_settings

    save_settings({"preferences": {"audience": "expert"}})
    s = load_settings()
    assert s["preferences"]["audience"] == "expert"


def test_get_default_notifications_auto_enable_defaults_all_false(urika_home):
    """No settings file → all channels default to False."""
    from urika.core.settings import get_default_notifications_auto_enable

    out = get_default_notifications_auto_enable()
    assert out == {"email": False, "slack": False, "telegram": False}


def test_get_default_notifications_auto_enable_reads_flags(urika_home):
    """``auto_enable=true`` per channel surfaces in the helper output."""
    from urika.core.settings import (
        get_default_notifications_auto_enable,
        save_settings,
    )

    save_settings(
        {
            "notifications": {
                "email": {"from_addr": "x@y.com", "auto_enable": True},
                "slack": {"channel": "#x", "auto_enable": False},
                "telegram": {"chat_id": "1", "auto_enable": True},
            }
        }
    )
    out = get_default_notifications_auto_enable()
    assert out == {"email": True, "slack": False, "telegram": True}


def test_get_default_notifications_auto_enable_roundtrips(urika_home):
    """The flag persists through load_settings/save_settings."""
    from urika.core.settings import (
        get_default_notifications_auto_enable,
        load_settings,
        save_settings,
    )

    save_settings(
        {"notifications": {"email": {"from_addr": "x@y.com", "auto_enable": True}}}
    )
    s = load_settings()
    assert s["notifications"]["email"]["auto_enable"] is True

    out = get_default_notifications_auto_enable()
    assert out["email"] is True


def test_get_default_notifications_auto_enable_missing_channel_is_false(urika_home):
    """Channels not present in the file return False."""
    from urika.core.settings import (
        get_default_notifications_auto_enable,
        save_settings,
    )

    # Only email is configured globally
    save_settings(
        {"notifications": {"email": {"from_addr": "x@y.com", "auto_enable": True}}}
    )
    out = get_default_notifications_auto_enable()
    assert out["email"] is True
    assert out["slack"] is False
    assert out["telegram"] is False
