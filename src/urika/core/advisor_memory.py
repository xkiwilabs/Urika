"""Persistent advisor conversation memory.

Two-tier system:
- Full history: projectbook/advisor-history.json (append-only audit log)
- Rolling summary: projectbook/advisor-context.md (always loaded into advisor context)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from urika.core.atomic_write import write_json_atomic, write_text_atomic

logger = logging.getLogger(__name__)


def append_exchange(
    project_dir: Path,
    *,
    role: str,
    text: str,
    source: str = "repl",
    suggestions: list[dict] | None = None,
) -> None:
    """Append a single message to the advisor history.

    Args:
        project_dir: Project root directory.
        role: "user" or "advisor".
        text: The message text.
        source: Origin — "repl", "cli", "telegram", "slack", "meta".
        suggestions: Parsed suggestions from advisor response (if any).
    """
    history_path = project_dir / "projectbook" / "advisor-history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing. Pre-v0.4.2 a JSONDecodeError silently reset
    # ``entries`` to ``[]`` and rewrote the file, destroying the
    # entire conversation history on a single corrupt write. Now
    # the corrupt file is preserved as ``.corrupt-<ts>`` so it can
    # be inspected or salvaged before being overwritten.
    entries: list[dict[str, Any]] = []
    if history_path.exists():
        try:
            entries = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as exc:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            backup = history_path.with_suffix(f".corrupt-{ts}.json")
            try:
                history_path.rename(backup)
                logger.warning(
                    "Corrupt advisor history at %s (%s); preserved as %s",
                    history_path,
                    exc,
                    backup,
                )
            except OSError:
                logger.warning(
                    "Corrupt advisor history at %s (%s); could not preserve backup",
                    history_path,
                    exc,
                )
            entries = []

    entry: dict[str, Any] = {
        "role": role,
        "text": text,
        "source": source,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if suggestions:
        entry["suggestions"] = suggestions

    entries.append(entry)
    write_json_atomic(history_path, entries)


def load_history(project_dir: Path, last_n: int | None = None) -> list[dict]:
    """Load advisor conversation history.

    Args:
        project_dir: Project root directory.
        last_n: If set, return only the last N entries.
    """
    history_path = project_dir / "projectbook" / "advisor-history.json"
    if not history_path.exists():
        return []
    try:
        entries = json.loads(history_path.read_text(encoding="utf-8"))
        if last_n is not None:
            return entries[-last_n:]
        return entries
    except (json.JSONDecodeError, ValueError):
        return []


def load_context_summary(project_dir: Path) -> str:
    """Load the rolling advisor context summary.

    Returns empty string if no summary exists yet.
    """
    summary_path = project_dir / "projectbook" / "advisor-context.md"
    if summary_path.exists():
        return summary_path.read_text(encoding="utf-8").strip()
    return ""


def save_context_summary(project_dir: Path, summary: str) -> None:
    """Save the rolling advisor context summary."""
    summary_path = project_dir / "projectbook" / "advisor-context.md"
    write_text_atomic(summary_path, summary.strip() + "\n")


def format_recent_history(entries: list[dict], max_entries: int = 6) -> str:
    """Format recent history entries as readable text for context injection."""
    if not entries:
        return ""
    recent = entries[-max_entries:]
    lines = []
    for e in recent:
        role = e.get("role", "?").capitalize()
        text = e.get("text", "")
        # Truncate long messages
        if len(text) > 300:
            text = text[:297] + "..."
        source = e.get("source", "")
        source_tag = f" [{source}]" if source and source != "repl" else ""
        lines.append(f"{role}{source_tag}: {text}")
    return "\n\n".join(lines)


async def update_context_summary(
    project_dir: Path,
    runner: object,
    registry: object = None,
) -> None:
    """Ask the advisor to update the rolling context summary.

    Reads the current summary and last 6 history entries, asks the advisor
    to produce an updated summary. This is a lightweight call (~500 tokens output).
    """
    current_summary = load_context_summary(project_dir)
    recent = format_recent_history(load_history(project_dir, last_n=6))

    if not recent:
        return  # Nothing to summarize

    if registry is None:
        from urika.agents.registry import AgentRegistry

        registry = AgentRegistry()
        registry.discover()

    advisor = registry.get("advisor_agent")
    if advisor is None:
        return

    prompt = (
        "Update the research context summary below based on the recent conversation. "
        "Keep it under 800 words. Structure:\n\n"
        "# Research Context\n\n"
        "## Current Strategy\n"
        "2-3 sentences on the current research direction.\n\n"
        "## Recent Decisions\n"
        "Bullet list of what was agreed, rejected, or discovered in recent discussions.\n\n"
        "## Next Steps\n"
        "Bullet list of pending experiments or analyses planned.\n\n"
        "## Key Insights\n"
        "Bullet list of important findings that should inform future decisions.\n\n"
        "---\n\n"
    )

    if current_summary:
        prompt += f"CURRENT SUMMARY:\n{current_summary}\n\n"
    else:
        prompt += "CURRENT SUMMARY: (none yet — create from scratch)\n\n"

    prompt += f"RECENT CONVERSATION:\n{recent}\n\n"
    prompt += "Output ONLY the updated summary in markdown. No preamble."

    config = advisor.build_config(project_dir=project_dir, experiment_id="")
    config.max_turns = 3  # Quick summary, no tool use needed

    try:
        result = await runner.run(config, prompt)
        if result.success and result.text_output:
            text = result.text_output.strip()
            # Validate it looks like a summary (has headings, reasonable length)
            if len(text) > 100 and "#" in text:
                save_context_summary(project_dir, text)
    except Exception as exc:
        logger.warning("Failed to update advisor context summary: %s", exc)
