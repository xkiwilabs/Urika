"""Tests for the status bar widget."""

from __future__ import annotations

import re

import pytest

from urika.repl.session import ReplSession
from urika.tui.app import UrikaApp


class TestStatusBar:
    """Test the 2-line status bar."""

    @pytest.mark.asyncio
    async def test_shows_urika_label(self) -> None:
        app = UrikaApp()
        async with app.run_test():
            bar = app.query_one("StatusBar")
            text = bar.render_line1()
            assert "urika" in text.lower()

    @pytest.mark.asyncio
    async def test_shows_project_name(self, tmp_path) -> None:
        session = ReplSession()
        session.load_project(path=tmp_path, name="my-study")
        app = UrikaApp(session=session)
        async with app.run_test():
            bar = app.query_one("StatusBar")
            text = bar.render_line1()
            assert "my-study" in text

    @pytest.mark.asyncio
    async def test_shows_elapsed_time(self) -> None:
        app = UrikaApp()
        async with app.run_test():
            bar = app.query_one("StatusBar")
            text = bar.render_line2()
            # _format_duration produces one of: "Nms", "N.Ns", "Nm Ns" — assert
            # the actual format pattern rather than substring-matching "s"/"ms"
            # which matches letters in words like "urika"/"tokens".
            assert re.search(r"\b\d+(ms|\.\d+s|m \d+s|s)\b", text), (
                f"elapsed-time format not found in line 2: {text!r}"
            )
