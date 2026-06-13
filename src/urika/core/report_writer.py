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

    path.write_text(content, encoding="utf-8")
    return path


def extract_report_markdown(text: str | None) -> str | None:
    """Return the report markdown from a report-agent response, or None
    if the response is narration rather than a report.

    The report agent has no file-writing tools — its reply IS the
    report and must begin (within the first few lines) with a markdown
    heading. Narration ("I'll write...", "Let me read...", "I have
    successfully written...") begins with prose and is rejected so it
    never gets written over a real report.
    """
    if not text:
        return None
    s = text.strip()
    if len(s) < 500:
        return None
    lines = s.splitlines()
    for i, line in enumerate(lines[:3]):
        if line.lstrip().startswith("#"):
            body = "\n".join(lines[i:]).strip()
            return body if len(body) >= 500 else None
    return None
