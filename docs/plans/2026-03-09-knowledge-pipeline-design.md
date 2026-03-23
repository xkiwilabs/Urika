# Knowledge Pipeline Design

**Date**: 2026-03-09
**Status**: Approved
**Context**: Phase 12 of Urika — knowledge ingestion, search, and literature agent.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Input sources | PDFs + text files + web URLs | Covers papers, notes, and online references |
| Search method | Keyword search (case-insensitive substring) | No external deps, good enough for v1 |
| Storage | Flat JSON file at `knowledge/index.json` | Simple, grep-able, consistent with other Urika stores |
| PDF extraction | `pypdf>=4.0` | Lightweight, pure Python |
| URL extraction | `urllib.request` + basic HTML tag stripping | No new deps (stdlib) |
| Agent | Literature agent included in this phase | Pipeline + agent together |

---

## 2. Module Structure

```
src/urika/knowledge/
    __init__.py          # Public API: KnowledgeStore, KnowledgeEntry
    models.py            # KnowledgeEntry dataclass
    store.py             # KnowledgeStore: ingest, search, list, get
    extractors.py        # extract_pdf(), extract_text(), extract_url()

src/urika/agents/roles/
    literature_agent.py  # Literature agent role
    prompts/
        literature_agent_system.md
```

---

## 3. KnowledgeEntry Model

```python
@dataclass
class KnowledgeEntry:
    id: str              # "k-001", "k-002", ...
    source: str          # file path or URL
    source_type: str     # "pdf", "text", "url"
    title: str           # filename or page title
    content: str         # extracted text
    tags: list[str]      # empty by default
    added_at: str        # ISO timestamp
```

---

## 4. Extractors

| Function | Input | Returns | Raises |
|---|---|---|---|
| `extract_pdf(path: Path) -> str` | PDF file | Extracted text | `ValueError` if corrupt/empty |
| `extract_text(path: Path) -> str` | .txt/.md file | File contents | `ValueError` if empty |
| `extract_url(url: str) -> str` | HTTP(S) URL | Text with HTML tags stripped | `ValueError` if unreachable |

---

## 5. KnowledgeStore

```python
store = KnowledgeStore(project_dir)

entry = store.ingest(source="path/to/file.pdf")           # auto-detects type
entry = store.ingest(source="https://...", source_type="url")

results = store.search("keyword")     # list[KnowledgeEntry], title matches first
entries = store.list_all()
entry = store.get("k-001")
```

- Auto-generates sequential IDs (`k-001`, `k-002`, ...)
- Persists to `<project>/knowledge/index.json`
- Search: case-insensitive substring matching on title + content

---

## 6. Literature Agent

- **name**: `"literature_agent"`, max_turns: 15
- **Tools**: Read, Write, Bash, Glob, Grep
- **Security**: writable_dirs=[project_dir / "knowledge"], bash prefixes: python/pip
- **Prompt**: Research librarian role. Ingest sources from knowledge/ dir, search for relevant literature, output summary.

---

## 7. New Dependency

`pypdf>=4.0` added to `pyproject.toml` main dependencies.
