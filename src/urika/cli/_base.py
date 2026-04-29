"""Click group definition for Urika CLI."""

from __future__ import annotations

import click


class _UrikaCLI(click.Group):
    """Custom CLI group that catches UserCancelled + UrikaError globally.

    UrikaError subclasses (ConfigError, AgentError, ValidationError) are
    rendered as a message line plus an optional hint line, then exit 2.
    No traceback for these — they are user-facing by definition. Anything
    else falls through to Click's default handling.
    """

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except SystemExit:
            raise  # Let clean exits through
        except Exception as exc:
            # Catch UserCancelled from any command — exit cleanly
            if type(exc).__name__ == "UserCancelled":
                raise SystemExit(0)
            # UrikaError — render message + hint without traceback
            from urika.core.errors import UrikaError

            if isinstance(exc, UrikaError):
                from urika.cli_display import print_error

                print_error(str(exc))
                if exc.hint:
                    click.echo(f"  hint: {exc.hint}", err=True)
                raise SystemExit(2)
            raise


@click.group(cls=_UrikaCLI, invoke_without_command=True)
@click.option(
    "--classic",
    is_flag=True,
    hidden=True,
    help="Use classic prompt_toolkit REPL instead of the Textual TUI.",
)
@click.version_option(package_name="urika")
@click.pass_context
def cli(ctx, classic: bool) -> None:
    """Urika: Agentic scientific analysis platform."""
    # Load credentials from ~/.urika/secrets.env
    from urika.core.secrets import load_secrets

    load_secrets()

    # One-time compliance reminder: Anthropic Consumer Terms §3.7 + the
    # April 2026 Agent SDK clarification prohibit using a Pro/Max
    # subscription to authenticate the Claude Agent SDK that Urika
    # depends on. We don't block — users may be running in private mode
    # only or have already acknowledged the requirement — but we surface
    # the missing key on every invocation until ack'd.
    import os as _os

    if not _os.environ.get("ANTHROPIC_API_KEY") and not _os.environ.get(
        "URIKA_ACK_API_KEY_REQUIRED"
    ):
        import sys as _sys

        _sys.stderr.write(
            "\n"
            "  \033[33m⚠ ANTHROPIC_API_KEY not set\033[0m\n"
            "\n"
            "  Urika requires an Anthropic API key. Per Anthropic's Consumer\n"
            "  Terms (§3.7) and the April 2026 Agent SDK clarification, a\n"
            "  Claude Pro/Max subscription cannot be used to authenticate the\n"
            "  Claude Agent SDK that Urika depends on.\n"
            "\n"
            "  Get a key:  https://console.anthropic.com (Settings → API Keys)\n"
            "  Save it:    urika config api-key   (interactive)\n"
            "              # or: export ANTHROPIC_API_KEY=sk-ant-...\n"
            "\n"
            "  To silence this warning permanently after acknowledging:\n"
            "    export URIKA_ACK_API_KEY_REQUIRED=1\n"
            "\n"
        )

    # Check for updates on every CLI invocation (cached, non-blocking).
    # Skip when stdout isn't a TTY \u2014 this catches CI runs, the test
    # suite, and any consumer piping `urika ... --json` output. The
    # banner would otherwise corrupt JSON output and clutter logs.
    try:
        import sys as _sys
        from urika.core.updates import (
            check_for_updates,
            format_update_message,
        )

        if _sys.stdout.isatty():
            update_info = check_for_updates()
            if update_info:
                from urika.cli_display import _C

                msg = format_update_message(update_info)
                click.echo(f"{_C.DIM}  \u2191 {msg}{_C.RESET}")
    except Exception:
        pass

    if ctx.invoked_subcommand is None:
        # Default path: launch the Textual TUI. Falls back to the
        # classic prompt_toolkit REPL if Textual isn't installed
        # (the [tui] extra is optional) or if the user passed
        # --classic explicitly.
        if classic:
            from urika.repl import run_repl

            run_repl()
            return
        try:
            from urika.tui import run_tui
        except ImportError:
            from urika.repl import run_repl

            run_repl()
            return
        run_tui()
