"""``urika completion`` group — shell completion install / script.

Click 8 has built-in completion generation. This module wraps it as a
small CLI group so users don't have to remember the
``_URIKA_COMPLETE=<shell>_source urika`` env-var dance:

    urika completion install [bash|zsh|fish]   # writes the script + prints source line
    urika completion script  [bash|zsh|fish]   # prints the script to stdout
    urika completion uninstall                 # removes the installed script

Completion files live at ``~/.urika/completions/urika.<shell>``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from urika.cli._base import cli


_SUPPORTED_SHELLS = ("bash", "zsh", "fish")


def _detect_shell() -> str | None:
    """Best-effort guess of the user's shell from $SHELL."""
    sh = os.environ.get("SHELL", "")
    base = Path(sh).name
    if base in _SUPPORTED_SHELLS:
        return base
    return None


def _completions_dir() -> Path:
    """Where the generated scripts live (``~/.urika/completions/``)."""
    home = Path(os.environ.get("URIKA_HOME") or (Path.home() / ".urika"))
    d = home / "completions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _generate_script(shell: str) -> str:
    """Return the completion script for *shell*.

    Wraps Click 8's ``shell_completion.get_completion_class`` so we
    never have to maintain shell-specific templates ourselves.
    """
    from click.shell_completion import get_completion_class

    cls = get_completion_class(shell)
    if cls is None:
        raise click.ClickException(
            f"Unsupported shell: {shell!r}. Supported: {', '.join(_SUPPORTED_SHELLS)}."
        )
    completion = cls(cli, {}, "urika", "_URIKA_COMPLETE")
    return completion.source()


@cli.group()
def completion() -> None:
    """Manage shell completion for the ``urika`` CLI.

    Subcommands: ``install`` (write the script + print source line),
    ``script`` (print to stdout for manual install), ``uninstall``.
    """


@completion.command("install")
@click.argument(
    "shell",
    type=click.Choice(_SUPPORTED_SHELLS),
    required=False,
)
def completion_install(shell: str | None) -> None:
    """Install the completion script for SHELL (or auto-detect).

    Writes ``~/.urika/completions/urika.<shell>`` and prints the
    ``source`` line the user should add to their shell rc file.
    """
    if shell is None:
        shell = _detect_shell()
        if shell is None:
            raise click.ClickException(
                "Couldn't auto-detect shell from $SHELL. "
                f"Pass one of: {', '.join(_SUPPORTED_SHELLS)}."
            )
        click.echo(f"  Detected shell: {shell}")

    script = _generate_script(shell)
    out_path = _completions_dir() / f"urika.{shell}"
    out_path.write_text(script, encoding="utf-8")
    click.echo(f"  Installed completion to: {out_path}")
    click.echo("  To activate immediately:")
    click.echo(f"    source {out_path}")
    click.echo("  To activate every shell, add the line above to:")
    rc_hint = {
        "bash": "~/.bashrc",
        "zsh": "~/.zshrc",
        "fish": f"~/.config/fish/completions/urika.fish (copy {out_path} there)",
    }.get(shell, "your shell rc file")
    click.echo(f"    {rc_hint}")


@completion.command("script")
@click.argument("shell", type=click.Choice(_SUPPORTED_SHELLS))
def completion_script(shell: str) -> None:
    """Print the completion script for SHELL to stdout."""
    sys.stdout.write(_generate_script(shell))


@completion.command("uninstall")
@click.argument(
    "shell",
    type=click.Choice(_SUPPORTED_SHELLS),
    required=False,
)
def completion_uninstall(shell: str | None) -> None:
    """Remove the installed completion script for SHELL.

    Without ``shell``, removes scripts for every supported shell that
    has one installed. Leaves the user's shell rc file untouched.
    """
    targets = [shell] if shell else list(_SUPPORTED_SHELLS)
    removed = []
    for sh in targets:
        path = _completions_dir() / f"urika.{sh}"
        if path.exists():
            path.unlink()
            removed.append(str(path))
    if removed:
        click.echo("  Removed:")
        for p in removed:
            click.echo(f"    {p}")
        click.echo(
            "  Remember to remove any matching `source` lines from your shell rc file."
        )
    else:
        click.echo("  No installed completion scripts found.")
