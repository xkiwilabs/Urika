"""Tests for CLI notifications helpers.

Covers ``seed_project_notifications_from_global`` — the non-interactive
helper that ``urika new`` uses to seed a fresh project's
``[notifications].channels`` list from the global per-channel
``auto_enable`` flags.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


@pytest.fixture
def urika_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    return home


def _make_project(tmp_path: Path, name: str = "proj") -> Path:
    """Create a minimal urika.toml so the seeding helper can mutate it."""
    p = tmp_path / name
    p.mkdir()
    (p / "urika.toml").write_text(
        f"[project]\n"
        f'name = "{name}"\n'
        f'question = "?"\n'
        f'mode = "exploratory"\n'
        f'description = ""\n',
        encoding="utf-8",
    )
    return p


def test_seed_no_auto_enable_returns_empty_list(urika_home, tmp_path):
    """No global ``auto_enable`` flags → no channels seeded, nothing written."""
    from urika.cli.config_notifications import seed_project_notifications_from_global

    project = _make_project(tmp_path)
    seeded = seed_project_notifications_from_global(project)
    assert seeded == []
    data = tomllib.loads((project / "urika.toml").read_text(encoding="utf-8"))
    assert "notifications" not in data


def test_seed_email_auto_enable_writes_channels(urika_home, tmp_path):
    """``auto_enable=true`` for email seeds ``channels = ['email']``."""
    from urika.cli.config_notifications import seed_project_notifications_from_global
    from urika.core.settings import save_settings

    save_settings(
        {
            "notifications": {
                "email": {"from_addr": "x@y.com", "auto_enable": True},
                "slack": {"channel": "#x", "auto_enable": False},
            }
        }
    )
    project = _make_project(tmp_path)
    seeded = seed_project_notifications_from_global(project)
    assert seeded == ["email"]
    data = tomllib.loads((project / "urika.toml").read_text(encoding="utf-8"))
    assert data["notifications"]["channels"] == ["email"]


def test_seed_multiple_channels_auto_enabled(urika_home, tmp_path):
    """Every channel with ``auto_enable=true`` ends up in the list."""
    from urika.cli.config_notifications import seed_project_notifications_from_global
    from urika.core.settings import save_settings

    save_settings(
        {
            "notifications": {
                "email": {"from_addr": "x@y.com", "auto_enable": True},
                "slack": {"channel": "#x", "auto_enable": True},
                "telegram": {"chat_id": "1", "auto_enable": False},
            }
        }
    )
    project = _make_project(tmp_path)
    seeded = seed_project_notifications_from_global(project)
    assert sorted(seeded) == ["email", "slack"]
    data = tomllib.loads((project / "urika.toml").read_text(encoding="utf-8"))
    assert sorted(data["notifications"]["channels"]) == ["email", "slack"]


def test_seed_no_urika_toml_returns_empty(urika_home, tmp_path):
    """If urika.toml doesn't exist, seeding is a silent no-op."""
    from urika.cli.config_notifications import seed_project_notifications_from_global
    from urika.core.settings import save_settings

    save_settings(
        {
            "notifications": {
                "email": {"from_addr": "x@y.com", "auto_enable": True},
            }
        }
    )
    nonexistent = tmp_path / "no-such-project"
    nonexistent.mkdir()
    seeded = seed_project_notifications_from_global(nonexistent)
    assert seeded == []


def test_seed_preserves_existing_notifications_section(urika_home, tmp_path):
    """If the project already has a [notifications] block (e.g. with
    per-channel overrides), seeding only sets the channels list."""
    from urika.cli.config_notifications import seed_project_notifications_from_global
    from urika.core.settings import save_settings

    save_settings(
        {
            "notifications": {
                "email": {"from_addr": "x@y.com", "auto_enable": True},
            }
        }
    )
    project = _make_project(tmp_path)
    # Pre-populate per-channel override
    toml_path = project / "urika.toml"
    toml_path.write_text(
        toml_path.read_text(encoding="utf-8")
        + '\n[notifications.email]\nextra_to = ["alice@x.com"]\n',
        encoding="utf-8",
    )
    seeded = seed_project_notifications_from_global(project)
    assert seeded == ["email"]
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    assert data["notifications"]["channels"] == ["email"]
    # Existing override survives
    assert data["notifications"]["email"]["extra_to"] == ["alice@x.com"]
