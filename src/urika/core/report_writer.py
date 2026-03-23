"""Write versioned narrative files."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil


def write_versioned(path: Path, content: str) -> Path:
    """Write content to path, preserving previous version with timestamp.

    If path exists, renames it to path-YYYY-MM-DD.ext before writing.
    Returns the path written to.
    """
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stem = path.stem
        suffix = path.suffix
        versioned = path.parent / f"{stem}-{stamp}{suffix}"
        # Don't overwrite an existing version from today
        counter = 1
        while versioned.exists():
            versioned = path.parent / f"{stem}-{stamp}-{counter}{suffix}"
            counter += 1
        shutil.copy2(path, versioned)

    path.write_text(content)
    return path
