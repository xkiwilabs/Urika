# Knowledge Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a knowledge ingestion and search pipeline (PDFs, text files, URLs) plus a literature agent role that uses it.

**Architecture:** A `knowledge/` package with extractors (PDF via pypdf, text, URL via urllib), a `KnowledgeEntry` model, and a `KnowledgeStore` that persists to `knowledge/index.json` per project. Keyword search over title and content. A literature agent role follows the existing agent pattern.

**Tech Stack:** pypdf (PDF extraction), urllib (URL fetching), existing agent infrastructure

---

## Reference Files

Before starting, read these to understand existing patterns:

- `src/urika/agents/roles/echo.py` — Agent role pattern (get_role, build_config)
- `tests/test_agents/test_echo_role.py` — Agent role test pattern
- `src/urika/agents/prompt.py` — `load_prompt()` with `{var}` substitution
- `src/urika/core/models.py` — Existing dataclass patterns (to_dict, from_dict)
- `docs/plans/2026-03-09-knowledge-pipeline-design.md` — Approved design spec

---

### Task 1: KnowledgeEntry Model + Extractors

**Files:**
- Create: `src/urika/knowledge/__init__.py`
- Create: `src/urika/knowledge/models.py`
- Create: `src/urika/knowledge/extractors.py`
- Create: `tests/test_knowledge/__init__.py`
- Create: `tests/test_knowledge/test_models.py`
- Create: `tests/test_knowledge/test_extractors.py`
- Modify: `pyproject.toml` — add `pypdf>=4.0`

**Step 1: Add pypdf dependency**

In `pyproject.toml`, add `"pypdf>=4.0",` to the `dependencies` list. Then run `pip install -e ".[dev]"`.

**Step 2: Write the failing tests for models**

```python
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
```

**Step 3: Write the failing tests for extractors**

```python
"""Tests for knowledge extractors."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from urika.knowledge.extractors import extract_pdf, extract_text, extract_url


class TestExtractText:
    def test_extracts_txt_content(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text("These are my research notes.")
        result = extract_text(f)
        assert result == "These are my research notes."

    def test_extracts_md_content(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.md"
        f.write_text("# Heading\n\nSome content.")
        result = extract_text(f)
        assert "Heading" in result

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("")
        with pytest.raises(ValueError, match="empty"):
            extract_text(f)

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            extract_text(tmp_path / "nope.txt")


class TestExtractPdf:
    def test_extracts_pdf_content(self, tmp_path: Path) -> None:
        """Test with a mock since creating real PDFs in tests is heavy."""
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page 1 content"
        mock_reader.pages = [mock_page]

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        with patch("urika.knowledge.extractors.PdfReader", return_value=mock_reader):
            result = extract_pdf(pdf_path)
        assert result == "Page 1 content"

    def test_multi_page_pdf(self, tmp_path: Path) -> None:
        mock_reader = MagicMock()
        page1 = MagicMock()
        page1.extract_text.return_value = "Page 1"
        page2 = MagicMock()
        page2.extract_text.return_value = "Page 2"
        mock_reader.pages = [page1, page2]

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        with patch("urika.knowledge.extractors.PdfReader", return_value=mock_reader):
            result = extract_pdf(pdf_path)
        assert "Page 1" in result
        assert "Page 2" in result

    def test_empty_pdf_raises(self, tmp_path: Path) -> None:
        mock_reader = MagicMock()
        mock_reader.pages = []

        pdf_path = tmp_path / "empty.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        with patch("urika.knowledge.extractors.PdfReader", return_value=mock_reader):
            with pytest.raises(ValueError, match="empty"):
                extract_pdf(pdf_path)

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            extract_pdf(tmp_path / "nope.pdf")


class TestExtractUrl:
    def test_extracts_html_content(self) -> None:
        html = b"<html><body><h1>Title</h1><p>Some text content.</p></body></html>"
        mock_response = MagicMock()
        mock_response.read.return_value = html
        mock_response.headers.get_content_charset.return_value = "utf-8"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urika.knowledge.extractors.urlopen", return_value=mock_response):
            result = extract_url("https://example.com")
        assert "Title" in result
        assert "Some text content" in result
        assert "<h1>" not in result

    def test_empty_response_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.read.return_value = b""
        mock_response.headers.get_content_charset.return_value = "utf-8"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urika.knowledge.extractors.urlopen", return_value=mock_response):
            with pytest.raises(ValueError, match="empty"):
                extract_url("https://example.com")

    def test_unreachable_raises(self) -> None:
        with patch("urika.knowledge.extractors.urlopen", side_effect=OSError("Connection refused")):
            with pytest.raises(ValueError, match="fetch"):
                extract_url("https://unreachable.example.com")
```

**Step 4: Run tests to verify they fail**

Run: `pytest tests/test_knowledge/ -v`
Expected: FAIL — ModuleNotFoundError

