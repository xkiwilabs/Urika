"""Knowledge integration helpers for the orchestrator."""

from __future__ import annotations

from pathlib import Path

from urika.knowledge import KnowledgeStore

_MAX_SNIPPET = 200


def build_knowledge_summary(project_dir: Path) -> str:
    """Build a text summary of project knowledge for agent context.

    Returns an empty string if no knowledge entries exist.
    """
    store = KnowledgeStore(project_dir)
    entries = store.list_all()

    if not entries:
        return ""

    lines = ["## Available Knowledge\n"]
    for entry in entries:
        snippet = entry.content[:_MAX_SNIPPET].replace("\n", " ")
        if len(entry.content) > _MAX_SNIPPET:
            snippet += "..."
        lines.append(f"- **{entry.title}** ({entry.source_type}): {snippet}")

    return "\n".join(lines)
