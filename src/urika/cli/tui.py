"""TUI command — launches the TypeScript interactive TUI."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import click

from urika.cli._base import cli
from urika.cli._helpers import _resolve_project


def _find_tui_binary() -> str | None:
    """Find the urika-tui binary.

    Searches in order:
    1. URIKA_TUI_BIN env var
    2. System PATH
    3. Local dev build: tui/dist/urika-tui
    4. Local dev via bun: tui/src/index.ts (run with bun)
    """
    # Env override
    env_bin = os.environ.get("URIKA_TUI_BIN")
    if env_bin and Path(env_bin).exists():
        return env_bin

    # System PATH
    system_bin = shutil.which("urika-tui")
    if system_bin:
        return system_bin

    # Local dev build
    repo_root = Path(__file__).parent.parent.parent.parent
    dev_bin = repo_root / "tui" / "dist" / "urika-tui"
    if dev_bin.exists():
        return str(dev_bin)

    # Local dev via bun (run TypeScript directly)
    dev_ts = repo_root / "tui" / "src" / "index.ts"
    if dev_ts.exists() and shutil.which("bun"):
        return None  # Signal to use bun run

    return None


@cli.command()
@click.argument("project", required=False, default=None)
def tui(project: str | None) -> None:
    """Launch the interactive Urika TUI."""
    from urika.cli_display import print_error, print_step

    project_dir = _resolve_project(project) if project else None

    binary = _find_tui_binary()

    if binary:
        # Run compiled binary
        args = [binary]
        if project_dir:
            args.append(str(project_dir))
        print_step("Launching Urika TUI...")
        try:
            result = subprocess.run(args)
            sys.exit(result.returncode)
        except FileNotFoundError:
            print_error(f"TUI binary not found: {binary}")
            raise SystemExit(1)
    else:
        # Try bun dev mode
        repo_root = Path(__file__).parent.parent.parent.parent
        dev_ts = repo_root / "tui" / "src" / "index.ts"
        bun = shutil.which("bun")

        if dev_ts.exists() and bun:
            args = [bun, "run", str(dev_ts)]
            if project_dir:
                args.append(str(project_dir))
            print_step("Launching Urika TUI (dev mode via bun)...")
            try:
                result = subprocess.run(args, cwd=str(repo_root / "tui"))
                sys.exit(result.returncode)
            except FileNotFoundError:
                print_error(
                    "Bun not found. Install bun or build the TUI: cd tui && bun run build"
                )
                raise SystemExit(1)
        else:
            print_error(
                "TUI not found. Options:\n"
                "  1. Build it: cd tui && bun run build\n"
                "  2. Run dev mode: cd tui && bun run dev -- <project-dir>\n"
                "  3. Set URIKA_TUI_BIN environment variable"
            )
            raise SystemExit(1)
