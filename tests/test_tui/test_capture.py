"""Tests for stdout capture and redirection."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


class TestStdoutCapture:
    """Test that print/click.echo output is captured to the output panel."""

    @pytest.mark.asyncio
    async def test_print_captured(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import OutputCapture

            capture = OutputCapture(app)
            with capture:
                print("test line from print")
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_click_echo_captured(self) -> None:
        import click

        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import OutputCapture

            capture = OutputCapture(app)
            with capture:
                click.echo("test from click.echo")
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_stdout_restored_after_context(self) -> None:
        import sys

        app = UrikaApp()
        async with app.run_test() as _pilot:
            original = sys.stdout
            from urika.tui.capture import OutputCapture

            capture = OutputCapture(app)
            with capture:
                pass
            assert sys.stdout is original
