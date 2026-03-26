"""Stdout/stderr capture that routes output to the TUI output panel."""

from __future__ import annotations

import asyncio
import re
import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from urika.tui.app import UrikaApp


_ANSI_RE = re.compile(r"\033\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


class _TuiWriter:
    """A file-like object that intercepts writes and posts them to the TUI."""

    def __init__(self, app: UrikaApp, original: object) -> None:
        self._app = app
        self._original = original
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, text: str | bytes) -> int:
        """Intercept write calls and route to the output panel."""
        if not text:
            return 0
        # click.echo may write bytes; decode to str.
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        with self._lock:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line:
                    self._post_line(line)
        return len(text)

    def _post_line(self, line: str) -> None:
        """Send a line to the output panel.

        When called from a thread that already has a running asyncio event
        loop (i.e. the Textual / test thread), we write to the panel directly.
        ``call_from_thread`` is only used when called from a background thread
        that does *not* own the event loop.
        """
        clean = _strip_ansi(line)
        try:
            # Detect whether we are already inside the event loop that owns
            # the Textual app.  If so, writing via call_from_thread would
            # deadlock or raise; instead we write directly.
            try:
                asyncio.get_running_loop()
                # We are on an async thread — write directly.
                self._write_to_panel(clean)
            except RuntimeError:
                # No running loop — we are on a background thread.
                self._app.call_from_thread(self._write_to_panel, clean)
        except Exception:
            # Last resort: dump to original stream so nothing is lost.
            try:
                self._original.write(line + "\n")  # type: ignore[union-attr]
                self._original.flush()  # type: ignore[union-attr]
            except Exception:
                pass

    def _write_to_panel(self, text: str) -> None:
        """Write to the output panel (called on the Textual thread)."""
        try:
            panel = self._app.query_one("OutputPanel")
            panel.write_line(text)
        except Exception:
            pass

    def flush(self) -> None:
        """Flush any remaining buffered content."""
        with self._lock:
            if self._buffer.strip():
                self._post_line(self._buffer)
                self._buffer = ""

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return "utf-8"

    def fileno(self) -> int:
        raise OSError("TUI writer has no file descriptor")


class OutputCapture:
    """Context manager that redirects stdout/stderr to the TUI output panel.

    Usage:
        capture = OutputCapture(app)
        with capture:
            print("goes to output panel")
            click.echo("also goes to output panel")
    """

    def __init__(self, app: UrikaApp) -> None:
        self._app = app
        self._old_stdout: object = None
        self._old_stderr: object = None

    def __enter__(self) -> OutputCapture:
        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr
        sys.stdout = _TuiWriter(self._app, self._old_stdout)  # type: ignore[assignment]
        sys.stderr = _TuiWriter(self._app, self._old_stderr)  # type: ignore[assignment]
        return self

    def __exit__(self, *args: object) -> None:
        if hasattr(sys.stdout, "flush"):
            sys.stdout.flush()
        if hasattr(sys.stderr, "flush"):
            sys.stderr.flush()
        sys.stdout = self._old_stdout  # type: ignore[assignment]
        sys.stderr = self._old_stderr  # type: ignore[assignment]
