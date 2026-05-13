"""Shared CLI helper functions used across command modules."""

from __future__ import annotations

import os
import re
from pathlib import Path

import click

from urika.core.errors import ConfigError, ValidationError
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


def _agent_run_start() -> tuple[int, str]:
    """Return (start_ms, start_iso) for timing and recording an agent call.

    Every CLI agent-invocation command needs both: a monotonic start time
    for elapsed-ms math, and a wall-clock ISO string for usage records.
    Returning the pair from one place kills the duplicated two-liner
    that used to open almost every agent command.
    """
    import time
    from datetime import datetime, timezone

    start_ms = int(time.monotonic() * 1000)
    start_iso = datetime.now(timezone.utc).isoformat()
    return start_ms, start_iso


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
        raise ValidationError(
            "Invalid project name: nothing left after sanitization.",
            hint="Use letters, digits, hyphens, underscores, or periods.",
        )
    return name


def _projects_dir() -> Path:
    """Default directory for new projects."""
    env = os.environ.get("URIKA_PROJECTS_DIR")
    if env:
        return Path(env)
    return Path.home() / "urika-projects"


def _resolve_project(name: str) -> tuple[Path, ProjectConfig]:
    """Look up project by name. Raises ConfigError on error."""
    registry = ProjectRegistry()
    project_path = registry.get(name)
    if project_path is None:
        raise ConfigError(
            f"Project '{name}' not found in registry.",
            hint="List registered projects with: urika list",
        )
    try:
        config = load_project_config(project_path)
    except FileNotFoundError:
        raise ConfigError(
            f"Project directory missing at {project_path}",
            hint="The project was moved or deleted. Re-register or remove: urika list",
        )
    return project_path, config


def _ensure_project(project: str | None) -> str:
    """If project is None, prompt user to pick from registered projects."""
    if project:
        return project
    registry = ProjectRegistry()
    projects = registry.list_all()
    if not projects:
        raise ConfigError(
            "No projects registered.",
            hint="Create one with: urika new <name>",
        )
    names = list(projects.keys())
    if len(names) == 1:
        return names[0]
    from urika.cli_helpers import UserCancelled, interactive_numbered

    try:
        return interactive_numbered("\n  Select project:", names, default=1)
    except UserCancelled:
        raise SystemExit(0)


def _probe_endpoint(url: str) -> tuple[bool, str]:
    """Probe an API endpoint; return ``(reachable, detail)``.

    ``reachable`` is True for any HTTP response from the server —
    including 401 / 403 / 404 — because that proves the server is up
    and the endpoint exists. Auth rejection just means the probe
    didn't send a key.

    ``detail`` is a short human-readable summary suitable for surfacing
    in the dashboard:

    * On success: ``"OK"`` for 2xx, ``"reachable (HTTP <code>)"`` for
      a non-2xx response.
    * On failure: a one-line reason — ``"connection refused"``,
      ``"name not resolved"``, ``"SSL error: <msg>"``, ``"timed out"``,
      etc. Never includes the URL or auth-bearing strings.
    """
    import socket
    import ssl
    import urllib.error
    import urllib.request

    # Validate scheme upfront so we return a useful message instead of
    # surfacing urllib's cryptic "unknown url type: <scheme>" — which
    # users tend to hit when they paste a URL with a label prefix
    # ("Tailscale: http://...") or omit the protocol entirely
    # (host:port without "http://").
    stripped = url.strip()
    if not stripped:
        return False, "URL is empty"
    if not (stripped.startswith("http://") or stripped.startswith("https://")):
        return False, "URL must start with http:// or https://"

    # Bypass any system HTTP(S)_PROXY env vars: private endpoints
    # (Tailscale, LAN, localhost) almost always need a direct
    # connection; routing them through a corporate proxy is the wrong
    # default and the most common cause of "url error: str" failures.
    no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = stripped

    last_reason: str | None = None

    for path in ("", "/api/tags", "/v1/models", "/models"):
        test_url = url.rstrip("/") + path
        try:
            req = urllib.request.Request(
                test_url,
                headers={"User-Agent": "urika-endpoint-check"},
            )
        except (ValueError, TypeError) as e:
            return False, f"invalid url: {type(e).__name__}"

        try:
            with no_proxy_opener.open(req, timeout=3) as resp:
                code = getattr(resp, "status", None) or resp.getcode()
                if 200 <= code < 300:
                    return True, "OK"
                return True, f"reachable (HTTP {code})"
        except urllib.error.HTTPError as e:
            # Server responded with a non-2xx status — endpoint exists.
            return True, f"reachable (HTTP {e.code})"
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, ssl.SSLError):
                last_reason = f"SSL error: {reason.reason or reason}"
            elif isinstance(reason, socket.gaierror):
                last_reason = "name not resolved (DNS)"
            elif isinstance(reason, ConnectionRefusedError):
                last_reason = "connection refused"
            elif isinstance(reason, TimeoutError):
                last_reason = "timed out"
            elif isinstance(reason, OSError):
                # Generic OS-level network error — strip path-like info.
                last_reason = (
                    f"network error: {reason.strerror or type(reason).__name__}"
                )
            elif isinstance(reason, str):
                # urllib sometimes wraps a plain string (typically from
                # proxy / handler chain failures). Pass it through —
                # the message is generally safe and tells the user what
                # went wrong.
                last_reason = reason
            else:
                last_reason = f"url error: {type(reason).__name__}"
        except TimeoutError:
            last_reason = "timed out"
        except OSError as e:
            last_reason = f"os error: {e.strerror or type(e).__name__}"

    return False, last_reason or "no response"


def _test_endpoint(url: str) -> bool:
    """Test if an API endpoint is reachable (3s timeout).

    Thin bool wrapper around :func:`_probe_endpoint` for legacy
    callers that don't need the failure reason.
    """
    return _probe_endpoint(url)[0]


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
