"""Grep tool callable by adapters that need a function-shaped wrapper.

The Claude SDK adapter gets a Grep tool for free via the bundled CLI;
OpenAI / Google adapters do not, so they register this function via
the SDK's function-tool registration mechanism. ``SecurityPolicy``
enforcement is identical to the ``can_use_tool`` callback in
``urika.agents.permission`` — see ``security.enforce_path_read``
(which delegates to ``permission._path_decision``).

The walker skips binary files (NUL byte heuristic in the first 1 KB)
and the total output is bounded via ``_cap_stream`` so a search that
matches millions of lines can't single-handedly fill the LLM context.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from urika.agents.config import SecurityPolicy
from urika.agents.tools import ToolResult
from urika.agents.tools.bash import _cap_stream
from urika.agents.tools.security import enforce_path_read

# Bytes sampled from the head of each file to detect a binary payload.
# A NUL byte in plain text is vanishingly rare, so it's a cheap, fast
# signal — the same heuristic ``grep -I`` uses.
_BINARY_SNIFF_BYTES = 1024


def grep(pattern: str, path: str, *, security: SecurityPolicy) -> ToolResult:
    resolved, err = enforce_path_read(path, security)
    if err is not None or resolved is None:
        return ToolResult(ok=False, output="", error=err or "denied")
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return ToolResult(ok=False, output="", error=f"bad pattern: {exc}")
    hits: list[str] = []
    for fp in _walk_files(resolved):
        if _looks_binary(fp):
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{fp}:{n}:{line}")
    return ToolResult(ok=True, output=_cap_stream("\n".join(hits)))


def _walk_files(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def _looks_binary(fp: Path) -> bool:
    """Return True if the file's head contains a NUL byte.

    Cheap, fast, and matches ``grep -I``'s heuristic. Files we can't
    open are treated as binary (skipped) — the caller would otherwise
    surface a misleading "no matches" for an unreadable file.
    """
    try:
        with fp.open("rb") as fh:
            chunk = fh.read(_BINARY_SNIFF_BYTES)
    except OSError:
        return True
    return b"\x00" in chunk
