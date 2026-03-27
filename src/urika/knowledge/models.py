"""Knowledge entry data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class KnowledgeEntry:
    """A single piece of ingested knowledge."""

    id: str
    source: str
    source_type: str
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    added_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "source_type": self.source_type,
            "title": self.title,
            "content": self.content,
            "tags": self.tags,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KnowledgeEntry:
        return cls(
            id=d["id"],
            source=d["source"],
            source_type=d["source_type"],
            title=d["title"],
            content=d["content"],
            tags=d.get("tags", []),
            added_at=d.get("added_at", ""),
        )
