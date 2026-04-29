"""Anthropic-compliance surfaces in the CLI.

Per Anthropic's Consumer Terms §3.7 and the April 2026 Agent SDK
clarification, Urika cannot use a Pro/Max OAuth token to authenticate
the Agent SDK. ``ANTHROPIC_API_KEY`` is required.

The CLI prints a one-time warning at startup when the key is unset (and
``URIKA_ACK_API_KEY_REQUIRED`` is unset). It also exposes
``urika config api-key`` as an interactive setup command that writes
the key to ``~/.urika/secrets.env`` via ``urika.core.secrets.save_secret``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from urika.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def urika_env(tmp_path: Path) -> dict[str, str]:
    """Minimal env with URIKA_HOME pointed at a tmp dir."""
    urika_home = tmp_path / ".urika"
    urika_home.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    return {
        "URIKA_HOME": str(urika_home),
        "URIKA_PROJECTS_DIR": str(projects_dir),
    }


# ---- Startup warning ------------------------------------------------------


def test_warning_prints_when_api_key_missing(
    runner: CliRunner, urika_env: dict[str, str], monkeypatch
) -> None:
    """When ANTHROPIC_API_KEY is unset, the CLI banner mentions it."""
    # CliRunner's ``env=`` *adds* to os.environ; it does not unset
    # already-present vars. Use monkeypatch to clear the developer's
    # real key + force load_secrets() to be a no-op.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("URIKA_ACK_API_KEY_REQUIRED", raising=False)
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)

    result = runner.invoke(cli, ["list"], env=urika_env)
    assert result.exit_code == 0
    assert "ANTHROPIC_API_KEY not set" in result.output
    # Banner cites the Anthropic policy; the literal string crosses a
    # line break so check tokens individually.
    assert "Consumer" in result.output
    assert "Agent SDK" in result.output


def test_warning_silenced_when_api_key_set(
    runner: CliRunner, urika_env: dict[str, str], monkeypatch
) -> None:
    """When ANTHROPIC_API_KEY is set, the warning does not print."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake")
    monkeypatch.delenv("URIKA_ACK_API_KEY_REQUIRED", raising=False)
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)

    result = runner.invoke(cli, ["list"], env=urika_env)
    assert result.exit_code == 0
    assert "ANTHROPIC_API_KEY not set" not in result.output


def test_warning_silenced_when_ack_env_set(
    runner: CliRunner, urika_env: dict[str, str], monkeypatch
) -> None:
    """``URIKA_ACK_API_KEY_REQUIRED=1`` silences the warning even when the
    key is unset (e.g. user is intentionally running private-mode-only).
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("URIKA_ACK_API_KEY_REQUIRED", "1")
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)

    result = runner.invoke(cli, ["list"], env=urika_env)
    assert result.exit_code == 0
    assert "ANTHROPIC_API_KEY not set" not in result.output


# ---- urika config api-key -------------------------------------------------


def test_config_api_key_saves_to_secrets_env(
    runner: CliRunner, urika_env: dict[str, str], tmp_path: Path
) -> None:
    """``urika config api-key`` calls save_secret with the typed value."""
    env = dict(urika_env)
    env["ANTHROPIC_API_KEY"] = "sk-ant-existing"  # silence the banner
    env["URIKA_ACK_API_KEY_REQUIRED"] = "1"

    fake_key = "sk-ant-" + "a" * 90  # passes the length check
    # Provide stdin: key + (no spend limit prompt) "n"
    stdin = f"{fake_key}\nn\n"

    with patch("urika.core.secrets.save_secret") as save_mock:
        result = runner.invoke(cli, ["config", "api-key"], input=stdin, env=env)

    assert result.exit_code == 0, result.output
    save_mock.assert_called_once()
    args, _kwargs = save_mock.call_args
    assert args[0] == "ANTHROPIC_API_KEY"
    assert args[1] == fake_key
    assert "Saved to ~/.urika/secrets.env" in result.output


def test_config_api_key_blank_input_cancels(
    runner: CliRunner, urika_env: dict[str, str]
) -> None:
    """Empty input does not call save_secret."""
    env = dict(urika_env)
    env["ANTHROPIC_API_KEY"] = "sk-ant-existing"
    env["URIKA_ACK_API_KEY_REQUIRED"] = "1"

    with patch("urika.core.secrets.save_secret") as save_mock:
        result = runner.invoke(cli, ["config", "api-key"], input="\n", env=env)

    assert result.exit_code == 0
    save_mock.assert_not_called()


def test_config_api_key_warns_on_bad_format_then_aborts(
    runner: CliRunner, urika_env: dict[str, str]
) -> None:
    """A non-Anthropic-looking key produces a warning + 'save anyway' prompt;
    answering N skips the save."""
    env = dict(urika_env)
    env["ANTHROPIC_API_KEY"] = "sk-ant-existing"
    env["URIKA_ACK_API_KEY_REQUIRED"] = "1"

    # Bad format key + "N" to the confirm prompt.
    with patch("urika.core.secrets.save_secret") as save_mock:
        result = runner.invoke(
            cli, ["config", "api-key"], input="not-a-real-key\nn\n", env=env
        )

    assert result.exit_code == 0
    save_mock.assert_not_called()
    assert "does not look like" in result.output


def test_config_api_key_save_anyway_overrides_format_warning(
    runner: CliRunner, urika_env: dict[str, str]
) -> None:
    """Answering Y to 'Save anyway?' persists the bad-format key."""
    env = dict(urika_env)
    env["ANTHROPIC_API_KEY"] = "sk-ant-existing"
    env["URIKA_ACK_API_KEY_REQUIRED"] = "1"

    bad_key = "definitely-not-anthropic"
    # bad key + "y" to save-anyway + "n" to spend-limit prompt
    stdin = f"{bad_key}\ny\nn\n"

    with patch("urika.core.secrets.save_secret") as save_mock:
        result = runner.invoke(cli, ["config", "api-key"], input=stdin, env=env)

    assert result.exit_code == 0, result.output
    save_mock.assert_called_once_with("ANTHROPIC_API_KEY", bad_key)
