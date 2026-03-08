"""Tests for KnowledgeEntry model."""

from __future__ import annotations

from urika.knowledge.models import KnowledgeEntry


class TestKnowledgeEntry:
    def test_create(self) -> None:
        entry = KnowledgeEntry(
            id="k-001",
            source="papers/test.pdf",
            source_type="pdf",
            title="Test Paper",
            content="Some extracted text",
            tags=[],
            added_at="2026-03-09T00:00:00",
        )
        assert entry.id == "k-001"
        assert entry.source_type == "pdf"

    def test_to_dict(self) -> None:
        entry = KnowledgeEntry(
            id="k-001",
            source="test.pdf",
            source_type="pdf",
            title="Test",
            content="Text",
            tags=["ml"],
            added_at="2026-03-09T00:00:00",
        )
        d = entry.to_dict()
        assert d["id"] == "k-001"
        assert d["tags"] == ["ml"]
        assert d["source_type"] == "pdf"

    def test_from_dict(self) -> None:
        d = {
            "id": "k-002",
            "source": "notes.md",
            "source_type": "text",
            "title": "Notes",
            "content": "My notes",
            "tags": [],
            "added_at": "2026-03-09T00:00:00",
        }
        entry = KnowledgeEntry.from_dict(d)
        assert entry.id == "k-002"
        assert entry.source_type == "text"

    def test_roundtrip(self) -> None:
        entry = KnowledgeEntry(
            id="k-001",
            source="test.pdf",
            source_type="pdf",
            title="Test",
            content="Content",
            tags=["tag1"],
            added_at="2026-03-09T00:00:00",
        )
        assert KnowledgeEntry.from_dict(entry.to_dict()) == entry