**Step 5: Write the implementations**

`src/urika/knowledge/__init__.py` (empty for now):
```python
```

`tests/test_knowledge/__init__.py` (empty).

`src/urika/knowledge/models.py`:
```python
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
```

`src/urika/knowledge/extractors.py`:
```python
"""Extract text content from various source types."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen


def extract_text(path: Path) -> str:
    """Extract content from a text or markdown file."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    content = path.read_text()
    if not content.strip():
        raise ValueError(f"File is empty: {path}")
    return content


def extract_pdf(path: Path) -> str:
    """Extract text content from a PDF file."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    from pypdf import PdfReader

    reader = PdfReader(path)
    if not reader.pages:
        raise ValueError(f"PDF is empty: {path}")
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    if not parts:
        raise ValueError(f"PDF has no extractable text: {path}")
    return "\n".join(parts)


def extract_url(url: str) -> str:
    """Fetch a URL and extract text content from HTML."""
    try:
        with urlopen(url) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read()
    except OSError as exc:
        raise ValueError(f"Failed to fetch URL: {exc}") from exc
    if not raw:
        raise ValueError(f"Empty response from URL: {url}")
    html = raw.decode(charset, errors="replace")
    return _strip_html_tags(html)


def _strip_html_tags(html: str) -> str:
    """Remove HTML tags and return plain text."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
```

**Step 6: Run tests**

Run: `pytest tests/test_knowledge/ -v`
Expected: All PASS

**Step 7: Lint and commit**

```bash
ruff check src/urika/knowledge/ tests/test_knowledge/
ruff format --check src/urika/knowledge/ tests/test_knowledge/
git add pyproject.toml src/urika/knowledge/ tests/test_knowledge/
git commit -m "feat: add knowledge entry model and extractors"
```

---

### Task 2: KnowledgeStore

**Files:**
- Create: `src/urika/knowledge/store.py`
- Create: `tests/test_knowledge/test_store.py`

**Step 1: Write the failing tests**

```python
"""Tests for KnowledgeStore."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from urika.knowledge.models import KnowledgeEntry
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
        with patch("urika.knowledge.extractors.PdfReader") as mock_cls:
            mock_page = type("Page", (), {"extract_text": lambda self: "PDF content"})()
            mock_cls.return_value.pages = [mock_page]
            entry = store.ingest(str(pdf))
        assert entry.source_type == "pdf"
        assert "PDF content" in entry.content

    def test_ingest_url(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)
        store = KnowledgeStore(tmp_path)
        with patch("urika.knowledge.extractors.urlopen") as mock_urlopen:
            mock_resp = type("Resp", (), {
                "read": lambda self: b"<html><body>Web content</body></html>",
                "headers": type("H", (), {"get_content_charset": lambda self: "utf-8"})(),
                "__enter__": lambda self: self,
                "__exit__": lambda self, *a: False,
            })()
            mock_urlopen.return_value = mock_resp
            entry = store.ingest("https://example.com/paper", source_type="url")
        assert entry.source_type == "url"
        assert "Web content" in entry.content

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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_knowledge/test_store.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write the implementation**

`src/urika/knowledge/store.py`:

```python
"""Knowledge store — ingest, persist, and search knowledge entries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
            self._entries = [KnowledgeEntry.from_dict(e) for e in data.get("entries", [])]

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
```

**Step 4: Run tests**

Run: `pytest tests/test_knowledge/ -v`
Expected: All PASS

**Step 5: Lint and commit**

```bash
ruff check src/urika/knowledge/store.py tests/test_knowledge/test_store.py
ruff format --check src/urika/knowledge/store.py tests/test_knowledge/test_store.py
git add src/urika/knowledge/store.py tests/test_knowledge/test_store.py
git commit -m "feat: add knowledge store with ingest and search"
```

---

### Task 3: Literature Agent Role

**Files:**
- Create: `src/urika/agents/roles/literature_agent.py`
- Create: `src/urika/agents/roles/prompts/literature_agent_system.md`
- Create: `tests/test_agents/test_literature_agent_role.py`

**Step 1: Write the failing tests**

Follow the exact pattern from `tests/test_agents/test_echo_role.py`:

```python
"""Tests for the literature agent role."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole
from urika.agents.registry import AgentRegistry
from urika.agents.roles.literature_agent import get_role


