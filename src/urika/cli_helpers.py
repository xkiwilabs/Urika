"""Shared CLI helpers — JSON output, interactive prompts, pipe detection."""

from __future__ import annotations

import json
import sys
from typing import Any

import click


def output_json(data: Any) -> None:
    """Write structured JSON to stdout with indent=2."""
    click.echo(json.dumps(data, indent=2, default=str))


def output_json_error(message: str) -> None:
    """Write a JSON error to stderr."""
    sys.stderr.write(json.dumps({"error": message}) + "\n")


def is_scripted(*, json_flag: bool = False) -> bool:
    """Check if running in scripted/piped mode.

    Returns True when output should be machine-readable:
    - ``--json`` flag is set
    - stdout is not a TTY (piped)
    """
    if json_flag:
        return True
    return not sys.stdout.isatty()


# --- prompt_toolkit interactive prompts ---


def _pt_prompt(message: str, **kwargs: Any) -> str:
    """Thin wrapper around prompt_toolkit's prompt() for mocking.

    Falls back to built-in input() when stdin is not a TTY
    (e.g. inside Click's CliRunner during tests, or piped input).
    """
    if not sys.stdin.isatty():
        # prompt_toolkit doesn't work with non-TTY stdin
        return input(message)

    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.history import InMemoryHistory

    # Shared history across prompts in a session
    if not hasattr(_pt_prompt, "_history"):
        _pt_prompt._history = InMemoryHistory()

    return pt_prompt(
        message,
        history=_pt_prompt._history,
        **kwargs,
    )


def interactive_prompt(
    message: str,
    *,
    default: str = "",
    required: bool = False,
) -> str:
    """Prompt for text input using prompt_toolkit.

    Supports arrow keys, history, multi-line paste.
    Falls back to *default* on empty input.
    Raises ``click.Abort`` on Ctrl+C/EOF only when *required* and no default.
    """
    suffix = f" [{default}]" if default else ""
    display = f"  {message}{suffix}: "

    try:
        result = _pt_prompt(display).strip()
        if not result and default:
            return default
        if not result and required:
            click.echo("  Value required.")
            return interactive_prompt(message, default=default, required=required)
        return result
    except EOFError:
        # EOF (piped stdin / CliRunner) — return default silently
        return default
    except KeyboardInterrupt:
        if default:
            return default
        raise UserCancelled()


def interactive_confirm(
    message: str,
    *,
    default: bool = True,
) -> bool:
    """Yes/no confirmation using prompt_toolkit."""
    hint = "Y/n" if default else "y/N"
    display = f"  {message} [{hint}]: "

    try:
        result = _pt_prompt(display).strip().lower()
        if not result:
            return default
        return result in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return default


class UserCancelled(Exception):
    """Raised when user cancels an interactive prompt."""

    pass


def interactive_numbered(
    prompt_text: str,
    options: list[str],
    *,
    default: int = 1,
    allow_cancel: bool = True,
) -> str:
    """Prompt with numbered options using prompt_toolkit.

    Returns the selected option text.
    Raises UserCancelled on Ctrl+C, ESC, or if user picks Cancel.
    """
    display_options = list(options)
    if allow_cancel:
        display_options.append("Cancel")

    click.echo(prompt_text)
    for i, opt in enumerate(display_options, 1):
        marker = " (default)" if i == default else ""
        click.echo(f"    {i}. {opt}{marker}")

    while True:
        try:
            raw = _pt_prompt(f"  Choice [{default}]: ").strip()
        except EOFError:
            return options[default - 1]
        except KeyboardInterrupt:
            raise UserCancelled()
        if not raw:
            return options[default - 1]
        try:
            idx = int(raw)
            if allow_cancel and idx == len(display_options):
                raise UserCancelled()
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass
        click.echo(f"  Enter a number between 1 and {len(display_options)}.")
