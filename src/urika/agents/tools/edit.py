"""Edit tool callable by adapters that need a function-shaped wrapper.

The Claude SDK adapter gets an Edit tool for free via the bundled CLI;
OpenAI / Google adapters do not, so they register this function via
the SDK's function-tool registration mechanism. ``SecurityPolicy``
enforcement is identical to the ``can_use_tool`` callback in
``urika.agents.permission`` — see ``security.enforce_path_write``
(which delegates to ``permission._path_decision``).

The uniqueness check (exactly one occurrence of ``old_string``) is
the same contract Claude Code's built-in Edit enforces: it forces
the caller to supply enough context to disambiguate, instead of
silently rewriting every occurrence.
"""

from __future__ import annotations

from urika.agents.config import SecurityPolicy
from urika.agents.tools import ToolResult
from urika.agents.tools.security import enforce_path_write


def edit(
    path: str,
    old_string: str,
    new_string: str,
    *,
    security: SecurityPolicy,
) -> ToolResult:
    resolved, err = enforce_path_write(path, security)
    if err is not None or resolved is None:
        return ToolResult(ok=False, output="", error=err or "denied")
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        return ToolResult(ok=False, output="", error=str(exc))
    count = text.count(old_string)
    if count == 0:
        return ToolResult(ok=False, output="", error="old_string not found")
    if count > 1:
        return ToolResult(
            ok=False,
            output="",
            error=f"old_string occurs {count} times — must be unique",
        )
    try:
        resolved.write_text(text.replace(old_string, new_string), encoding="utf-8")
    except OSError as exc:
        return ToolResult(ok=False, output="", error=str(exc))
    return ToolResult(ok=True, output=f"edited {resolved}")
