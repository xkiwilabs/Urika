"""Append-only JSON Lines records.

One record per line, appended, never rewritten. Used for per-turn
history that must survive later turns (plans, evaluations) where an
overwrite-latest file would erase the trail.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append *record* as one line to *path*, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read every well-formed record in *path*; missing file → []."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out
