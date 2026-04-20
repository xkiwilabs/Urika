"""Background agent execution via Textual Workers.

Two execution modes for slash commands:

1. **Worker mode** — for long-running agent commands (``/run``,
   ``/finalize``, etc.) that invoke Claude agents. Output captured
   to the OutputPanel. Interactive stdin is bridged so
   ``click.prompt`` / ``input()`` read from the InputBar.

2. **Suspend mode** — fallback for commands that absolutely need raw
   terminal access beyond what the stdin bridge provides.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
from typing import TYPE_CHECKING, Callable

from textual.worker import Worker

if TYPE_CHECKING:
    from urika.repl.session import ReplSession
    from urika.tui.app import UrikaApp


CommandHandler = Callable[["ReplSession", str], None]


class _TuiStdinReader:
    """A file-like stdin replacement for worker threads.

    When a command handler calls ``input()`` or ``click.prompt()``,
    the call chains to ``sys.stdin.readline()``. This reader blocks
    on a queue until the InputBar feeds a line into it.

    Uses an OS pipe for ``fileno()`` so that click's terminal
    detection (which calls ``os.isatty(stdin.fileno())``) gets a
    real fd instead of crashing. We write fed text to BOTH the
    queue (for our readline) AND the pipe (for any code that reads
    from the raw fd). The pipe is separate from the terminal fd so
    there's no conflict with Textual's driver.
    """

    # Marker so prompt helpers (e.g. _pt_prompt in cli_helpers.py) can
    # detect they're running inside the TUI worker and fall back to
    # input() instead of prompt_toolkit.prompt() — prompt_toolkit
    # fights with Textual over terminal control and hangs/crashes.
    _tui_bridge = True

    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._pipe_r, self._pipe_w = os.pipe()
        self.encoding = "utf-8"
        self._cancelled = False

    def readline(self, limit: int = -1) -> str:
        """Block until the InputBar sends a line."""
        line = self._queue.get()
        if self._cancelled:
            raise EOFError("cancelled")
        return line

    def read(self, size: int = -1) -> str:
        return self.readline()

    def feed(self, line: str) -> None:
        """Called by the InputBar when the user submits text while
        a worker is waiting for input."""
        text = line + "\n"
        self._queue.put(text)
        # Also write to the pipe fd for any code that reads via
        # os.read(fileno()) instead of our readline().
        try:
            os.write(self._pipe_w, text.encode("utf-8"))
        except OSError:
            pass

    def isatty(self) -> bool:
        # click needs this to show prompts instead of falling back
        # to non-interactive mode.
        return True

    def fileno(self) -> int:
        # Return the pipe's reader end — a real fd that satisfies
        # os.isatty() checks (returns False for a pipe, but that's
        # OK because our isatty() method returns True and click
        # uses stream.isatty() not os.isatty(fileno())).
        return self._pipe_r

    @property
    def closed(self) -> bool:
        return False

    def cancel(self) -> None:
        """Signal cancellation — unblocks readline with an EOFError."""
        self._cancelled = True
        self._queue.put("\n")  # unblock the waiting get()

    def close(self) -> None:
        """Unblock any waiting readline and close the pipe."""
        self._queue.put("\n")
        try:
            os.close(self._pipe_w)
        except OSError:
            pass
        try:
            os.close(self._pipe_r)
        except OSError:
            pass

    def flush(self) -> None:
        pass

    def writable(self) -> bool:
        return False

    def readable(self) -> bool:
        return True


# Module-level reference so the InputBar can feed it.
_active_stdin_reader: _TuiStdinReader | None = None


def get_active_stdin_reader() -> _TuiStdinReader | None:
    """Return the currently active stdin reader, or None."""
    return _active_stdin_reader


def run_command_in_worker(
    app: UrikaApp,
    handler: CommandHandler,
    args: str,
    cmd_name: str,
) -> Worker:
    """Run a command handler in a background Textual Worker.

    Installs OutputCapture (stdout → panel) and _TuiStdinReader
    (stdin ← InputBar queue) so the handler can use print(),
    click.echo(), click.prompt(), and input() unchanged.
    """
    from urika.cli_display import print_error
    from urika.tui.capture import OutputCapture
    from urika.tui.widgets.input_bar import InputBar

    def _post_command_refresh() -> None:
        from textual.css.query import NoMatches

        try:
            input_bar = app.query_one(InputBar)
        except NoMatches:
            return
        input_bar.refresh_prompt()

    def _work() -> None:
        global _active_stdin_reader

        stdin_reader = _TuiStdinReader()
        old_stdin = sys.stdin
        sys.stdin = stdin_reader  # type: ignore[assignment]
        _active_stdin_reader = stdin_reader

        app.session.set_agent_running(agent_name=cmd_name)
        try:
            with OutputCapture(app):
                try:
                    handler(app.session, args)
                except SystemExit:
                    app.session.save_usage()
                    app.call_from_thread(app.exit)
                except EOFError:
                    # Raised by _TuiStdinReader when cancelled via /stop
                    # or Ctrl+C — exit silently, cleanup in finally.
                    pass
                except Exception as exc:
                    print_error(f"Error: {exc}")
        finally:
            sys.stdin = old_stdin  # type: ignore[assignment]
            _active_stdin_reader = None
            stdin_reader.close()
            app.session.set_agent_idle()
            try:
                app.call_from_thread(_post_command_refresh)
            except RuntimeError:
                pass

    return app.run_worker(_work, thread=True, name=f"agent:{cmd_name}")
