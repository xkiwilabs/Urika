"""Pause/stop controller and keyboard listener for graceful orchestrator interruption.

PauseController provides thread-safe pause/stop signalling that the orchestrator
can check between agent calls.  KeyListener runs a daemon thread that detects
ESC (0x1b) on stdin and requests a pause via the controller.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)


def read_and_clear_flag(project_dir: Path) -> str | None:
    """Read and remove ``<project_dir>/.urika/pause_requested``.

    Cross-process bridge: the dashboard (or any other out-of-process
    caller) writes the literal string ``"pause"`` or ``"stop"`` into the
    flag file; the orchestrator loop calls this helper at each turn
    boundary to learn about the request.

    Returns ``"pause"`` or ``"stop"`` when the file contains one of those
    values; returns ``None`` when the file is missing, unreadable, or
    contains anything else. The flag file is removed after a successful
    read so a subsequent turn (or a future experiment in the same
    project) doesn't re-trigger on stale state.
    """
    flag = project_dir / ".urika" / "pause_requested"
    if not flag.exists():
        return None
    try:
        content = flag.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    try:
        flag.unlink()
    except OSError:
        pass
    if content in ("pause", "stop"):
        return content
    return None


class PauseController:
    """Thread-safe pause/stop signalling for the orchestrator loop."""

    def __init__(self) -> None:
        self._pause_requested = threading.Event()
        self._stop_requested = threading.Event()

    def request_pause(self) -> None:
        """Signal the orchestrator to pause after the current agent finishes."""
        self._pause_requested.set()

    def request_stop(self) -> None:
        """Signal the orchestrator to stop the experiment entirely."""
        self._stop_requested.set()

    def is_pause_requested(self) -> bool:
        """Check whether a pause has been requested."""
        return self._pause_requested.is_set()

    def is_stop_requested(self) -> bool:
        """Check whether a stop has been requested."""
        return self._stop_requested.is_set()

    def reset(self) -> None:
        """Clear both pause and stop signals."""
        self._pause_requested.clear()
        self._stop_requested.clear()


class KeyListener:
    """Background daemon thread that listens for ESC to trigger a pause.

    On Unix/macOS, uses cbreak mode via termios so that individual key presses
    are detected without waiting for Enter.  On Windows, uses msvcrt for
    non-blocking key detection.  If stdin is not a TTY (piped input, CI), start()
    is a no-op.
    """

    _ESC = b"\x1b"

    def __init__(
        self,
        controller: PauseController,
        on_pause_requested: Callable[[], None] | None = None,
    ) -> None:
        self._controller = controller
        self._on_pause_requested = on_pause_requested
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._original_termios: list | None = None

    def start(self) -> None:
        """Start the key-listener daemon thread.

        No-op when stdin is not a TTY (e.g. piped input or CI).
        """
        if not sys.stdin.isatty():
            logger.debug("stdin is not a TTY — KeyListener disabled")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._listen,
            name="urika-key-listener",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the listener thread to exit and restore terminal settings."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._restore_terminal()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _listen(self) -> None:
        """Main loop — runs in a daemon thread."""
        if sys.platform == "win32":
            self._listen_windows()
        else:
            self._listen_unix()

    def _listen_unix(self) -> None:
        """Listen for ESC on Unix/macOS using cbreak mode."""
        try:
            import termios
            import tty
        except ImportError:
            logger.debug("termios not available — KeyListener disabled")
            return

        fd = sys.stdin.fileno()
        try:
            self._original_termios = termios.tcgetattr(fd)
        except termios.error:
            logger.debug("Cannot get terminal attributes — KeyListener disabled")
            return

        try:
            tty.setcbreak(fd)
            while not self._stop_event.is_set():
                # Use select for a short timeout so we can check _stop_event
                import select

                ready, _, _ = select.select([sys.stdin], [], [], 0.2)
                if ready:
                    ch = sys.stdin.buffer.read(1)
                    if ch == self._ESC:
                        self._handle_esc()
        except OSError:
            logger.debug("stdin read error — KeyListener stopping")
        finally:
            self._restore_terminal()

    def _listen_windows(self) -> None:
        """Listen for ESC on Windows using msvcrt."""
        try:
            import msvcrt
        except ImportError:
            logger.debug("msvcrt not available — KeyListener disabled")
            return

        while not self._stop_event.is_set():
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch == self._ESC:
                    self._handle_esc()
            else:
                self._stop_event.wait(timeout=0.2)

    def _handle_esc(self) -> None:
        """Handle an ESC keypress."""
        self._controller.request_pause()
        if self._on_pause_requested is not None:
            self._on_pause_requested()
        logger.info("Pause requested via ESC key")

    def _restore_terminal(self) -> None:
        """Restore original terminal settings (Unix only)."""
        if self._original_termios is not None:
            try:
                import termios

                termios.tcsetattr(
                    sys.stdin.fileno(),
                    termios.TCSADRAIN,
                    self._original_termios,
                )
            except (ImportError, OSError, termios.error):
                pass
            self._original_termios = None
