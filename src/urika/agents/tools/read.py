"""Read tool callable by adapters that need a function-shaped wrapper.

The Claude SDK adapter gets a Read tool for free via the bundled CLI;
OpenAI / Google adapters do not, so they register this function via
the SDK's function-tool registration mechanism. ``SecurityPolicy``
enforcement is identical to the ``can_use_tool`` callback in
``urika.agents.permission`` — see ``security.enforce_path_read``
(which delegates to ``permission._path_decision``).
"""

from __future__ import annotations

from urika.agents.config import SecurityPolicy
from urika.agents.tools import ToolResult
from urika.agents.tools.security import enforce_path_read


def read(path: str, *, security: SecurityPolicy) -> ToolResult:
    resolved, err = enforce_path_read(path, security)
    if err is not None or resolved is None:
        return ToolResult(ok=False, output="", error=err or "denied")
    try:
        text = resolved.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ToolResult(ok=False, output="", error=f"no such file: {resolved}")
    except OSError as exc:
        return ToolResult(ok=False, output="", error=str(exc))
    return ToolResult(ok=True, output=text)
