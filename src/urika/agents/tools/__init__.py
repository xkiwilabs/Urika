"""Shared tool layer consumed by non-Claude adapters.

The Claude adapter uses the SDK's built-in tools (Bash/Read/Write/etc)
and enforces ``SecurityPolicy`` via a ``can_use_tool`` callback. The
OpenAI and Google adapters do not get those tools for free, so they
register the functions in this package as SDK function calls.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    error: str | None = None
    exit_code: int | None = None


class ToolRegistry:
    """Returns the tools an agent role is allowed to invoke."""

    @staticmethod
    def for_role(role: str) -> list[str]:
        # All roles get the full set today; tighten per role later.
        return ["bash", "read", "write", "grep", "glob", "edit"]
