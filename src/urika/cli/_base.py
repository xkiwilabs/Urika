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
        # Try TUI first, fall back to REPL
        from urika.cli.tui import _find_tui_binary

        import shutil
        import subprocess
        import sys
        from pathlib import Path

        binary = _find_tui_binary()
        if binary:
            subprocess.run([binary])
            raise SystemExit(0)

        # Try bun dev mode (new packages location first, then legacy)
        repo_root = Path(__file__).parent.parent.parent.parent
        bun = shutil.which("bun")
        dev_ts = repo_root / "packages" / "urika-tui" / "src" / "index.ts"
        dev_cwd = repo_root / "packages" / "urika-tui"
        if not dev_ts.exists():
            dev_ts = repo_root / "tui" / "src" / "index.ts"
            dev_cwd = repo_root / "tui"
        if dev_ts.exists() and bun:
            subprocess.run([bun, "run", str(dev_ts)], cwd=str(dev_cwd))
            raise SystemExit(0)

        # Fall back to REPL
        from urika.repl import run_repl

        run_repl()
