"""Tests for knowledge package public API."""

from __future__ import annotations


class TestKnowledgePublicAPI:
    def test_knowledge_entry_importable(self) -> None:
        from urika.knowledge import KnowledgeEntry

        assert KnowledgeEntry is not None

    def test_knowledge_store_importable(self) -> None:
        from urika.knowledge import KnowledgeStore

        assert KnowledgeStore is not None

    def test_extract_pdf_importable(self) -> None:
        from urika.knowledge import extract_pdf

        assert callable(extract_pdf)

    def test_extract_text_importable(self) -> None:
        from urika.knowledge import extract_text

        assert callable(extract_text)

    def test_extract_url_importable(self) -> None:
        from urika.knowledge import extract_url

        assert callable(extract_url)
