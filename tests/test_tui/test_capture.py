"""Tests for stdout capture and redirection."""

from __future__ import annotations

import sys
import threading

import pytest

from urika.tui.app import UrikaApp


def _panel_text(panel) -> str:
    """Flatten all rendered Strips in an OutputPanel to plain text."""
    return "\n".join(str(strip) for strip in panel.lines)


class TestStdoutCapture:
    """OutputCapture + _TuiWriter behavior end-to-end."""

    @pytest.mark.asyncio
    async def test_print_captured(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import OutputCapture

            with OutputCapture(app):
                print("test line from print")
            await pilot.pause()

            assert "test line from print" in _panel_text(panel)

    @pytest.mark.asyncio
    async def test_click_echo_captured(self) -> None:
        import click

        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import OutputCapture

            with OutputCapture(app):
                click.echo("test from click.echo")
            await pilot.pause()

            assert "test from click.echo" in _panel_text(panel)

    @pytest.mark.asyncio
    async def test_stdout_restored_after_context(self) -> None:
        app = UrikaApp()
        async with app.run_test():
            original = sys.stdout
            from urika.tui.capture import OutputCapture

            with OutputCapture(app):
                pass
            assert sys.stdout is original

    @pytest.mark.asyncio
    async def test_bytes_input_decoded(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import _TuiWriter

            writer = _TuiWriter(app, sys.stdout)
            # click.echo uses the non-tty bytes path — mimic it directly.
            writer.write(b"bytes line\n")
            await pilot.pause()

            assert "bytes line" in _panel_text(panel)

    @pytest.mark.asyncio
    async def test_bytearray_and_memoryview_accepted(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import _TuiWriter

            writer = _TuiWriter(app, sys.stdout)
            writer.write(bytearray(b"bytearray line\n"))
            writer.write(memoryview(b"memoryview line\n"))
            await pilot.pause()

            text = _panel_text(panel)
            assert "bytearray line" in text
            assert "memoryview line" in text

    @pytest.mark.asyncio
    async def test_ansi_stripped(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import OutputCapture

            with OutputCapture(app):
                # Bold red, reset — should appear as plain text.
                print("\x1b[1;31mred\x1b[0m word")
            await pilot.pause()

            text = _panel_text(panel)
            assert "red word" in text
            # ESC should not survive through to the panel.
            assert "\x1b" not in text

    @pytest.mark.asyncio
    async def test_worker_thread_write(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import _TuiWriter

            writer = _TuiWriter(app, sys.stdout)

            def worker() -> None:
                # Must go through call_from_thread, not the same-thread
                # direct-write path. Runs on a non-event-loop thread.
                writer.write("worker line\n")

            t = threading.Thread(target=worker)
            t.start()
            t.join(timeout=2.0)
            await pilot.pause()

            assert "worker line" in _panel_text(panel)

    @pytest.mark.asyncio
    async def test_nested_capture_raises(self) -> None:
        app = UrikaApp()
        async with app.run_test():
            from urika.tui.capture import OutputCapture

            with OutputCapture(app):
                # Nesting a second capture must fail loudly, not silently
                # tangle the sys.stdout stack.
                with pytest.raises(RuntimeError, match="already active"):
                    with OutputCapture(app):
                        pass

    @pytest.mark.asyncio
    async def test_partial_trailing_line_flushed(self) -> None:
        """A write without a trailing newline must still reach the panel
        on context-manager exit, matching write()'s whitespace-preserving
        semantics."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import OutputCapture

            with OutputCapture(app):
                print("partial line", end="")
            await pilot.pause()

            assert "partial line" in _panel_text(panel)
