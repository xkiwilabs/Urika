"""Bash tool callable by adapters that need a function-shaped wrapper.

The Claude SDK adapter gets a Bash tool for free via the bundled CLI;
OpenAI / Google adapters do not, so they register this function via
the SDK's function-tool registration mechanism. ``SecurityPolicy``
enforcement is identical to the ``can_use_tool`` callback in
``urika.agents.permission`` — see ``security.enforce_bash`` (which
delegates to ``permission._bash_decision``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from urika.agents.config import SecurityPolicy
from urika.agents.tools import ToolResult
from urika.agents.tools.security import enforce_bash

# Maximum bytes of stdout/stderr returned from a single Bash call.
# A runaway command (``find / -type f``, an unbounded training-loop
# log spam, etc.) would otherwise flood the LLM context window with
# one tool result. ~32 KB is a few thousand tokens — enough to be
# useful, small enough to not blow the budget.
_MAX_STREAM_BYTES = 32_000
_HEAD_TAIL_BYTES = _MAX_STREAM_BYTES // 2  # 16 KB head + 16 KB tail


def _cap_stream(text: str) -> str:
    """Cap *text* to ~``_MAX_STREAM_BYTES`` with a head+tail keepsake.

    If the payload is small enough, returns it unchanged. Otherwise
    keeps the first 16 KB and last 16 KB with a ``[truncated N
    bytes]`` marker in the middle so the agent sees both ends.
    """
    if len(text) <= _MAX_STREAM_BYTES:
        return text
    dropped = len(text) - _MAX_STREAM_BYTES
    return (
        text[:_HEAD_TAIL_BYTES]
        + f"\n\n... [truncated {dropped} bytes] ...\n\n"
        + text[-_HEAD_TAIL_BYTES:]
    )


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
        output=_cap_stream(proc.stdout),
        error=_cap_stream(proc.stderr) if proc.returncode != 0 else None,
        exit_code=proc.returncode,
    )
