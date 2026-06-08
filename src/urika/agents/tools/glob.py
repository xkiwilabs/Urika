"""Glob tool callable by adapters that need a function-shaped wrapper.

The Claude SDK adapter gets a Glob tool for free via the bundled CLI;
OpenAI / Google adapters do not, so they register this function via
the SDK's function-tool registration mechanism. ``SecurityPolicy``
enforcement is identical to the ``can_use_tool`` callback in
``urika.agents.permission`` — see ``security.enforce_path_read``
(which delegates to ``permission._path_decision``).
"""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import SecurityPolicy
from urika.agents.tools import ToolResult
from urika.agents.tools.bash import _cap_stream
from urika.agents.tools.security import enforce_path_read


def glob(pattern: str, *, security: SecurityPolicy, project_dir: Path) -> ToolResult:
    # Some agents (notably Gemini) pass absolute patterns like
    # "/home/foo/*.csv" instead of relative "*.csv". Python 3.12's
    # Path.rglob() raises NotImplementedError on absolute patterns.
    # Detect + split: use the absolute parent as the search root and
    # the trailing name pattern as the rglob filter. Then re-enforce
    # the security policy against the resolved root.
    p = Path(pattern)
    if p.is_absolute():
        root = p.parent
        name_pattern = p.name or "*"
        resolved, err = enforce_path_read(str(root), security)
        if err is not None:
            return ToolResult(ok=False, output="", error=err)
        search_root = resolved or root
    else:
        _, err = enforce_path_read(str(project_dir), security)
        if err is not None:
            return ToolResult(ok=False, output="", error=err)
        search_root = project_dir
        name_pattern = pattern
    try:
        matches = [str(m) for m in search_root.rglob(name_pattern)]
    except (NotImplementedError, ValueError) as exc:
        return ToolResult(ok=False, output="", error=f"invalid glob pattern: {exc}")
    return ToolResult(ok=True, output=_cap_stream("\n".join(matches)))
