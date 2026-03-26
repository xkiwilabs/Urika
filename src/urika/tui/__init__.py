"""Textual TUI for Urika (Phase B)."""

from __future__ import annotations


def run_tui() -> None:
    """Launch the Textual TUI application."""
    from urika.tui.app import UrikaApp

    app = UrikaApp()
    app.run()
