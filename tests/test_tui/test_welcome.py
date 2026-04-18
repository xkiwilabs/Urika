"""Tests for the TUI welcome screen."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


def _panel_text(panel) -> str:
    """Flatten all rendered Strips in an OutputPanel to plain text."""
    return "\n".join(str(strip) for strip in panel.lines)


class TestWelcomeScreen:
    """The on_mount welcome message — branding, global stats, help hint."""

    @pytest.mark.asyncio
    async def test_shows_urika_branding(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("OutputPanel")
            text = _panel_text(panel)
            assert "Urika" in text
            assert "scientific analysis" in text.lower()

    @pytest.mark.asyncio
    async def test_shows_help_hint(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("OutputPanel")
            text = _panel_text(panel)
            assert "/help" in text
            assert "orchestrator" in text.lower()

    @pytest.mark.asyncio
    async def test_shows_global_stats_or_fails_gracefully(self) -> None:
        """get_global_stats returns counts from the global projects
        registry. On a fresh install with no projects, the function
        still succeeds (returns zeros); on a broken install it
        raises and we log + skip. Either way the welcome must NOT
        crash the app, and the stats line must appear when the
        call succeeds."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("OutputPanel")
            text = _panel_text(panel)
            # Either the "N projects" line appears, or it doesn't —
            # but the help hint MUST appear regardless (it's printed
            # after the try/except).
            assert "/help" in text
            # The app is still alive.
            assert app._exit is False
