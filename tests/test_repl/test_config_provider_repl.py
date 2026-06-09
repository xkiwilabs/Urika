"""REPL ``/config anthropic|openai|google`` parity (v0.7.1 parity sweep).

Provider auth modes shipped in v0.7.0 for CLI + dashboard only; this
slash gives REPL/TUI users the same surface without dropping to
``urika config <provider>`` or hand-editing ``~/.urika/settings.toml``.
"""

from __future__ import annotations

from pathlib import Path

from urika.repl.commands import cmd_config
from urika.repl.session import ReplSession


def _spy(calls: list, name: str):
    def fn(*args) -> None:
        calls.append((name, args))

    return fn


def _patch_providers(monkeypatch) -> list:
    """Monkeypatch the three run_config_* functions where cmd_config
    imports them (inside-function import → patch the source module)."""
    calls: list = []
    monkeypatch.setattr(
        "urika.cli.config_provider.run_config_anthropic",
        _spy(calls, "anthropic"),
    )
    monkeypatch.setattr(
        "urika.cli.config_provider.run_config_openai",
        _spy(calls, "openai"),
    )
    monkeypatch.setattr(
        "urika.cli.config_provider.run_config_google",
        _spy(calls, "google"),
    )
    return calls


def test_anthropic_mode_subscription_dispatches(monkeypatch) -> None:
    calls = _patch_providers(monkeypatch)
    cmd_config(ReplSession(), "anthropic --mode subscription")
    assert calls == [("anthropic", ("subscription", False))]


def test_anthropic_no_verify_threads_through(monkeypatch) -> None:
    calls = _patch_providers(monkeypatch)
    cmd_config(ReplSession(), "anthropic --mode subscription --no-verify")
    assert calls == [("anthropic", ("subscription", True))]


def test_openai_dispatches_with_mode_only(monkeypatch) -> None:
    """run_config_openai takes mode only — no no_verify arg."""
    calls = _patch_providers(monkeypatch)
    cmd_config(ReplSession(), "openai --mode api_key")
    assert calls == [("openai", ("api_key",))]


def test_google_dispatches_with_mode_only(monkeypatch) -> None:
    calls = _patch_providers(monkeypatch)
    cmd_config(ReplSession(), "google --mode api_key")
    assert calls == [("google", ("api_key",))]


def test_bad_mode_errors_without_dispatch(monkeypatch, capsys) -> None:
    calls = _patch_providers(monkeypatch)
    cmd_config(ReplSession(), "anthropic --mode oauth")
    out = capsys.readouterr().out
    assert "--mode must be api_key or subscription" in out
    assert calls == []


def test_no_mode_shows_current_default(tmp_path: Path, monkeypatch, capsys) -> None:
    """The CLI requires --mode; the REPL's bare ``/config <provider>``
    shows the current mode instead (safe default: api_key)."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    calls = _patch_providers(monkeypatch)
    cmd_config(ReplSession(), "anthropic")
    out = capsys.readouterr().out
    assert "api_key" in out
    assert calls == []


def test_no_mode_shows_current_from_settings(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / "urika-home"
    home.mkdir(parents=True)
    (home / "settings.toml").write_text('[anthropic]\nauth = "subscription"\n')
    monkeypatch.setenv("URIKA_HOME", str(home))
    calls = _patch_providers(monkeypatch)
    cmd_config(ReplSession(), "anthropic")
    out = capsys.readouterr().out
    assert "subscription" in out
    assert calls == []


def test_subscription_rejection_is_echoed_not_raised(monkeypatch, capsys) -> None:
    """run_config_openai/google raise click.UsageError for subscription
    mode — the REPL must echo the message, not crash the loop."""
    import click

    def boom(mode: str) -> None:
        raise click.UsageError("OpenAI Plus subscriptions cannot be used")

    monkeypatch.setattr("urika.cli.config_provider.run_config_openai", boom)
    cmd_config(ReplSession(), "openai --mode subscription")
    out = capsys.readouterr().out
    assert "cannot be used" in out


def test_repl_provider_set_matches_cli() -> None:
    """Parity pin: the REPL accepts exactly the CLI's PROVIDER_NAMES.
    (Simple-pin variant — the cross-interface parity file gets the
    dynamic dispatch pin.)"""
    import inspect

    from urika.cli.config_provider import PROVIDER_NAMES
    from urika.repl.commands import cmd_config as fn

    src = inspect.getsource(fn)
    assert PROVIDER_NAMES == {"anthropic", "openai", "google"}
    for name in PROVIDER_NAMES:
        assert f'"{name}"' in src, f"REPL /config does not handle CLI provider {name!r}"
