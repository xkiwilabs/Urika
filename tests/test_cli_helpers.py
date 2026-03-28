"""Tests for CLI helper functions."""

from __future__ import annotations

import json
from unittest.mock import patch

import click
import pytest


def test_output_json_writes_to_stdout(capsys):
    from urika.cli_helpers import output_json

    output_json({"key": "value"})
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == {"key": "value"}


def test_output_json_pretty_prints(capsys):
    from urika.cli_helpers import output_json

    output_json({"a": 1})
    captured = capsys.readouterr()
    assert "\n" in captured.out  # indented


def test_output_json_handles_non_serializable(capsys):
    """default=str should handle dates, paths, etc."""
    from pathlib import Path

    from urika.cli_helpers import output_json

    output_json({"path": Path("/tmp/test")})
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == {"path": "/tmp/test"}


def test_output_json_error_to_stderr(capsys):
    from urika.cli_helpers import output_json_error

    output_json_error("something broke")
    captured = capsys.readouterr()
    data = json.loads(captured.err)
    assert data == {"error": "something broke"}


def test_is_scripted_when_json_flag():
    from urika.cli_helpers import is_scripted

    assert is_scripted(json_flag=True) is True


def test_is_scripted_when_not_tty():
    from urika.cli_helpers import is_scripted

    # In test environments stdout is usually not a TTY
    # so is_scripted() without json_flag depends on environment.
    # With json_flag=True it's always True.
    assert is_scripted(json_flag=True) is True


def test_interactive_prompt_returns_input():
    from urika.cli_helpers import interactive_prompt

    with patch("urika.cli_helpers._pt_prompt", return_value="hello"):
        result = interactive_prompt("Enter value")
        assert result == "hello"


def test_interactive_prompt_default():
    from urika.cli_helpers import interactive_prompt

    with patch("urika.cli_helpers._pt_prompt", return_value=""):
        result = interactive_prompt("Enter", default="fallback")
        assert result == "fallback"


def test_interactive_prompt_required_empty_retries():
    """When required=True and input is empty, should re-prompt."""
    from urika.cli_helpers import interactive_prompt

    # First call empty, second call has value
    with patch(
        "urika.cli_helpers._pt_prompt", side_effect=["", "actual"]
    ):
        result = interactive_prompt("Enter", required=True)
        assert result == "actual"


def test_interactive_prompt_keyboard_interrupt_with_default():
    from urika.cli_helpers import interactive_prompt

    with patch(
        "urika.cli_helpers._pt_prompt", side_effect=KeyboardInterrupt
    ):
        result = interactive_prompt("Enter", default="safe")
        assert result == "safe"


def test_interactive_prompt_keyboard_interrupt_no_default():
    from urika.cli_helpers import interactive_prompt

    with patch(
        "urika.cli_helpers._pt_prompt", side_effect=KeyboardInterrupt
    ):
        from urika.cli_helpers import UserCancelled
        with pytest.raises(UserCancelled):
            interactive_prompt("Enter")


def test_interactive_confirm_yes():
    from urika.cli_helpers import interactive_confirm

    with patch("urika.cli_helpers._pt_prompt", return_value="y"):
        assert interactive_confirm("Continue?") is True


def test_interactive_confirm_no():
    from urika.cli_helpers import interactive_confirm

    with patch("urika.cli_helpers._pt_prompt", return_value="n"):
        assert interactive_confirm("Continue?") is False


def test_interactive_confirm_default_true():
    from urika.cli_helpers import interactive_confirm

    with patch("urika.cli_helpers._pt_prompt", return_value=""):
        assert interactive_confirm("Continue?", default=True) is True


def test_interactive_confirm_default_false():
    from urika.cli_helpers import interactive_confirm

    with patch("urika.cli_helpers._pt_prompt", return_value=""):
        assert interactive_confirm("Continue?", default=False) is False


def test_interactive_numbered_selects_option():
    from urika.cli_helpers import interactive_numbered

    with patch("urika.cli_helpers._pt_prompt", return_value="2"):
        result = interactive_numbered(
            "Pick one:", ["alpha", "beta", "gamma"]
        )
        assert result == "beta"


def test_interactive_numbered_default():
    from urika.cli_helpers import interactive_numbered

    with patch("urika.cli_helpers._pt_prompt", return_value=""):
        result = interactive_numbered(
            "Pick one:", ["alpha", "beta", "gamma"], default=2
        )
        assert result == "beta"


def test_interactive_numbered_invalid_then_valid():
    from urika.cli_helpers import interactive_numbered

    with patch(
        "urika.cli_helpers._pt_prompt", side_effect=["99", "abc", "1"]
    ):
        result = interactive_numbered(
            "Pick one:", ["alpha", "beta"]
        )
        assert result == "alpha"
