"""Shared CLI helper functions used across command modules."""

from __future__ import annotations

import os
import re
from pathlib import Path

import click

from urika.core.models import ProjectConfig
from urika.core.registry import ProjectRegistry
from urika.core.workspace import load_project_config


def _make_on_message() -> object:
    """Create an on_message callback that prints tool use events."""
    from urika.cli_display import print_tool_use

    def _on_msg(msg: object) -> None:
        try:
            if hasattr(msg, "content"):
                for block in msg.content:
                    tool_name = getattr(block, "name", None)
                    if tool_name:
                        inp = getattr(block, "input", {}) or {}
                        detail = ""
                        if isinstance(inp, dict):
                            detail = (
                                inp.get("command", "")
                                or inp.get("file_path", "")
                                or inp.get("pattern", "")
                            )
                        print_tool_use(tool_name, detail)
        except Exception:
            pass

    return _on_msg


def _record_agent_usage(
    project_path: Path,
    result: object,
    start_iso: str,
    start_ms: int,
) -> None:
    """Record usage from a single agent call in the CLI."""
    import time

    from datetime import datetime, timezone

    try:
        from urika.core.usage import record_session

        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        record_session(
            project_path,
            started=start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=elapsed_ms,
            tokens_in=getattr(result, "tokens_in", 0),
            tokens_out=getattr(result, "tokens_out", 0),
            cost_usd=getattr(result, "cost_usd", 0.0) or 0.0,
            agent_calls=1,
            experiments_run=0,
        )
    except Exception:
        pass


def _sanitize_project_name(name: str) -> str:
    """Sanitize a project name so it is safe to use as a directory name.

    - Strips leading/trailing whitespace
    - Replaces path separators (/ and \\) with hyphens
    - Removes '..' sequences
    - Keeps only alphanumeric, hyphens, underscores, spaces, and periods
    - Strips leading/trailing dots and hyphens
    - Raises click.ClickException if the result is empty
    """
    name = name.strip()
    name = name.replace("/", "-").replace("\\", "-")
    name = name.replace("..", "")
    name = re.sub(r"[^a-zA-Z0-9 _.\-]", "", name)
    name = name.strip(".-")
    if not name:
        raise click.ClickException(
            "Invalid project name: nothing left after sanitization."
        )
    return name


def _projects_dir() -> Path:
    """Default directory for new projects."""
    env = os.environ.get("URIKA_PROJECTS_DIR")
    if env:
        return Path(env)
    return Path.home() / "urika-projects"


def _resolve_project(name: str) -> tuple[Path, ProjectConfig]:
    """Look up project by name. Raises ClickException on error."""
    registry = ProjectRegistry()
    project_path = registry.get(name)
    if project_path is None:
        raise click.ClickException(f"Project '{name}' not found in registry.")
    try:
        config = load_project_config(project_path)
    except FileNotFoundError:
        raise click.ClickException(f"Project directory missing at {project_path}")
    return project_path, config


def _ensure_project(project: str | None) -> str:
    """If project is None, prompt user to pick from registered projects."""
    if project:
        return project
    registry = ProjectRegistry()
    projects = registry.list_all()
    if not projects:
        raise click.ClickException("No projects registered. Create one with: urika new")
    names = list(projects.keys())
    if len(names) == 1:
        return names[0]
    from urika.cli_helpers import UserCancelled, interactive_numbered

    try:
        return interactive_numbered("\n  Select project:", names, default=1)
    except UserCancelled:
        raise SystemExit(0)


def _test_endpoint(url: str) -> bool:
    """Test if an API endpoint is reachable (3s timeout)."""
    import urllib.request
    import urllib.error

    # Try common health/version endpoints
    for path in ["", "/api/tags", "/v1/models"]:
        try:
            test_url = url.rstrip("/") + path
            req = urllib.request.Request(
                test_url,
                headers={"User-Agent": "urika-endpoint-check"},
            )
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:
            continue
    return False


def _prompt_numbered(prompt_text: str, options: list[str], default: int = 1) -> str:
    """Prompt user with numbered options. Returns the selected option text.

    Exits cleanly (SystemExit 0) if the user cancels.
    """
    from urika.cli_helpers import UserCancelled, interactive_numbered

    try:
        return interactive_numbered(prompt_text, options, default=default)
    except UserCancelled:
        raise SystemExit(0)


def _prompt_path(prompt_text: str, must_exist: bool = True) -> str | None:
    """Prompt for a path, re-asking if it doesn't exist. Empty = skip."""
    from urika.cli_helpers import interactive_prompt

    while True:
        try:
            raw = interactive_prompt(prompt_text).strip()
        except click.Abort:
            return None
        if not raw:
            return None
        resolved = Path(raw).resolve()
        if not must_exist or resolved.exists():
            return str(resolved)
        click.echo(f"  Path not found: {raw}")
        click.echo("  Please check the path and try again.")
