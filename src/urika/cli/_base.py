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

    # Check for updates on every CLI invocation (cached, non-blocking)
    try:
        from urika.core.updates import (
            check_for_updates,
            format_update_message,
        )

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
