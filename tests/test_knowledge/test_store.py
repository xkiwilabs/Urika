"""Tests for KnowledgeStore."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from urika.knowledge.store import KnowledgeStore


class TestKnowledgeStoreIngest:
    def test_ingest_text_file(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        notes = tmp_path / "knowledge" / "notes.txt"
        notes.write_text("Research notes about regression.")
        store = KnowledgeStore(tmp_path)
        entry = store.ingest(str(notes))
        assert entry.id == "k-001"
        assert entry.source_type == "text"
        assert "regression" in entry.content
        assert entry.title == "notes.txt"

    def test_ingest_md_file(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        notes = tmp_path / "knowledge" / "notes.md"
        notes.write_text("# My Notes\nContent here.")
        store = KnowledgeStore(tmp_path)
        entry = store.ingest(str(notes))
        assert entry.source_type == "text"

    def test_ingest_pdf(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        pdf = tmp_path / "knowledge" / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        store = KnowledgeStore(tmp_path)
        with patch("pypdf.PdfReader") as mock_cls:
            mock_page = type("Page", (), {"extract_text": lambda self: "PDF content"})()
            mock_cls.return_value.pages = [mock_page]
            entry = store.ingest(str(pdf))
        assert entry.source_type == "pdf"
        assert "PDF content" in entry.content

    def test_ingest_url(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        store = KnowledgeStore(tmp_path)
        with patch("urika.knowledge.extractors.urlopen") as mock_urlopen:
            mock_resp = type(
                "Resp",
                (),
                {
                    "read": lambda self, *a: b"<html><body>Web content</body></html>",
                    "headers": type(
                        "H", (), {"get_content_charset": lambda self: "utf-8"}
                    )(),
                    "__enter__": lambda self: self,
                    "__exit__": lambda self, *a: False,
                },
            )()
            mock_urlopen.return_value = mock_resp
            entry = store.ingest("https://example.com/paper", source_type="url")
        assert entry.source_type == "url"
        assert "Web content" in entry.content

    def test_ingest_url_auto_detected(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        store = KnowledgeStore(tmp_path)
        with patch("urika.knowledge.extractors.urlopen") as mock_urlopen:
            mock_resp = type(
                "Resp",
                (),
                {
                    "read": lambda self, *a: b"<html><body>Auto detected</body></html>",
                    "headers": type(
                        "H", (), {"get_content_charset": lambda self: "utf-8"}
                    )(),
                    "__enter__": lambda self: self,
                    "__exit__": lambda self, *a: False,
                },
            )()
            mock_urlopen.return_value = mock_resp
            entry = store.ingest("https://example.com/paper")
        assert entry.source_type == "url"

    def test_ingest_assigns_sequential_ids(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        (tmp_path / "knowledge" / "a.txt").write_text("Note A")
        (tmp_path / "knowledge" / "b.txt").write_text("Note B")
        store = KnowledgeStore(tmp_path)
        e1 = store.ingest(str(tmp_path / "knowledge" / "a.txt"))
        e2 = store.ingest(str(tmp_path / "knowledge" / "b.txt"))
        assert e1.id == "k-001"
        assert e2.id == "k-002"

    def test_ingest_persists_to_index(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        (tmp_path / "knowledge" / "test.txt").write_text("Persisted content")
        store = KnowledgeStore(tmp_path)
        store.ingest(str(tmp_path / "knowledge" / "test.txt"))
        # Load fresh store and verify entry exists
        store2 = KnowledgeStore(tmp_path)
        assert len(store2.list_all()) == 1


class TestKnowledgeStoreSearch:
    def test_search_by_content(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        (tmp_path / "knowledge" / "a.txt").write_text("Linear regression is useful.")
        (tmp_path / "knowledge" / "b.txt").write_text("Random forests are great.")
        store = KnowledgeStore(tmp_path)
        store.ingest(str(tmp_path / "knowledge" / "a.txt"))
        store.ingest(str(tmp_path / "knowledge" / "b.txt"))
        results = store.search("regression")
        assert len(results) == 1
        assert results[0].id == "k-001"

    def test_search_case_insensitive(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        (tmp_path / "knowledge" / "a.txt").write_text("REGRESSION analysis")
        store = KnowledgeStore(tmp_path)
        store.ingest(str(tmp_path / "knowledge" / "a.txt"))
        results = store.search("regression")
        assert len(results) == 1

    def test_search_by_title(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        (tmp_path / "knowledge" / "regression_notes.txt").write_text("Some content")
        store = KnowledgeStore(tmp_path)
        store.ingest(str(tmp_path / "knowledge" / "regression_notes.txt"))
        results = store.search("regression")
        assert len(results) == 1

    def test_search_no_results(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        (tmp_path / "knowledge" / "a.txt").write_text("Nothing relevant.")
        store = KnowledgeStore(tmp_path)
        store.ingest(str(tmp_path / "knowledge" / "a.txt"))
        results = store.search("quantum")
        assert results == []

    def test_search_title_matches_first(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        (tmp_path / "knowledge" / "other.txt").write_text("Text about regression")
        (tmp_path / "knowledge" / "regression.txt").write_text("Some notes")
        store = KnowledgeStore(tmp_path)
        store.ingest(str(tmp_path / "knowledge" / "other.txt"))
        store.ingest(str(tmp_path / "knowledge" / "regression.txt"))
        results = store.search("regression")
        assert len(results) == 2
        assert results[0].title == "regression.txt"


class TestKnowledgeStoreListGet:
    def test_list_all_empty(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        store = KnowledgeStore(tmp_path)
        assert store.list_all() == []

    def test_list_all(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        (tmp_path / "knowledge" / "a.txt").write_text("A")
        (tmp_path / "knowledge" / "b.txt").write_text("B")
        store = KnowledgeStore(tmp_path)
        store.ingest(str(tmp_path / "knowledge" / "a.txt"))
        store.ingest(str(tmp_path / "knowledge" / "b.txt"))
        assert len(store.list_all()) == 2

    def test_get_existing(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        (tmp_path / "knowledge" / "a.txt").write_text("Content A")
        store = KnowledgeStore(tmp_path)
        store.ingest(str(tmp_path / "knowledge" / "a.txt"))
        entry = store.get("k-001")
        assert entry is not None
        assert entry.title == "a.txt"

    def test_get_nonexistent(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        store = KnowledgeStore(tmp_path)
        assert store.get("k-999") is None
