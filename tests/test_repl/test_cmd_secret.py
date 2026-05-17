"""REPL ``/secret`` parity test (v0.4.5 T4).

Pre-v0.4.5 the REPL had no secret-vault surface — only the CLI
(``urika config secret``) and the dashboard. ``cmd_secret`` wraps
``SecretsVault`` so list/set/delete are reachable from inside a
REPL or TUI session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.repl.commands import cmd_secret
from urika.repl.session import ReplSession


@pytest.fixture
def session(tmp_path: Path, monkeypatch) -> ReplSession:
    """REPL session pointed at a temp URIKA_HOME so vault writes
    land in the test's isolated tier (not the dev machine's real
    ``~/.urika/secrets.env``)."""
    home = tmp_path / "urika-home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    return ReplSession()


def test_list_empty_vault(session, capsys) -> None:
    cmd_secret(session, "")
    out = capsys.readouterr().out
    assert "No secrets stored." in out


def test_list_returns_known_names(session, capsys, monkeypatch) -> None:
    """Seed a couple of secrets, then ``/secret list`` should
    enumerate them by name only (no values, ever)."""
    import os

    from urika.core.registry import _urika_home
    from urika.core.vault import SecretsVault

    vault = SecretsVault(global_path=_urika_home() / "secrets.env")
    vault.set_global("ALPHA_KEY", "value-must-not-appear-in-output")
    vault.set_global("BETA_KEY", "another-secret")

    cmd_secret(session, "list")
    out = capsys.readouterr().out

    assert "ALPHA_KEY" in out
    assert "BETA_KEY" in out
    # Critical: never echo values.
    assert "value-must-not-appear-in-output" not in out
    assert "another-secret" not in out

    # ``2 secret(s)`` summary line — pinning so the count format
    # doesn't drift silently.
    assert "2 secret" in out

    # Cleanup so other tests in the same session don't see leftover
    # state from os.environ (set_global writes through to env too).
    os.environ.pop("ALPHA_KEY", None)
    os.environ.pop("BETA_KEY", None)


def test_set_refuses_without_tty(session, capsys, monkeypatch) -> None:
    """``/secret set NAME`` must refuse masked-value entry when
    stdin isn't a TTY — pytest's captured stdin returns
    ``isatty() == False`` so this exercises the refusal branch
    that's critical for TUI / CI safety (don't dump a secret value
    into scrollback)."""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)

    cmd_secret(session, "set ALPHA_KEY")
    out = capsys.readouterr().out

    assert "Secure value entry needs a real terminal" in out
    # The redirect text should mention the alternate paths.
    assert "urika config secret" in out
    assert "dashboard" in out.lower()


def test_set_without_name_prints_usage(session, capsys) -> None:
    cmd_secret(session, "set")
    out = capsys.readouterr().out
    assert "Usage: /secret set NAME" in out


def test_delete_without_name_prints_usage(session, capsys) -> None:
    cmd_secret(session, "delete")
    out = capsys.readouterr().out
    assert "Usage: /secret delete NAME" in out


def test_delete_unknown_secret_reports_missing(session, capsys) -> None:
    cmd_secret(session, "delete NONEXISTENT_KEY")
    out = capsys.readouterr().out
    assert "No secret named" in out


def test_secret_command_is_registered_as_global() -> None:
    """``/secret`` doesn't need a loaded project (vault is global).
    The registration goes into ``GLOBAL_COMMANDS`` so it's available
    from both the REPL and the TUI (which inherits the REPL
    registry)."""
    from urika.repl.commands import GLOBAL_COMMANDS, cmd_secret

    assert "secret" in GLOBAL_COMMANDS, (
        "cmd_secret should be a global command — it wraps the "
        "GLOBAL vault tier, not per-project state"
    )
    assert GLOBAL_COMMANDS["secret"]["func"] is cmd_secret
