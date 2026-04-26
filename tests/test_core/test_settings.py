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


def test_get_default_privacy_returns_endpoints_only(urika_home):
    """get_default_privacy() exposes endpoints but NOT a mode key —
    there is no system-wide default privacy mode any more."""
    from urika.core.settings import get_default_privacy, save_settings

    save_settings(
        {
            "privacy": {
                "mode": "private",  # legacy, ignored
                "endpoints": {
                    "private": {
                        "base_url": "http://localhost:11434",
                        "api_key_env": "",
                    }
                },
            }
        }
    )
    out = get_default_privacy()
    assert "mode" not in out
    assert out["endpoints"]["private"]["base_url"] == "http://localhost:11434"


def test_get_default_privacy_no_file_returns_empty_endpoints(urika_home):
    """No settings file → get_default_privacy returns empty endpoints
    dict, no mode key."""
    from urika.core.settings import get_default_privacy

    out = get_default_privacy()
    assert "mode" not in out
    assert out["endpoints"] == {}


# ---- get_named_endpoints ---------------------------------------------------


def test_get_named_endpoints_returns_empty_when_no_file(urika_home):
    """No settings file → ``get_named_endpoints`` returns ``[]``."""
    from urika.core.settings import get_named_endpoints

    assert get_named_endpoints() == []


def test_get_named_endpoints_returns_empty_when_no_endpoints_block(urika_home):
    """Settings file without ``[privacy.endpoints]`` → ``[]``."""
    from urika.core.settings import get_named_endpoints, save_settings

    save_settings({"preferences": {"audience": "expert"}})
    assert get_named_endpoints() == []


def test_get_named_endpoints_returns_legacy_single_private_with_empty_default_model(
    urika_home,
):
    """Old single-endpoint setup (``[privacy.endpoints.private]`` with
    just ``base_url`` + ``api_key_env``) round-trips with an empty
    ``default_model`` field."""
    from urika.core.settings import get_named_endpoints, save_settings

    save_settings(
        {
            "privacy": {
                "endpoints": {
                    "private": {
                        "base_url": "http://localhost:11434",
                        "api_key_env": "",
                    }
                }
            }
        }
    )
    eps = get_named_endpoints()
    assert len(eps) == 1
    ep = eps[0]
    assert ep["name"] == "private"
    assert ep["base_url"] == "http://localhost:11434"
    assert ep["api_key_env"] == ""
    assert ep["default_model"] == ""


def test_get_named_endpoints_returns_multiple_sorted_by_name(urika_home):
    """Multiple endpoints come back sorted alphabetically by name with
    every field surfaced."""
    from urika.core.settings import get_named_endpoints, save_settings

    save_settings(
        {
            "privacy": {
                "endpoints": {
                    "private": {
                        "base_url": "http://localhost:11434",
                        "api_key_env": "",
                        "default_model": "qwen3:14b",
                    },
                    "ollama": {
                        "base_url": "http://localhost:11435",
                        "api_key_env": "",
                        "default_model": "llama3:8b",
                    },
                }
            }
        }
    )
    eps = get_named_endpoints()
    assert [e["name"] for e in eps] == ["ollama", "private"]
    ollama = eps[0]
    assert ollama["base_url"] == "http://localhost:11435"
    assert ollama["default_model"] == "llama3:8b"
    private = eps[1]
    assert private["base_url"] == "http://localhost:11434"
    assert private["default_model"] == "qwen3:14b"


def test_get_named_endpoints_skips_non_dict_entries(urika_home, monkeypatch):
    """A malformed (non-dict) endpoint value is silently skipped."""
    from urika.core import settings as settings_mod

    monkeypatch.setattr(
        settings_mod,
        "load_settings",
        lambda: {
            "privacy": {
                "endpoints": {
                    "ok": {"base_url": "http://x", "api_key_env": ""},
                    "bad": "not-a-dict",
                }
            }
        },
    )
    eps = settings_mod.get_named_endpoints()
    assert [e["name"] for e in eps] == ["ok"]
