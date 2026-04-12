"""Click group definition for Urika CLI."""

from __future__ import annotations

import click


class _UrikaCLI(click.Group):
    """Custom CLI group that catches UserCancelled globally."""

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except SystemExit:
            raise  # Let clean exits through
        except Exception as exc:
            # Catch UserCancelled from any command — exit cleanly
            if type(exc).__name__ == "UserCancelled":
                raise SystemExit(0)
            raise


@click.group(cls=_UrikaCLI, invoke_without_command=True)
@click.version_option(package_name="urika")
@click.pass_context
def cli(ctx) -> None:
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
        from urika.repl import run_repl

        run_repl()
