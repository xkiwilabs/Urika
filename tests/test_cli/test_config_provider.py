"""Tests for ``urika config anthropic|openai|google`` provider auth setup.

v0.7.0 Task 4.2 — these commands let users explicitly opt in to either the
Anthropic-API-key (default, pre-v0.7.0 behaviour) or the post-June-15-2026
``claude login`` subscription auth path, and reject OpenAI/Google
subscription pseudo-modes with an explanatory error.

Settings are written to ``[anthropic|openai|google] auth = "..."`` in
``~/.urika/settings.toml`` via :func:`urika.core.settings.save_settings`.
The Anthropic side of the contract is consumed by
``urika.core.compliance._get_anthropic_auth_preference`` (Task 4.1).
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from urika.cli import cli


def _settings_text(home: Path) -> str:
    settings_file = home / "settings.toml"
    assert settings_file.exists(), f"settings.toml not written at {settings_file}"
    return settings_file.read_text(encoding="utf-8")


def test_config_anthropic_subscription_writes_preference(tmp_path, monkeypatch):
    """``urika config anthropic --mode subscription --no-verify`` writes ``auth = "subscription"``."""
    home = tmp_path / "urika"
    monkeypatch.setenv("URIKA_HOME", str(home))
    runner = CliRunner()
    result = runner.invoke(
        cli, ["config", "anthropic", "--mode", "subscription", "--no-verify"]
    )
    assert result.exit_code == 0, result.output
    text = _settings_text(home)
    assert "subscription" in text
    assert 'auth = "subscription"' in text
    # The user-visible hint should mention `claude login`.
    assert "claude login" in result.output


def test_config_anthropic_api_key_writes_preference(tmp_path, monkeypatch):
    """``urika config anthropic --mode api_key`` writes ``auth = "api_key"``."""
    home = tmp_path / "urika"
    monkeypatch.setenv("URIKA_HOME", str(home))
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "anthropic", "--mode", "api_key"])
    assert result.exit_code == 0, result.output
    text = _settings_text(home)
    assert 'auth = "api_key"' in text
    # The user-visible hint should mention ANTHROPIC_API_KEY discovery.
    assert "ANTHROPIC_API_KEY" in result.output


def test_config_anthropic_subscription_no_verify_skips_claude_probe(
    tmp_path, monkeypatch
):
    """``--no-verify`` must skip the ``claude --version`` subprocess probe."""
    home = tmp_path / "urika"
    monkeypatch.setenv("URIKA_HOME", str(home))

    def _boom(*args, **kwargs):  # pragma: no cover - asserts via call
        raise AssertionError(
            "subprocess.run must not be called when --no-verify is set"
        )

    monkeypatch.setattr("subprocess.run", _boom)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["config", "anthropic", "--mode", "subscription", "--no-verify"]
    )
    assert result.exit_code == 0, result.output


def test_config_anthropic_subscription_verify_warns_when_claude_missing(
    tmp_path, monkeypatch
):
    """Without ``--no-verify``, a missing ``claude`` CLI surfaces a warning but still exits 0."""
    home = tmp_path / "urika"
    monkeypatch.setenv("URIKA_HOME", str(home))

    def _missing(*args, **kwargs):
        raise FileNotFoundError("no claude CLI")

    monkeypatch.setattr("subprocess.run", _missing)
    # Click 8.2 removed CliRunner(mix_stderr=...) — assert against mixed output instead.
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "anthropic", "--mode", "subscription"])
    assert result.exit_code == 0, result.output
    # Warning surfaces in the mixed stdout/stderr stream.
    assert "claude" in result.output
    # Setting is still written.
    assert 'auth = "subscription"' in _settings_text(home)


def test_config_openai_rejects_subscription(tmp_path, monkeypatch):
    """``urika config openai --mode subscription`` errors with an explanatory message and writes no setting."""
    home = tmp_path / "urika"
    monkeypatch.setenv("URIKA_HOME", str(home))
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "openai", "--mode", "subscription"])
    assert result.exit_code != 0
    # Error message names the API key path as the supported alternative.
    assert "API key" in result.output or "api_key" in result.output
    # Nothing must be written.
    assert not (home / "settings.toml").exists()


def test_config_openai_api_key_writes_preference(tmp_path, monkeypatch):
    """``urika config openai --mode api_key`` writes ``[openai] auth = "api_key"``."""
    home = tmp_path / "urika"
    monkeypatch.setenv("URIKA_HOME", str(home))
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "openai", "--mode", "api_key"])
    assert result.exit_code == 0, result.output
    text = _settings_text(home)
    assert "[openai]" in text
    assert 'auth = "api_key"' in text
    assert "OPENAI_API_KEY" in result.output


def test_config_google_rejects_subscription(tmp_path, monkeypatch):
    """``urika config google --mode subscription`` errors mentioning Google's ToS and writes no setting."""
    home = tmp_path / "urika"
    monkeypatch.setenv("URIKA_HOME", str(home))
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "google", "--mode", "subscription"])
    assert result.exit_code != 0
    assert "Google" in result.output
    assert not (home / "settings.toml").exists()


def test_config_google_api_key_writes_preference(tmp_path, monkeypatch):
    """``urika config google --mode api_key`` writes ``[google] auth = "api_key"``."""
    home = tmp_path / "urika"
    monkeypatch.setenv("URIKA_HOME", str(home))
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "google", "--mode", "api_key"])
    assert result.exit_code == 0, result.output
    text = _settings_text(home)
    assert "[google]" in text
    assert 'auth = "api_key"' in text
    assert "GEMINI_API_KEY" in result.output


def test_config_anthropic_preserves_existing_settings(tmp_path, monkeypatch):
    """Writing the auth preference must not clobber unrelated settings sections."""
    home = tmp_path / "urika"
    home.mkdir(parents=True)
    # Seed an existing settings file with an unrelated section.
    (home / "settings.toml").write_text(
        "[preferences]\nweb_search = true\n", encoding="utf-8"
    )
    monkeypatch.setenv("URIKA_HOME", str(home))
    runner = CliRunner()
    result = runner.invoke(
        cli, ["config", "anthropic", "--mode", "subscription", "--no-verify"]
    )
    assert result.exit_code == 0, result.output
    text = _settings_text(home)
    assert 'auth = "subscription"' in text
    assert "[preferences]" in text
    assert "web_search = true" in text
