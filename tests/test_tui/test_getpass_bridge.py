"""Tests for the TUI getpass bridge — v0.4.2 C8 regression suite.

Pre-v0.4.2 ``click.prompt(hide_input=True)`` (used by
``urika config api-key`` and the SMTP password prompt in
``urika notifications``) called Click's default ``hidden_prompt_func``,
which delegates to ``getpass.getpass``. On POSIX,
``getpass.getpass`` opens ``/dev/tty`` directly, bypassing both
``sys.stdin`` and the TUI's stdin bridge — so the prompt blocked
indefinitely waiting for input that never arrived.

These tests verify the patch installed by
``urika.tui.agent_worker._install_getpass_bridge``:

- The patch is idempotent (re-import doesn't re-wrap).
- Calls fall through to the original when stdin is NOT bridged.
- Calls read from the bridge when stdin IS bridged.
"""

from __future__ import annotations

import io
import sys
from unittest.mock import patch


def test_patch_installed_at_import():
    import click.termui

    import urika.tui.agent_worker  # noqa: F401 — ensures patch ran

    assert getattr(click.termui, "_urika_getpass_patched", False) is True


def test_patch_idempotent():
    import click.termui

    import urika.tui.agent_worker

    first = click.termui.hidden_prompt_func
    urika.tui.agent_worker._install_getpass_bridge()
    second = click.termui.hidden_prompt_func
    assert first is second, "Re-installing should not wrap a second time"


def test_falls_through_when_stdin_not_bridged(monkeypatch):
    """Without the ``_tui_bridge`` marker, the patched function must
    forward to the original implementation so plain shell users keep
    getting real password masking via ``getpass.getpass``."""
    import click.termui

    import urika.tui.agent_worker  # noqa: F401

    # Plain stdin (no marker).
    plain = io.StringIO()
    monkeypatch.setattr(sys, "stdin", plain)

    captured: dict[str, object] = {}

    def fake_original(prompt: str) -> str:
        captured["called"] = True
        captured["prompt"] = prompt
        return "shell-password"

    # The patched function closed over the ORIGINAL hidden_prompt_func
    # at install time, so we need to monkeypatch the module-level
    # reference the patch captured. Easiest is to reach into the
    # closure — but cleaner is to verify by behaviour: a non-bridged
    # stdin must NOT go through the bridge code path. We assert the
    # negative: that the patched function does NOT pull from the
    # plain StringIO (which would happen if it mistakenly treated
    # plain stdin as bridged).
    plain.write("from-stringio\n")
    plain.seek(0)

    # Use the (real) patched function. Since we have no _tui_bridge
    # marker on the StringIO, the patched function should defer to
    # the original — which on a non-tty test session calls
    # getpass.getpass. We patch getpass.getpass to a sentinel so we
    # don't actually try to read /dev/tty.
    with patch("getpass.getpass", return_value="real-getpass-path"):
        result = click.termui.hidden_prompt_func("Pass: ")

    # When falling through, the result comes from the underlying
    # original (which we mocked to "real-getpass-path"). The
    # StringIO must NOT have been read.
    assert result == "real-getpass-path"
    # Confirm the bridge did NOT consume the StringIO.
    assert plain.read() == "from-stringio\n"


def test_reads_from_bridge_when_marker_present(monkeypatch):
    """When ``sys.stdin`` has the ``_tui_bridge`` marker, the patched
    function reads via ``readline()`` — the path the TUI's
    ``_TuiStdinReader`` exposes."""
    import click.termui

    import urika.tui.agent_worker  # noqa: F401

    class FakeBridge:
        _tui_bridge = True

        def __init__(self) -> None:
            self._line = "secret-from-bridge\n"

        def readline(self) -> str:
            return self._line

    monkeypatch.setattr(sys, "stdin", FakeBridge())
    # Also redirect stdout so we capture the prompt write.
    captured_out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured_out)

    result = click.termui.hidden_prompt_func("API key: ")

    assert result == "secret-from-bridge"  # newline stripped
    assert "API key: " in captured_out.getvalue()


def test_strips_trailing_crlf(monkeypatch):
    """Bridge readline can include ``\\r\\n`` on Windows-style input;
    the patched function must strip both."""
    import click.termui

    import urika.tui.agent_worker  # noqa: F401

    class FakeBridge:
        _tui_bridge = True

        def readline(self) -> str:
            return "windows-style\r\n"

    monkeypatch.setattr(sys, "stdin", FakeBridge())
    monkeypatch.setattr(sys, "stdout", io.StringIO())

    assert click.termui.hidden_prompt_func("p: ") == "windows-style"