class TestLiteratureAgentRole:
    def test_get_role_returns_agent_role(self) -> None:
        role = get_role()
        assert isinstance(role, AgentRole)
        assert role.name == "literature_agent"

    def test_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert isinstance(config, AgentConfig)
        assert config.name == "literature_agent"

    def test_config_has_write_and_bash_tools(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert "Read" in config.allowed_tools
        assert "Write" in config.allowed_tools
        assert "Bash" in config.allowed_tools
        assert "Glob" in config.allowed_tools
        assert "Grep" in config.allowed_tools

    def test_config_security_writable_knowledge_dir(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        knowledge_dir = tmp_path / "knowledge"
        assert any(
            d.resolve() == knowledge_dir.resolve() for d in config.security.writable_dirs
        )

    def test_config_security_bash_restricted(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert config.security.is_bash_allowed("python script.py")
        assert config.security.is_bash_allowed("pip install pypdf")
        assert not config.security.is_bash_allowed("rm -rf /")
        assert not config.security.is_bash_allowed("git push")

    def test_config_has_system_prompt(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert len(config.system_prompt) > 0
        assert str(tmp_path) in config.system_prompt

    def test_config_max_turns(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert config.max_turns == 15

    def test_discoverable_by_registry(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        assert "literature_agent" in registry.list_all()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_literature_agent_role.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write the system prompt**

`src/urika/agents/roles/prompts/literature_agent_system.md`:

```markdown
# Literature Agent

You are a research librarian on the Urika analysis platform. Your job is to ingest, index, and search relevant literature for the project.

**Project directory:** {project_dir}
**Knowledge directory:** {knowledge_dir}

## Your Responsibilities

1. Scan `{knowledge_dir}/` for PDFs, text files, and notes
2. Ingest new sources into the knowledge store
3. Search existing knowledge for relevant information
4. Summarize what you found

## Using the Knowledge Store

```python
from urika.knowledge.store import KnowledgeStore

store = KnowledgeStore(Path("{project_dir}"))

# Ingest a file
entry = store.ingest("{knowledge_dir}/paper.pdf")

# Search
results = store.search("regression")
for r in results:
    print(f"{{r.title}}: {{r.content[:200]}}")

# List all entries
for entry in store.list_all():
    print(f"{{entry.id}}: {{entry.title}} ({{entry.source_type}})")
```

## Output Format

Output a JSON block with your findings:

```json
{{
  "ingested": ["paper1.pdf", "notes.md"],
  "total_entries": 5,
  "relevant_findings": [
    {{
      "source": "paper1.pdf",
      "summary": "Describes linear regression techniques for behavioral data"
    }}
  ]
}}
```

## Constraints

- Only write files inside `{knowledge_dir}/`
- Only run Python and pip commands
- Do NOT modify project data or experiment files
```

**Step 4: Write the implementation**

`src/urika/agents/roles/literature_agent.py`:

```python
"""Literature agent — ingests and searches project knowledge."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.prompt import load_prompt

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="literature_agent",
        description="Ingests and searches project knowledge and literature",
        build_config=build_config,
    )


def build_config(project_dir: Path, **kwargs: object) -> AgentConfig:
    knowledge_dir = project_dir / "knowledge"
    return AgentConfig(
        name="literature_agent",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "literature_agent_system.md",
            variables={
                "project_dir": str(project_dir),
                "knowledge_dir": str(knowledge_dir),
            },
        ),
        allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[knowledge_dir],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=["python ", "pip "],
            blocked_bash_patterns=["rm -rf", "git push", "git reset"],
        ),
        max_turns=15,
        cwd=project_dir,
    )
```

**Step 5: Run tests**

Run: `pytest tests/test_agents/test_literature_agent_role.py -v`
Expected: 8 PASSED

**Step 6: Lint and commit**

```bash
ruff check src/urika/agents/roles/literature_agent.py tests/test_agents/test_literature_agent_role.py
ruff format --check src/urika/agents/roles/literature_agent.py tests/test_agents/test_literature_agent_role.py
git add src/urika/agents/roles/literature_agent.py src/urika/agents/roles/prompts/literature_agent_system.md tests/test_agents/test_literature_agent_role.py
git commit -m "feat: add literature agent role"
```

---

### Task 4: Public API Exports

**Files:**
- Modify: `src/urika/knowledge/__init__.py`
- Create: `tests/test_knowledge/test_public_api.py`

**Step 1: Write the failing tests**

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_knowledge/test_public_api.py -v`
Expected: FAIL — ImportError

**Step 3: Write the implementation**

Update `src/urika/knowledge/__init__.py`:

```python
"""Knowledge ingestion and search."""

from urika.knowledge.extractors import extract_pdf, extract_text, extract_url
from urika.knowledge.models import KnowledgeEntry
from urika.knowledge.store import KnowledgeStore

__all__ = [
    "KnowledgeEntry",
    "KnowledgeStore",
    "extract_pdf",
    "extract_text",
    "extract_url",
]
```

**Step 4: Run all tests**

Run: `pytest -v`
Expected: All tests pass

**Step 5: Lint and commit**

```bash
ruff check src/urika/knowledge/__init__.py
ruff format --check src/urika/knowledge/__init__.py
git add src/urika/knowledge/__init__.py tests/test_knowledge/test_public_api.py
git commit -m "feat: add knowledge package public API exports"
```
