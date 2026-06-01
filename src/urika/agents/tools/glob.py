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
    _, err = enforce_path_read(str(project_dir), security)
    if err is not None:
        return ToolResult(ok=False, output="", error=err)
    matches = [str(p) for p in project_dir.rglob(pattern)]
    return ToolResult(ok=True, output=_cap_stream("\n".join(matches)))
