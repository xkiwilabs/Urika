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
    # Scan the first few lines for the leading heading. A compliant
    # report starts at line 0; we tolerate a short (1-2 line + blank)
    # preamble before rejecting as narration — captured narration
    # always runs 4+ prose lines before any heading.
    for i, line in enumerate(lines[:5]):
        if line.lstrip().startswith("#"):
            body = "\n".join(lines[i:]).strip()
            return body if len(body) >= 500 else None
    return None


# Narration openers — an agent describing what it's doing rather than
# producing the deliverable. Used to reject chatter from artifacts that
# are legitimately short/heading-less prose (e.g. project summaries),
# where extract_report_markdown's heading requirement is too strict.
_NARRATION_OPENERS = (
    "i'll ",
    "i will ",
    "let me ",
    "i have written",
    "i've written",
    "i have successfully",
    "i've successfully",
    "successfully written",
    "successfully wrote",
    "let me check if the file",
    "let me start by",
    "let me read",
    "here is the",
    "here's the",
    "now let me",
    "i'll now",
    "i am going to",
    "i'm going to",
    "sure,",
    "certainly,",
    "of course,",
)


def looks_like_narration(text: str | None) -> bool:
    """True if *text* looks like agent chatter (describing that it wrote/did
    something) rather than the deliverable itself. Heuristic: the first
    non-blank line opens with a narration phrase, or the head contains a
    strong "successfully wrote/written" marker."""
    if not text:
        return False
    s = text.strip()
    first = next((ln.strip().lower() for ln in s.splitlines() if ln.strip()), "")
    if any(first.startswith(op) for op in _NARRATION_OPENERS):
        return True
    head = s[:600].lower()
    return (
        "successfully written" in head
        or "successfully wrote" in head
        or "i have successfully" in head
    )
