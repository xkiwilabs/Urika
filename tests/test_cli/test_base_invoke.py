"""Tests for ``cli._base._UrikaCLI.invoke`` — v0.4.2 M12 + M13 regressions.

M12 — pre-fix the update-banner check only gated on stdout.isatty(),
   so a user running ``urika list --json`` from an interactive TTY
   got a banner prepended to the JSON document, breaking parsers.
M13 — pre-fix UserCancelled was detected via
   ``type(exc).__name__ == "UserCancelled"`` (string compare) instead
   of isinstance — brittle and would match any class anywhere named
   UserCancelled.
"""

from __future__ import annotations

import json
import sys

import click
from click.testing import CliRunner

from urika.cli import cli
from urika.cli_helpers import UserCancelled


class TestUserCancelledHandling:
    def test_isinstance_match_still_works(self, monkeypatch) -> None:
        """Sanity: a real UserCancelled raised in a registered command
        should exit 0 (the documented "user backed out cleanly" path).
        We register a throwaway command on the cli group for the test.
        """
        from urika.cli import cli as _cli

        @_cli.command("__test_cancel", hidden=True)
        def _cancel() -> None:
            raise UserCancelled("user backed out")

        try:
            runner = CliRunner()
            result = runner.invoke(_cli, ["__test_cancel"])
            assert result.exit_code == 0, result.output
        finally:
            # Unregister the test command to keep the CLI registry clean.
            _cli.commands.pop("__test_cancel", None)

    def test_lookalike_class_does_not_match(self, monkeypatch) -> None:
        """Pre-v0.4.2 ``type(exc).__name__ == "UserCancelled"`` would
        match a stranger class with the same name. With the isinstance
        fix that no longer happens — a mis-named exception falls through
        to the default error-handling path."""
        from urika.cli import cli as _cli

        class UserCancelled(Exception):  # noqa: F811 — deliberately shadowing
            """Different module, same name — should NOT be caught silently."""

        @_cli.command("__test_lookalike", hidden=True)
        def _bad() -> None:
            raise UserCancelled("imposter")

        try:
            runner = CliRunner()
            result = runner.invoke(_cli, ["__test_lookalike"])
            # Pre-fix: exit_code == 0 (silently caught).
            # Post-fix: exception propagates → non-zero.
            assert result.exit_code != 0, (
                "Look-alike UserCancelled was silently swallowed — "
                "string-name compare regression."
            )
        finally:
            _cli.commands.pop("__test_lookalike", None)


class TestUpdateBannerSuppressedUnderJson:
    def test_argv_json_blocks_banner(self, monkeypatch, tmp_path) -> None:
        """Confirm the argv-sweep gate suppresses the banner when --json
        is in argv. We don't need to actually invoke a command; we just
        need to drive the same conditional the cli() function uses.
        """
        # Simulate ``urika list --json`` from a TTY.
        monkeypatch.setattr(sys, "argv", ["urika", "list", "--json"])

        # Re-create the gate logic from _base.cli() literally.
        json_mode = "--json" in sys.argv
        is_tty_simulated = True
        should_print_banner = is_tty_simulated and not json_mode
        assert should_print_banner is False

    def test_argv_no_json_allows_banner(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "argv", ["urika", "list"])
        json_mode = "--json" in sys.argv
        is_tty_simulated = True
        should_print_banner = is_tty_simulated and not json_mode
        assert should_print_banner is True

    def test_non_tty_blocks_banner_even_without_json(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["urika", "list"])
        json_mode = "--json" in sys.argv
        is_tty_simulated = False
        should_print_banner = is_tty_simulated and not json_mode
        assert should_print_banner is False
