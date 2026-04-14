"""Stdout/stderr capture that routes output to the TUI output panel."""

from __future__ import annotations

import logging
import re
import sys
import threading
from typing import TYPE_CHECKING

from textual.css.query import NoMatches

if TYPE_CHECKING:
    from urika.tui.app import UrikaApp

log = logging.getLogger(__name__)

# Compiled once: matches CSI escape sequences like \x1b[31m, \x1b[1;32m, etc.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


class _TuiWriter:
    """A file-like object that intercepts writes and posts them to the TUI.

    Thread-safe: agent code may print from worker threads (Task 8 wires
    those up). Buffer manipulation happens under a lock; line emission
    happens via App.call_from_thread so the panel is only touched on the
    Textual event-loop thread.
    """

    def __init__(self, app: UrikaApp, original: object) -> None:
        self._app = app
        self._original = original
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, text: str | bytes) -> int:
        """Intercept write calls and route to the output panel.

        Accepts bytes too because click.echo encodes to bytes when it
        decides the stream is non-interactive. We decode as utf-8 with
        replacement so a stray byte never crashes the writer.
        """
        if not text:
            return 0
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

        Tries call_from_thread first (the correct path when invoked from
        a worker thread). If we are already on the Textual thread, that
        raises RuntimeError — fall through to a direct panel write. If
        the app isn't running at all (also RuntimeError), fall back to
        the original stdout so output is not lost.
        """
        clean = _strip_ansi(line)
        try:
            self._app.call_from_thread(self._write_to_panel, clean)
            return
        except RuntimeError:
            # Two known causes:
            #   1. Called from the same thread as the app's event loop
            #      (no worker thread in play) — we can write directly.
            #   2. The app isn't running (shutdown / not yet started)
            #      — fall through to the original-stdout fallback.
            pass

        # Same-thread path: try a direct panel write. This is safe because
        # we're already on the Textual thread.
        if (
            self._app._thread_id == threading.get_ident()
            and self._app._loop is not None
        ):
            self._write_to_panel(clean)
            return

        # App not running — preserve output by writing to the real stdout.
        try:
            self._original.write(line + "\n")  # type: ignore[attr-defined]
            self._original.flush()  # type: ignore[attr-defined]
        except (OSError, ValueError) as exc:
            # OSError: underlying stream closed. ValueError: I/O on closed
            # file. Nothing more we can do — log and drop the line.
            log.warning("OutputCapture fallback write failed: %s", exc)

    def _write_to_panel(self, text: str) -> None:
        """Write to the output panel (called on the Textual thread)."""
        try:
            panel = self._app.query_one("OutputPanel")
        except NoMatches:
            # OutputPanel not mounted (app composing or shutting down).
            # Drop silently — there's no panel to receive the line.
            return
        panel.write_line(text)

    def flush(self) -> None:
        """Flush any remaining buffered content."""
        with self._lock:
            if self._buffer:
                remaining = self._buffer
                self._buffer = ""
                # Emit any partial trailing line so nothing is lost on exit.
                if remaining.strip():
                    self._post_line(remaining)

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
        # Drain any partial trailing content before restoring.
        if hasattr(sys.stdout, "flush"):
            sys.stdout.flush()
        if hasattr(sys.stderr, "flush"):
            sys.stderr.flush()
        sys.stdout = self._old_stdout  # type: ignore[assignment]
        sys.stderr = self._old_stderr  # type: ignore[assignment]
