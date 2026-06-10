"""Corrupt-tolerant JSON file loading.

Reading a JSON state file that was partially written (crash mid-write,
disk full) must never crash the caller or silently discard the user's
data. ``load_json_or_preserve`` returns a fallback instead of raising,
and preserves the corrupt bytes next to the original (timestamped, so
repeated corruption never clobbers an earlier salvageable copy) —
mirroring the ``advisor_memory`` precedent introduced in v0.4.2.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def preserve_corrupt_file(path: Path) -> Path | None:
    """Rename *path* to ``<name>.corrupt-<unix-ts>``; None on failure.

    The preserved name is ``<original-name>.corrupt-<unix-ts>``, e.g.
    ``sess-1.json.corrupt-1760000000``.  This format intentionally never
    matches ``*.json`` globs (the extension is appended, not replaced),
    so list_sessions and similar scanners will not pick it up.

    If the target already exists (two corruptions within the same second),
    a ``-<n>`` counter is appended to guarantee uniqueness.
    """
    base = path.name
    ts = int(time.time())
    target = path.with_name(f"{base}.corrupt-{ts}")
    counter = 1
    while target.exists():
        target = path.with_name(f"{base}.corrupt-{ts}-{counter}")
        counter += 1
    try:
        path.replace(target)
    except OSError:
        return None
    return target


def load_json_or_preserve(path: Path, fallback: Any) -> Any:
    """Parse JSON from *path*; on corruption, preserve the file and return *fallback*.

    Missing file → *fallback* (nothing to preserve). The fallback value is
    returned as-is — callers pass a fresh instance per call site.
    """
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        preserved = preserve_corrupt_file(path)
        logger.warning("Corrupt JSON at %s: %s — preserved as %s", path, exc, preserved)
        return fallback
