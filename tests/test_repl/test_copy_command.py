"""Tests for the /copy slash command and its session-side ring buffer."""

from __future__ import annotations

import pytest

from urika.repl.commands import cmd_copy
from urika.repl.session import ReplSession


@pytest.fixture
def session_with_output() -> ReplSession:
    session = ReplSession()
    for i in range(1, 6):
        session.record_output_line(f"line {i}")
    return session


def test_record_output_line_appends():
    session = ReplSession()
    session.record_output_line("hello")
    session.record_output_line("world")
    assert session.recent_output_lines == ["hello", "world"]


def test_record_output_line_caps_at_configured_limit():
    session = ReplSession()
    session._recent_output_cap = 5
    for i in range(12):
        session.record_output_line(f"line {i}")
    # Oldest lines dropped, most recent 5 retained.
    assert session.recent_output_lines == [
        "line 7",
        "line 8",
        "line 9",
        "line 10",
        "line 11",
    ]


def test_copy_without_arg_uses_default_40(session_with_output, monkeypatch):
    # Stash more than 40 lines so the default matters.
    session = ReplSession()
    for i in range(100):
        session.record_output_line(f"row {i}")

    captured = {}
    monkeypatch.setattr("pyperclip.copy", lambda s: captured.update(text=s))

    cmd_copy(session, "")

    # Default N=40 → last 40 lines.
    expected = "\n".join(f"row {i}" for i in range(60, 100))
    assert captured["text"] == expected


def test_copy_with_explicit_n(session_with_output, monkeypatch):
    captured = {}
    monkeypatch.setattr("pyperclip.copy", lambda s: captured.update(text=s))

    cmd_copy(session_with_output, "2")

    assert captured["text"] == "line 4\nline 5"


def test_copy_with_invalid_arg_prints_error(session_with_output, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("pyperclip.copy", lambda s: calls.append(s))

    cmd_copy(session_with_output, "not-a-number")

    assert calls == []  # no clipboard side effect on bad input


def test_copy_with_zero_or_negative_prints_error(session_with_output, monkeypatch):
    calls = []
    monkeypatch.setattr("pyperclip.copy", lambda s: calls.append(s))

    cmd_copy(session_with_output, "0")
    cmd_copy(session_with_output, "-5")

    assert calls == []


def test_copy_with_no_buffered_output_warns(monkeypatch):
    session = ReplSession()  # no recorded lines
    calls = []
    monkeypatch.setattr("pyperclip.copy", lambda s: calls.append(s))

    cmd_copy(session, "")

    assert calls == []  # nothing to copy


def test_copy_falls_back_to_printing_on_pyperclip_error(
    session_with_output, monkeypatch, capsys
):
    """Headless Linux with no xclip/xsel raises PyperclipException — we print
    the text so the user can copy manually, but don't crash."""
    import pyperclip

    def _raise(_text):
        raise pyperclip.PyperclipException("no clipboard backend")

    monkeypatch.setattr("pyperclip.copy", _raise)

    cmd_copy(session_with_output, "3")

    # Captured stdout should include the fallback-printed lines.
    out = capsys.readouterr().out
    assert "line 3" in out
    assert "line 4" in out
    assert "line 5" in out


def test_copy_is_registered_as_global_command():
    from urika.repl.commands import GLOBAL_COMMANDS

    assert "copy" in GLOBAL_COMMANDS
    assert "Copy the last" in GLOBAL_COMMANDS["copy"]["description"]
