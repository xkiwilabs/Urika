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


class TestGetDefaultRuntimePerMode:
    """``get_default_runtime(mode)`` prefers ``[runtime.modes.<mode>].model``
    over the legacy flat ``[runtime].model`` key, matching the canonical
    write path used by the dashboard's Models tab. Without this,
    ``urika new`` silently ignored every global default the user had
    set in 0.3.0/0.3.1.
    """

    def test_per_mode_model_preferred_over_flat_model(self, urika_home):
        from urika.core.settings import get_default_runtime, save_settings

        save_settings(
            {
                "runtime": {
                    "model": "claude-sonnet-4-5",  # legacy flat
                    "modes": {
                        "open": {"model": "claude-opus-4-6"},
                    },
                }
            }
        )
        rt = get_default_runtime("open")
        assert rt["model"] == "claude-opus-4-6"

    def test_falls_back_to_flat_model_when_mode_missing(self, urika_home):
        from urika.core.settings import get_default_runtime, save_settings

        save_settings(
            {
                "runtime": {
                    "model": "claude-sonnet-4-5",
                    "modes": {"open": {}},  # no model under open
                }
            }
        )
        rt = get_default_runtime("open")
        assert rt["model"] == "claude-sonnet-4-5"

    def test_no_mode_argument_uses_legacy_flat_model(self, urika_home):
        from urika.core.settings import get_default_runtime, save_settings

        save_settings(
            {
                "runtime": {
                    "model": "claude-haiku-4-5",
                    "modes": {"open": {"model": "claude-opus-4-6"}},
                }
            }
        )
        rt = get_default_runtime()  # no mode → legacy behavior
        assert rt["model"] == "claude-haiku-4-5"


class TestMigrate437Pins:
    """One-shot migration rewrites stale ``claude-opus-4-7`` model pins
    (a 0.3.0/0.3.1 dashboard default) to ``claude-opus-4-6``. Idempotent
    via marker file. Backs up the original to ``settings.toml.pre-0.3.2.bak``.
    """

    def test_rewrites_per_mode_default_and_per_agent(self, urika_home, capsys):
        from urika.core.settings import (
            load_settings,
            migrate_settings,
            save_settings,
        )

        save_settings(
            {
                "runtime": {
                    "modes": {
                        "open": {
                            "model": "claude-opus-4-7",
                            "models": {
                                "advisor_agent": {
                                    "model": "claude-opus-4-7",
                                    "endpoint": "open",
                                },
                                "task_agent": {
                                    "model": "claude-sonnet-4-5",
                                    "endpoint": "open",
                                },
                            },
                        }
                    }
                }
            }
        )
        migrate_settings()

        s = load_settings()
        modes = s["runtime"]["modes"]["open"]
        assert modes["model"] == "claude-opus-4-6"
        assert modes["models"]["advisor_agent"]["model"] == "claude-opus-4-6"
        # Untouched pins stay put.
        assert modes["models"]["task_agent"]["model"] == "claude-sonnet-4-5"

        # Backup file exists.
        backup = urika_home / "settings.toml.pre-0.3.2.bak"
        assert backup.exists(), "expected pre-0.3.2 backup file"

        # Marker file recorded.
        marker = urika_home / ".migrated_0.3.2"
        assert marker.exists()

        # User-visible warning printed to stderr.
        captured = capsys.readouterr()
        assert "claude-opus-4-7" in captured.err
        assert "Migrated" in captured.err

    def test_idempotent_does_not_run_twice(self, urika_home):
        from urika.core.settings import migrate_settings, save_settings, load_settings

        save_settings({"runtime": {"modes": {"open": {"model": "claude-opus-4-7"}}}})
        migrate_settings()
        # Second call should be a no-op even if we re-pin 4-7.
        save_settings({"runtime": {"modes": {"open": {"model": "claude-opus-4-7"}}}})
        migrate_settings()
        s = load_settings()
        assert s["runtime"]["modes"]["open"]["model"] == "claude-opus-4-7", (
            "second migrate call must not rewrite — marker file gates it"
        )

    def test_no_settings_file_marks_complete(self, urika_home):
        from urika.core.settings import migrate_settings

        migrate_settings()
        assert (urika_home / ".migrated_0.3.2").exists()

    def test_no_4_7_pins_marks_complete_without_backup(self, urika_home):
        from urika.core.settings import migrate_settings, save_settings

        save_settings({"runtime": {"modes": {"open": {"model": "claude-opus-4-6"}}}})
        migrate_settings()
        assert (urika_home / ".migrated_0.3.2").exists()
        assert not (urika_home / "settings.toml.pre-0.3.2.bak").exists()


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
