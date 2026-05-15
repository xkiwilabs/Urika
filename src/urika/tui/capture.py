"""Stdout/stderr capture that routes output to the TUI output panel."""

from __future__ import annotations

import logging
import re
import sys
import asyncio
import threading
from typing import TYPE_CHECKING

from textual.css.query import NoMatches

if TYPE_CHECKING:
    from urika.tui.app import UrikaApp

log = logging.getLogger(__name__)

# Compiled once. Matches CSI escape sequences like \x1b[31m, \x1b[1;32m.
# Does NOT cover OSC (\x1b]...) or 8-bit CSI. Fine for agent output which
# only uses plain CSI color codes via click / our cli_display module.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# Safety cap: if a caller emits a progress-bar style stream with only \r
# separators, the buffer would grow unbounded. Force-flush beyond this.
_MAX_BUFFER_BYTES = 64 * 1024

# Detects click.prompt's default-value pattern: ``Some text [default_val]:``
# Only fires when a stdin reader is active (a command is waiting for input).
# Captures the default value inside the brackets.
_PROMPT_DEFAULT_RE = re.compile(r"\[([^\]]+)\]\s*:\s*$")


def _strip_ansi(text: str) -> str:
    """Remove ANSI CSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


class _TuiWriter:
    """A file-like object that intercepts writes and posts them to the TUI.

    Thread-safe: agent code may print from worker threads (Task 8 wires
    those up). Buffer manipulation happens under a lock, but cross-thread
    dispatch via ``App.call_from_thread`` is done OUTSIDE the lock to
    avoid serializing every print through the event loop under a single
    mutex (which would also risk deadlock if anything on the event loop
    ever needed to acquire something a worker thread holds).
    """

    def __init__(self, app: UrikaApp, original: object) -> None:
        self._app = app
        self._original = original
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, text: str | bytes | bytearray | memoryview) -> int:
        """Intercept write calls and route to the output panel.

        Accepts bytes-like types too because click.echo encodes to bytes
        when the stream is non-interactive (we return isatty=False).
        Decoded as utf-8 with replacement so a stray byte never crashes
        the writer.
        """
        if not text:
            return 0
        if isinstance(text, (bytes, bytearray, memoryview)):
            text = bytes(text).decode("utf-8", errors="replace")

        # Collect complete lines under the lock, then release before
        # emitting. `_post_line` calls App.call_from_thread which BLOCKS
        # waiting on the event loop; holding `self._lock` across that
        # call would serialize every print across all threads through
        # the event loop under a single mutex.
        lines_to_post: list[str] = []
        with self._lock:
            self._buffer += text

            # Normalize CRLF so Windows-style line endings don't leave
            # stray \r characters in the panel.
            if "\r\n" in self._buffer:
                self._buffer = self._buffer.replace("\r\n", "\n")

            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line:
                    lines_to_post.append(line)

            # Safety cap: unbounded buffer growth from \r-only streams
            # (progress bars). Force-emit what we have and reset.
            if len(self._buffer) > _MAX_BUFFER_BYTES:
                lines_to_post.append(self._buffer)
                self._buffer = ""

        for line in lines_to_post:
            self._post_line(line)
        return len(text)

    def _post_line(self, line: str) -> None:
        """Send a single line to the output panel.

        Must NOT be called while holding ``self._lock`` (see `write`).
        Three code paths, in order:

        1. Worker thread + app running → ``call_from_thread`` (cross-
           thread, documented-safe).
        2. Same thread as the Textual event loop + loop running →
           direct ``_write_to_panel`` call. Safe because we're already
           on the thread that owns the widget tree.
        3. App not running (shutdown / not yet started) → write to the
           original stdout so the line is not lost.
        """
        # The line is passed through with ANSI codes intact. The panel
        # converts them to Rich styling via Text.from_ansi() so the
        # per-agent colours from cli_display.print_agent (the
        # "──── Finalizer ────" headers) survive the trip and look the
        # same in the TUI as they do in the CLI / classic REPL.

        # Path 1: cross-thread dispatch. Raises RuntimeError if the
        # caller is on the same thread as the event loop, or if the
        # loop isn't running.
        try:
            self._app.call_from_thread(self._write_to_panel, line)
            return
        except RuntimeError:
            pass

        # Path 2: we might be on the app thread ourselves. We need
        # to know "is this thread the one Textual's event loop is
        # running on?". Textual exposes ``call_from_thread`` (Path 1
        # above) but no first-class "am I on the loop thread?" check;
        # we approximate by comparing against ``asyncio`` directly.
        #
        # ``asyncio.get_running_loop()`` raises ``RuntimeError`` when
        # there is no running loop in the current thread. If it
        # succeeds we know we're on _some_ loop; if that loop also
        # equals the one Textual is using, we're definitely safe.
        # Falls back to the private-attribute probe (``app._loop``,
        # ``app._thread_id``) only if asyncio's public API doesn't
        # answer the question — keeps the Textual upgrade surface
        # small. v0.4: prefer the public API; v0.3.x sites also
        # checked both regardless of whether asyncio answered.
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        textual_loop = getattr(self._app, "_loop", None)
        same_thread = current_loop is not None and current_loop is textual_loop
        if not same_thread:
            # Fallback to the legacy private-attribute path so behavior
            # is unchanged on Textual versions that don't expose the
            # loop the same way (e.g. when ``_loop`` lookup fails but
            # ``_thread_id`` happens to match).
            same_thread = getattr(self._app, "_thread_id", 0) == threading.get_ident()
        loop_running = textual_loop is not None and textual_loop.is_running()
        if same_thread and loop_running:
            self._write_to_panel(line)
            return

        # Path 3: fallback to the original stream.
        try:
            self._original.write(line + "\n")  # type: ignore[attr-defined]
            self._original.flush()  # type: ignore[attr-defined]
        except (OSError, ValueError) as exc:
            # OSError: underlying stream closed. ValueError: I/O on
            # closed file. Nothing more we can do — log and drop.
            log.warning("OutputCapture fallback write failed: %s", exc)

    def _prefill_input(self, default_value: str) -> None:
        """Pre-fill the InputBar with a detected default value.

        Called on the Textual thread via ``call_from_thread``. Sets
        the InputBar's value to the default so the user can press
        Enter to accept or modify it, without having to retype.
        """
        try:
            from urika.tui.widgets.input_bar import InputBar

            input_bar = self._app.query_one(InputBar)
            input_bar.value = default_value
            input_bar.cursor_position = len(default_value)
        except Exception:
            pass  # InputBar not mounted or query failed — skip

    def _write_to_panel(self, text: str) -> None:
        """Write to the output panel (called on the Textual thread).

        ``text`` may contain ANSI escape codes; the panel parses them
        via Text.from_ansi(). The /copy buffer stores the ANSI-stripped
        version so what lands on the user's clipboard is plain text.
        """
        try:
            panel = self._app.query_one("OutputPanel")
        except NoMatches:
            # OutputPanel not mounted (app composing or shutting down).
            # Drop silently — there's no panel to receive the line.
            return
        panel.write_line(text)
        # Buffer the line for the /copy slash command. Best-effort: if the
        # app doesn't expose a session (e.g. in tests), silently skip.
        session = getattr(self._app, "session", None)
        if session is not None and hasattr(session, "record_output_line"):
            session.record_output_line(_strip_ansi(text))

    def flush(self) -> None:
        """Flush any remaining buffered content.

        Called by context-manager exit and by explicit flush() calls
        (e.g. click.echo flushing between writes). Drains the whole
        remaining buffer — including whitespace-only content — so the
        semantics match `write()`, which also preserves whitespace
        (only fully-empty lines are skipped).
        """
        with self._lock:
            if not self._buffer:
                return
            remaining = self._buffer
            self._buffer = ""

        if remaining:
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

    Usage::

        capture = OutputCapture(app)
        with capture:
            print("goes to output panel")
            click.echo("also goes to output panel")

    Not reentrant. Nesting an ``OutputCapture`` inside an already-active
    ``OutputCapture`` raises ``RuntimeError``. The symptom of silent
    nesting would be ``__exit__`` restoring the outer ``_TuiWriter`` as
    the "original", which the caller would then see as sys.stdout even
    after they expected the real stream back. We'd rather fail loudly.
    """

    def __init__(self, app: UrikaApp) -> None:
        self._app = app
        self._old_stdout: object = None
        self._old_stderr: object = None

    def __enter__(self) -> OutputCapture:
        # Guard against nested capture. Tasks 7 and 8 both wrap handler
        # invocations; if a command handler somehow recurses into
        # another capture, the stack-of-writers would get tangled.
        if isinstance(sys.stdout, _TuiWriter) or isinstance(sys.stderr, _TuiWriter):
            raise RuntimeError(
                "OutputCapture is already active — nesting not supported. "
                "Ensure only one capture context is live at a time."
            )

        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr
        sys.stdout = _TuiWriter(self._app, self._old_stdout)  # type: ignore[assignment]
        sys.stderr = _TuiWriter(self._app, self._old_stderr)  # type: ignore[assignment]
        return self

    def __exit__(self, *args: object) -> None:
        # Drain any partial trailing content before restoring. Flush
        # the writers in place so their remaining buffer goes to the
        # panel, not lost on stream swap.
        if hasattr(sys.stdout, "flush"):
            sys.stdout.flush()
        if hasattr(sys.stderr, "flush"):
            sys.stderr.flush()
        sys.stdout = self._old_stdout  # type: ignore[assignment]
        sys.stderr = self._old_stderr  # type: ignore[assignment]
