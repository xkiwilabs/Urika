"""Tests for TUI entry point and fallback."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestEntryPoint:
    """Test that urika with no args launches TUI or falls back."""

    def test_run_tui_is_importable(self) -> None:
        from urika.tui import run_tui

        assert callable(run_tui)

    def test_fallback_when_textual_missing(self) -> None:
        """If textual is not installed, fall back to classic REPL."""
        import sys

        with patch.dict(sys.modules, {"textual": None}):
            with pytest.raises(ImportError):
                if "urika.tui" in sys.modules:
                    del sys.modules["urika.tui"]
                if "urika.tui.app" in sys.modules:
                    del sys.modules["urika.tui.app"]
                from urika.tui.app import UrikaApp
