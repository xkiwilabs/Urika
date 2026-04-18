"""Background agent execution via Textual Workers.

Blocking slash-command handlers run on a Textual thread-based Worker
so the TUI stays responsive. The worker installs:

1. ``OutputCapture`` — routes ``print()`` / ``click.echo()`` to the
   OutputPanel.
2. ``_TuiStdinReader`` — replaces ``sys.stdin`` so that ``input()``
   and ``click.prompt()`` read from a queue fed by the InputBar.
   When the user types while a worker is active, the text goes to
   the queue instead of the normal dispatch path, unblocking the
   thread.
"""

from __future__ import annotations

import sys
import queue
import threading
from typing import TYPE_CHECKING, Callable

from textual.worker import Worker

if TYPE_CHECKING:
    from urika.repl.session import ReplSession
    from urika.tui.app import UrikaApp


CommandHandler = Callable[["ReplSession", str], None]


class _TuiStdinReader:
    """A file-like object that replaces ``sys.stdin`` in worker threads.

    When a command handler calls ``input()`` or ``click.prompt()``,
    the call chains to ``sys.stdin.readline()``. This reader blocks
    on a ``threading.Queue`` until the InputBar feeds a line into it.

    The prompt text (``"Choice: "`` etc.) reaches the OutputPanel
    via ``OutputCapture``'s stdout redirection, so the user sees the
    question and can type their answer in the InputBar.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self.encoding = "utf-8"

    def readline(self, limit: int = -1) -> str:
        """Block until the InputBar sends a line."""
        return self._queue.get()

    def read(self, size: int = -1) -> str:
        return self.readline()

    def feed(self, line: str) -> None:
        """Called by the InputBar when the user submits text while
        a worker is waiting for input."""
        self._queue.put(line + "\n")

    def isatty(self) -> bool:
        return True  # click needs this to show prompts

    def fileno(self) -> int:
        raise OSError("TUI stdin reader has no file descriptor")

    @property
    def closed(self) -> bool:
        return False

    def close(self) -> None:
        # Unblock any waiting readline by feeding an empty line.
        self._queue.put("\n")


# Module-level reference so the InputBar can feed it.
_active_stdin_reader: _TuiStdinReader | None = None


def get_active_stdin_reader() -> _TuiStdinReader | None:
    """Return the currently active stdin reader, or None if no worker
    is waiting for input."""
    return _active_stdin_reader


def run_command_in_worker(
    app: UrikaApp,
    handler: CommandHandler,
    args: str,
    cmd_name: str,
) -> Worker:
    """Run a sync command handler in a background Textual Worker.

    The worker:

    1. Sets ``session.agent_running = True``.
    2. Installs ``OutputCapture`` (stdout/stderr → OutputPanel).
    3. Installs ``_TuiStdinReader`` (stdin ← InputBar queue).
    4. Invokes ``handler(session, args)``.
    5. On completion — success or failure — clears the agent flag,
       restores stdin, and refreshes the InputBar.
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
                except Exception as exc:
                    print_error(f"Error: {exc}")
        finally:
            sys.stdin = old_stdin  # type: ignore[assignment]
            _active_stdin_reader = None
            app.session.set_agent_idle()
            try:
                app.call_from_thread(_post_command_refresh)
            except RuntimeError:
                pass

    return app.run_worker(_work, thread=True, name=f"agent:{cmd_name}")
