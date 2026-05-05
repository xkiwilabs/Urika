"""Tests for ``cli_display._is_tty()`` — v0.4.2 M18 regression.

Pre-v0.4.2 ``_IS_TTY`` was evaluated at import time and frozen for
the lifetime of the process. Textual's TUI swaps ``sys.stdout`` *after*
import, and tests that capture+release stdout flip the TTY status —
the frozen flag turned spinners into permanent no-ops in those cases.

The fix exposes ``_is_tty()`` which re-checks at call time. The
``_IS_TTY`` module-level constant remains as a back-compat alias.
"""

from __future__ import annotations

import io
import sys

from urika.cli_display import _is_tty


class TestIsTtyReevaluates:
    def test_returns_bool(self) -> None:
        result = _is_tty()
        assert isinstance(result, bool)

    def test_reflects_current_stdout_state(self, monkeypatch) -> None:
        """Swap stdout for a non-TTY and confirm the function notices.
        Pre-v0.4.2 the frozen ``_IS_TTY`` would have returned its
        import-time value regardless of the swap.
        """
        non_tty = io.StringIO()
        monkeypatch.setattr(sys, "stdout", non_tty)
        assert _is_tty() is False

    def test_handles_stdout_without_isatty(self, monkeypatch) -> None:
        """Some custom redirects don't have ``isatty`` at all. The
        helper should return False rather than raising.
        """

        class NoIsAtty:
            def write(self, _: str) -> int:
                return 0

            def flush(self) -> None:
                pass

        monkeypatch.setattr(sys, "stdout", NoIsAtty())
        assert _is_tty() is False

    def test_handles_closed_stdout(self, monkeypatch) -> None:
        """A stdout that's been closed mid-call raises ValueError on
        isatty(). The helper swallows it and returns False so display
        code doesn't blow up during process teardown.
        """

        class ClosedStdout:
            def isatty(self) -> bool:
                raise ValueError("I/O operation on closed file.")

            def write(self, _: str) -> int:
                return 0

            def flush(self) -> None:
                pass

        monkeypatch.setattr(sys, "stdout", ClosedStdout())
        assert _is_tty() is False
