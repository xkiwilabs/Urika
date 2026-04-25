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
    async def test_ansi_preserved_for_panel_styling(self) -> None:
        """ANSI escapes flow through to the panel so per-agent colours
        from cli_display.print_agent render in the TUI the same as in
        the CLI/REPL. The panel converts them to Rich Text via
        Text.from_ansi() — so the visible characters are the bare text,
        but the rendered Text object carries colour spans."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import OutputCapture

            with OutputCapture(app):
                # Bold red, reset.
                print("\x1b[1;31mred\x1b[0m word")
            await pilot.pause()

            text = _panel_text(panel)
            # The visible text contains both words with escape sequences
            # resolved into Rich style metadata. The styled "red" and
            # the unstyled " word" render as separate segments, so check
            # they're both present rather than matching a single span.
            # The bold-red colour shows up in the segment metadata.
            assert "red" in text
            assert "word" in text
            assert "bold=True" in text  # rich style applied
            assert "\x1b" not in text

    @pytest.mark.asyncio
    async def test_copy_buffer_strips_ansi(self) -> None:
        """The /copy ring buffer holds plain text — ANSI codes from the
        coloured CLI helpers must not land on the user's clipboard."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            from urika.tui.capture import OutputCapture

            with OutputCapture(app):
                print("\x1b[1;31mred\x1b[0m word")
            await pilot.pause()

            recorded = list(app.session.recent_output_lines)
            assert recorded, "expected a recorded output line"
            joined = "\n".join(recorded)
            assert "red word" in joined
            assert "\x1b" not in joined

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
