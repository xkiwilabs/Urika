"""Tests for ``urika notifications`` (the CLI subcommand).

Pre-this-file the @cli.command at config_notifications.py:17 was
*never* invoked by a CliRunner test. The seed helper had its own tests
but the CLI surface (--show/--test/--disable, --project, interactive
mode) was unverified.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from urika.cli import cli


@pytest.fixture
def urika_env(tmp_path: Path, monkeypatch) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setenv("URIKA_PROJECTS_DIR", str(projects))
    return {
        "URIKA_HOME": str(home),
        "URIKA_PROJECTS_DIR": str(projects),
    }


def _seed_global_settings(home: Path, payload: str) -> None:
    (home / "settings.toml").write_text(payload, encoding="utf-8")


def _seed_project(
    home: Path, projects_dir: Path, name: str, *, channels: list[str] | None = None
) -> Path:
    proj = projects_dir / name
    proj.mkdir()
    body = (
        f'[project]\nname = "{name}"\nquestion = "?"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    if channels:
        body += f"\n[notifications]\nchannels = {json.dumps(channels)}\n"
    (proj / "urika.toml").write_text(body, encoding="utf-8")
    (home / "projects.json").write_text(json.dumps({name: str(proj)}), encoding="utf-8")
    return proj


# ── --show ─────────────────────────────────────────────────────


def test_show_global_with_no_config(urika_env) -> None:
    _seed_global_settings(Path(urika_env["URIKA_HOME"]), "")
    r = CliRunner().invoke(cli, ["notifications", "--show"], env=urika_env)
    assert r.exit_code == 0, r.output
    assert "not configured" in r.output.lower()


def test_show_global_with_email_configured(urika_env) -> None:
    _seed_global_settings(
        Path(urika_env["URIKA_HOME"]),
        "[notifications.email]\n"
        'from_addr = "alice@example.com"\n'
        'to = "bob@example.com"\n'
        'smtp_server = "smtp.example.com"\nsmtp_port = 587\n',
    )
    r = CliRunner().invoke(cli, ["notifications", "--show"], env=urika_env)
    assert r.exit_code == 0, r.output
    assert "alice@example.com" in r.output
    assert "bob@example.com" in r.output


def test_show_project_lists_enabled_channels(urika_env) -> None:
    _seed_global_settings(Path(urika_env["URIKA_HOME"]), "")
    _seed_project(
        Path(urika_env["URIKA_HOME"]),
        Path(urika_env["URIKA_PROJECTS_DIR"]),
        "alpha",
        channels=["email"],
    )
    r = CliRunner().invoke(
        cli, ["notifications", "--show", "--project", "alpha"], env=urika_env
    )
    assert r.exit_code == 0, r.output
    assert "alpha" in r.output
    assert "email" in r.output.lower()


def test_show_project_with_no_channels_explains_empty_state(urika_env) -> None:
    _seed_global_settings(Path(urika_env["URIKA_HOME"]), "")
    _seed_project(
        Path(urika_env["URIKA_HOME"]),
        Path(urika_env["URIKA_PROJECTS_DIR"]),
        "alpha",
    )
    r = CliRunner().invoke(
        cli, ["notifications", "--show", "--project", "alpha"], env=urika_env
    )
    assert r.exit_code == 0, r.output
    assert "no channels enabled" in r.output.lower()


# ── --disable ──────────────────────────────────────────────────


def test_disable_global_explains_project_only(urika_env) -> None:
    """``--disable`` is project-level; running globally must explain
    that, not silently no-op or crash."""
    _seed_global_settings(Path(urika_env["URIKA_HOME"]), "")
    r = CliRunner().invoke(cli, ["notifications", "--disable"], env=urika_env)
    assert r.exit_code == 0, r.output
    assert "project" in r.output.lower()


def test_disable_clears_project_channels(urika_env) -> None:
    _seed_global_settings(Path(urika_env["URIKA_HOME"]), "")
    proj = _seed_project(
        Path(urika_env["URIKA_HOME"]),
        Path(urika_env["URIKA_PROJECTS_DIR"]),
        "alpha",
        channels=["email", "slack"],
    )
    r = CliRunner().invoke(
        cli, ["notifications", "--disable", "--project", "alpha"], env=urika_env
    )
    assert r.exit_code == 0, r.output
    # The project's [notifications].channels is now empty.
    import tomllib

    data = tomllib.loads((proj / "urika.toml").read_text("utf-8"))
    assert data.get("notifications", {}).get("channels", []) == []


# ── --test ─────────────────────────────────────────────────────


def test_test_send_with_no_channels_reports_nothing_to_send(
    urika_env, monkeypatch
) -> None:
    """``--test`` against an empty config must not crash; it should
    report there's nothing configured."""
    _seed_global_settings(Path(urika_env["URIKA_HOME"]), "")
    r = CliRunner().invoke(cli, ["notifications", "--test"], env=urika_env)
    # Must not 500 / crash; exit code 0 or 1 is acceptable, output
    # must not be empty.
    assert r.exit_code in (0, 1), r.output
    assert r.output.strip(), "no output from --test on empty config"


# ── --project for unknown name ─────────────────────────────────


def test_project_unknown_name_raises_clickexception(urika_env) -> None:
    _seed_global_settings(Path(urika_env["URIKA_HOME"]), "")
    r = CliRunner().invoke(
        cli,
        ["notifications", "--show", "--project", "does-not-exist"],
        env=urika_env,
    )
    assert r.exit_code != 0


# ── interactive (non-TTY → cancels cleanly) ────────────────────


def test_interactive_no_tty_cancels_gracefully(urika_env) -> None:
    """Without flags, the command enters interactive mode; under
    CliRunner (no TTY) it should catch UserCancelled / EOF and exit
    cleanly with a "Cancelled" message, not hang or 5xx."""
    _seed_global_settings(Path(urika_env["URIKA_HOME"]), "")
    r = CliRunner().invoke(cli, ["notifications"], env=urika_env, input="\n")
    # Exit cleanly (0 or 1); must not hang.
    assert r.exit_code in (0, 1), r.output
