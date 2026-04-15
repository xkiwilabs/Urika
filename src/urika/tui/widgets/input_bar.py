"""Input bar — minimum-viable diagnostic build.

This is a deliberate strip-down to isolate the "space key is eaten"
bug. Everything non-essential has been removed:

* No custom BINDINGS (no Tab completion)
* No custom Suggester (no ghost-text completion)
* No focus-management quirks
* No custom key handlers

It is just an ``Input`` subclass that:

1. Holds a reference to the session so the placeholder can show
   the project name.
2. Emits ``CommandSubmitted`` on Enter.
3. Logs every single value mutation via ``watch_value`` so we can
   see, in the Textual dev console, exactly what Textual thinks
   the widget's value is after every keystroke. If the logs show
   ``"hello "`` landing correctly but then getting clobbered to
   ``"hello"``, the bug is a mutation we can't see statically.
   If ``value`` never contains a space at all, the bug is upstream
   of the widget (focus stealing, key routing, driver).
"""

from __future__ import annotations

import datetime
from contextlib import suppress

from textual import on
from textual.message import Message
from textual.widgets import Input

from urika.repl.session import ReplSession


_LOG_PATH = "/tmp/urika-tui.log"


def _log(message: str) -> None:
    """Append a timestamped diagnostic line to /tmp/urika-tui.log.

    Single place so both watch_value and _on_key share one file
    handler. Errors are swallowed — we don't want a logging failure
    to break the TUI during a user test.
    """
    with suppress(OSError):
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")
            fh.write(f"{ts}  {message}\n")


class InputBar(Input):
    """Minimal Input subclass for the Urika TUI.

    Tab completion, suggester, custom key handling, and focus
    overrides are all intentionally absent while we chase down
    why space is being eaten in the real terminal. Once that is
    resolved they can be added back one at a time, with a
    regression test between each addition.
    """

    class CommandSubmitted(Message):
        """Fired when the user submits input with Enter."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, session: ReplSession, **kwargs: object) -> None:
        self.session = session
        prompt = self._build_prompt()
        super().__init__(
            placeholder=prompt,
            select_on_focus=False,
            **kwargs,
        )

    def _build_prompt(self) -> str:
        if self.session.has_project:
            return f"urika:{self.session.project_name}> "
        return "urika> "

    def on_mount(self) -> None:
        """Focus the input on mount so users can type immediately."""
        self.focus()

    def watch_value(self, value: str) -> None:
        """Diagnostic hook: log every value mutation to ``/tmp/urika-tui.log``."""
        _log(f"watch_value → {value!r}  len={len(value)}")

    async def _on_key(self, event: object) -> None:
        """Diagnostic hook: log every key event that reaches Input.

        We chain to ``super()._on_key(event)`` so the Input widget's
        native character-insert path still runs. If the log shows
        space keys arriving here but ``watch_value`` never reports a
        space in ``value``, the interception is inside Input itself.
        If the log NEVER shows a space arriving, the interception is
        upstream of the widget entirely (dispatch / focus / driver).
        """
        key = getattr(event, "key", None)
        character = getattr(event, "character", None)
        is_printable = getattr(event, "is_printable", None)
        _log(
            f"_on_key ← key={key!r}  char={character!r}  "
            f"printable={is_printable}"
        )
        await super()._on_key(event)  # type: ignore[misc]

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        """Handle Enter — emit CommandSubmitted, clear, stop the event."""
        text = event.value.strip()
        if text:
            self.post_message(self.CommandSubmitted(text))
        self.value = ""
        event.stop()

    def refresh_prompt(self) -> None:
        """Update the placeholder after a project change."""
        self.placeholder = self._build_prompt()
