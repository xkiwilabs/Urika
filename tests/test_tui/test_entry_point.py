"""Tests for the CLI entry point + TUI/REPL routing."""

from __future__ import annotations

import sys
from unittest.mock import patch

from click.testing import CliRunner


class TestEntryPoint:
    """Routing semantics of `urika` with no subcommand."""

    def test_run_tui_is_importable(self) -> None:
        from urika.tui import run_tui

        assert callable(run_tui)

    def test_default_launches_tui(self) -> None:
        """With no --classic flag and textual installed, `urika` (no
        subcommand) must call `urika.tui.run_tui`, not `run_repl`."""
        from urika.cli._base import cli

        runner = CliRunner()
        with (
            patch("urika.tui.run_tui") as mock_tui,
            patch("urika.repl.run_repl") as mock_repl,
        ):
            result = runner.invoke(cli, [])
            assert result.exit_code == 0, result.output
            mock_tui.assert_called_once()
            mock_repl.assert_not_called()

    def test_classic_flag_launches_repl(self) -> None:
        """`urika --classic` must bypass the TUI and call run_repl."""
        from urika.cli._base import cli

        runner = CliRunner()
        with (
            patch("urika.tui.run_tui") as mock_tui,
            patch("urika.repl.run_repl") as mock_repl,
        ):
            result = runner.invoke(cli, ["--classic"])
            assert result.exit_code == 0, result.output
            mock_tui.assert_not_called()
            mock_repl.assert_called_once()

    def test_tui_import_failure_falls_back_to_repl(self) -> None:
        """If `from urika.tui import run_tui` raises ImportError (e.g.
        the optional textual extra isn't installed), fall back to
        run_repl cleanly — no visible error.

        Setting ``sys.modules["urika.tui"] = None`` makes Python raise
        ImportError on subsequent ``from urika.tui import ...``
        statements, which simulates the dependency being missing
        without actually uninstalling it.
        """
        from urika.cli._base import cli

        runner = CliRunner()
        saved = sys.modules.get("urika.tui")
        sys.modules["urika.tui"] = None  # type: ignore[assignment]
        try:
            with patch("urika.repl.run_repl") as mock_repl:
                result = runner.invoke(cli, [])
                assert result.exit_code == 0, result.output
                mock_repl.assert_called_once()
        finally:
            if saved is not None:
                sys.modules["urika.tui"] = saved
            else:
                sys.modules.pop("urika.tui", None)
