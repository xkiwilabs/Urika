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
    """When ANTHROPIC_API_KEY is unset, the CLI banner mentions it.

    Note: the warning is suppressed in ``--json`` mode (see _base.py)
    so JSON pipelines stay clean; this test runs without ``--json``
    so the gate is open.
    """
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
    # bad key + "y" to save-anyway + "n" to test-key prompt + "n" to spend-limit
    stdin = f"{bad_key}\ny\nn\nn\n"

    with patch("urika.core.secrets.save_secret") as save_mock:
        result = runner.invoke(cli, ["config", "api-key"], input=stdin, env=env)

    assert result.exit_code == 0, result.output
    save_mock.assert_called_once_with("ANTHROPIC_API_KEY", bad_key)


# ---- urika config api-key --test ------------------------------------------


def test_config_api_key_test_flag_with_no_key_set_errors(
    runner: CliRunner, urika_env: dict[str, str], monkeypatch
) -> None:
    """``--test`` with no key set exits 1 and shows a setup hint."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)

    env = dict(urika_env)
    env["URIKA_ACK_API_KEY_REQUIRED"] = "1"  # silence the startup banner

    result = runner.invoke(cli, ["config", "api-key", "--test"], env=env)
    assert result.exit_code == 1, result.output
    assert "ANTHROPIC_API_KEY is not set" in result.output
    assert "urika config api-key" in result.output


def test_config_api_key_test_flag_with_invalid_key_reports_401(
    runner: CliRunner, urika_env: dict[str, str], monkeypatch
) -> None:
    """``--test`` with a bad key surfaces the 401 + remediation hint."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-bogus")
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)

    with patch(
        "urika.core.anthropic_check.verify_anthropic_api_key",
        return_value=(False, "401 unauthorized — key is invalid or revoked."),
    ):
        result = runner.invoke(cli, ["config", "api-key", "--test"], env=urika_env)

    assert result.exit_code == 1, result.output
    assert "401" in result.output
    assert "API key test failed" in result.output
    # Remediation hint
    assert "console.anthropic.com" in result.output


def test_config_api_key_test_flag_with_working_key_reports_success(
    runner: CliRunner, urika_env: dict[str, str], monkeypatch
) -> None:
    """``--test`` with a working key prints success + model + reply."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-good-key-12345")
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)

    with patch(
        "urika.core.anthropic_check.verify_anthropic_api_key",
        return_value=(
            True,
            "key authenticated; model=claude-haiku-4-5; reply='ok'",
        ),
    ):
        result = runner.invoke(cli, ["config", "api-key", "--test"], env=urika_env)

    assert result.exit_code == 0, result.output
    assert "API key works" in result.output


# ---- urika config secret (generic named-secret setup) -------------------


def test_config_secret_saves_arbitrary_named_secret(
    runner: CliRunner, urika_env: dict[str, str]
) -> None:
    """``urika config secret`` calls vault.set_global with the typed value.

    This is the generic CLI surface for any credential Urika doesn't know
    about specifically (private vLLM keys, HuggingFace tokens, custom-tool
    API keys). Useful for hybrid mode setup where the data agent needs an
    api_key_env that points at a private inference endpoint.
    """
    env = dict(urika_env)
    env["ANTHROPIC_API_KEY"] = "sk-ant-existing"  # silence the banner
    env["URIKA_ACK_API_KEY_REQUIRED"] = "1"

    # Stdin: name + value + description
    stdin = "LLM_INFERENCE_KEY\nsk-private-vllm-token\nlocal vLLM\n"

    with patch("urika.core.vault.SecretsVault.set_global") as set_mock:
        result = runner.invoke(cli, ["config", "secret"], input=stdin, env=env)

    assert result.exit_code == 0, result.output
    set_mock.assert_called_once()
    args, kwargs = set_mock.call_args
    assert args[0] == "LLM_INFERENCE_KEY"
    assert args[1] == "sk-private-vllm-token"
    assert kwargs.get("description") == "local vLLM"
    # Reminds the user how to wire it into the Privacy tab
    assert "API key env var" in result.output
    assert "LLM_INFERENCE_KEY" in result.output


def test_config_secret_blank_name_cancels(
    runner: CliRunner, urika_env: dict[str, str]
) -> None:
    """No name → no save."""
    env = dict(urika_env)
    env["ANTHROPIC_API_KEY"] = "sk-ant-existing"
    env["URIKA_ACK_API_KEY_REQUIRED"] = "1"

    with patch("urika.core.vault.SecretsVault.set_global") as set_mock:
        result = runner.invoke(cli, ["config", "secret"], input="\n", env=env)

    assert result.exit_code == 0
    set_mock.assert_not_called()


def test_config_secret_warns_when_name_looks_like_value(
    runner: CliRunner, urika_env: dict[str, str]
) -> None:
    """Pasting a value into the name prompt triggers a warning + confirm.

    The Privacy tab's api_key_env field hits this same foot-gun — users
    sometimes paste the value (sk-...) thinking it's the value field.
    """
    env = dict(urika_env)
    env["ANTHROPIC_API_KEY"] = "sk-ant-existing"
    env["URIKA_ACK_API_KEY_REQUIRED"] = "1"

    # Stdin: a sk-... "name" + decline override
    stdin = "sk-pasted-value\nn\n"

    with patch("urika.core.vault.SecretsVault.set_global") as set_mock:
        result = runner.invoke(cli, ["config", "secret"], input=stdin, env=env)

    assert result.exit_code == 0
    set_mock.assert_not_called()
    assert "looks like a secret VALUE" in result.output


def test_config_api_key_test_flag_masks_key_in_output(
    runner: CliRunner, urika_env: dict[str, str], monkeypatch
) -> None:
    """The configured key must NEVER appear in full in the output."""
    secret = "sk-ant-this-is-a-real-secret-WXYZ"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)

    with patch(
        "urika.core.anthropic_check.verify_anthropic_api_key",
        return_value=(True, "key authenticated; model=claude-haiku-4-5; reply='ok'"),
    ):
        result = runner.invoke(cli, ["config", "api-key", "--test"], env=urika_env)

    assert result.exit_code == 0, result.output
    assert secret not in result.output
    # Last 4 chars are part of the masked display.
    assert "WXYZ" in result.output


def test_config_api_key_save_then_test_yes_runs_verification(
    runner: CliRunner, urika_env: dict[str, str], monkeypatch
) -> None:
    """Interactive flow: save then answer 'y' to the test prompt."""
    env = dict(urika_env)
    env["ANTHROPIC_API_KEY"] = "sk-ant-existing"
    env["URIKA_ACK_API_KEY_REQUIRED"] = "1"

    fake_key = "sk-ant-" + "a" * 90
    # key + "y" to test prompt + "n" to spend-limit prompt
    stdin = f"{fake_key}\ny\nn\n"

    with patch("urika.core.secrets.save_secret"), patch(
        "urika.core.anthropic_check.verify_anthropic_api_key",
        return_value=(True, "key authenticated; model=claude-haiku-4-5; reply='ok'"),
    ) as test_mock:
        result = runner.invoke(cli, ["config", "api-key"], input=stdin, env=env)

    assert result.exit_code == 0, result.output
    test_mock.assert_called_once_with(fake_key)
    assert "API key works" in result.output
