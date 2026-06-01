"""Bash tool callable by adapters that need a function-shaped wrapper.

The Claude SDK adapter gets a Bash tool for free via the bundled CLI;
OpenAI / Google adapters do not, so they register this function via
the SDK's function-tool registration mechanism. ``SecurityPolicy``
enforcement is identical to the ``can_use_tool`` callback in
``urika.agents.permission`` — see ``security.enforce_bash``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from urika.agents.permission import SecurityPolicy
from urika.agents.tools import ToolResult
from urika.agents.tools.security import enforce_bash


def bash(
    cmd: str,
    *,
    security: SecurityPolicy,
    project_dir: Path,
    timeout_seconds: int = 600,
) -> ToolResult:
    deny = enforce_bash(cmd, security)
    if deny is not None:
        return ToolResult(ok=False, output="", error=deny, exit_code=None)
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            ok=False,
            output="",
            error=f"timed out after {timeout_seconds}s",
            exit_code=None,
        )
    return ToolResult(
        ok=proc.returncode == 0,
        output=proc.stdout,
        error=proc.stderr if proc.returncode != 0 else None,
        exit_code=proc.returncode,
    )
