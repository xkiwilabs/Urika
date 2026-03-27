"""Knowledge store — ingest, persist, and search knowledge entries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from urika.knowledge.extractors import extract_pdf, extract_text, extract_url
from urika.knowledge.models import KnowledgeEntry

_EXTENSION_TYPES: dict[str, str] = {
    ".pdf": "pdf",
    ".txt": "text",
    ".md": "text",
    ".markdown": "text",
}


class KnowledgeStore:
    """Ingest, persist, and search knowledge entries for a project."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._index_path = project_dir / "knowledge" / "index.json"
        self._entries: list[KnowledgeEntry] = []
        self._load()

    def _load(self) -> None:
        if self._index_path.exists():
            data = json.loads(self._index_path.read_text())
            self._entries = [
                KnowledgeEntry.from_dict(e) for e in data.get("entries", [])
            ]

    def _save(self) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"entries": [e.to_dict() for e in self._entries]}
        self._index_path.write_text(json.dumps(data, indent=2) + "\n")

    def _next_id(self) -> str:
        if not self._entries:
            return "k-001"
        max_num = 0
        for entry in self._entries:
            try:
                num = int(entry.id.split("-")[1])
                max_num = max(max_num, num)
            except (IndexError, ValueError):
                continue
        return f"k-{max_num + 1:03d}"

    def ingest(self, source: str, *, source_type: str | None = None) -> KnowledgeEntry:
        """Ingest a source (file path or URL) into the knowledge store."""
        if source_type is None:
            source_type = self._detect_type(source)

        content = self._extract(source, source_type)
        title = self._derive_title(source, source_type)

        entry = KnowledgeEntry(
            id=self._next_id(),
            source=source,
            source_type=source_type,
            title=title,
            content=content,
            tags=[],
            added_at=datetime.now(tz=timezone.utc).isoformat(),
        )
        self._entries.append(entry)
        self._save()
        return entry

    def search(self, query: str) -> list[KnowledgeEntry]:
        """Search entries by keyword (case-insensitive) in title and content."""
        q = query.lower()
        title_matches: list[KnowledgeEntry] = []
        content_matches: list[KnowledgeEntry] = []
        for entry in self._entries:
            in_title = q in entry.title.lower()
            in_content = q in entry.content.lower()
            if in_title:
                title_matches.append(entry)
            elif in_content:
                content_matches.append(entry)
        return title_matches + content_matches

    def list_all(self) -> list[KnowledgeEntry]:
        """Return all entries."""
        return list(self._entries)

    def get(self, entry_id: str) -> KnowledgeEntry | None:
        """Get an entry by ID."""
        for entry in self._entries:
            if entry.id == entry_id:
                return entry
        return None

    def _detect_type(self, source: str) -> str:
        if source.startswith(("http://", "https://")):
            return "url"
        path = Path(source)
        ext = path.suffix.lower()
        if ext in _EXTENSION_TYPES:
            return _EXTENSION_TYPES[ext]
        raise ValueError(f"Cannot detect source type for: {source}")

    def _extract(self, source: str, source_type: str) -> str:
        if source_type == "pdf":
            return extract_pdf(Path(source))
        if source_type == "text":
            return extract_text(Path(source))
        if source_type == "url":
            return extract_url(source)
        raise ValueError(f"Unknown source type: {source_type}")

    def _derive_title(self, source: str, source_type: str) -> str:
        if source_type == "url":
            return source
        return Path(source).name
