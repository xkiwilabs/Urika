# Knowledge Pipeline

The knowledge pipeline lets you bring domain context -- research papers, methodology notes, protocol descriptions -- into a project. Agents can search this knowledge during experiments to ground their analytical decisions in existing literature and domain expertise.


## What It Does

The knowledge pipeline:

1. **Ingests** documents from files or URLs, extracting plain text content
2. **Stores** entries in a structured index within the project directory
3. **Searches** entries by keyword, matching against titles and content
4. **Provides context** to agents, especially the literature agent and planning agent


## Supported Source Types

| Source Type | Extensions/Format | Extractor |
|-------------|-------------------|-----------|
| PDF | `.pdf` | `pypdf` -- extracts text from all pages (included in base install) |
| Text | `.txt`, `.md`, `.markdown` | Direct file read |
| URL | `http://`, `https://` | Fetches HTML, strips tags and scripts, returns plain text |

URL ingestion includes SSRF protection (blocks private/internal IP addresses) and a 10 MB response size limit.


## CLI Commands

### Ingesting documents

```bash
urika knowledge ingest <project> <source>
```

The `<source>` can be a file path or URL. The source type is auto-detected from the file extension or URL scheme:

```bash
# Ingest a PDF paper
urika knowledge ingest my-project ~/papers/smith-2024-dht-review.pdf

# Ingest a text file
urika knowledge ingest my-project notes/analysis-protocol.md

# Ingest from a URL
urika knowledge ingest my-project https://example.com/methodology-guide
```

Each ingested source gets a unique ID (e.g., `k-001`, `k-002`).

### Searching knowledge

```bash
urika knowledge search <project> <query>
```

Search is case-insensitive keyword matching. Title matches are ranked above content-only matches:

```bash
urika knowledge search my-project "regression"
urika knowledge search my-project "target selection"
```

### Listing entries

```bash
urika knowledge list <project>
```

Lists all ingested entries showing their ID, title, source type, and when they were added.


## Storage

Knowledge is stored inside the project directory under `knowledge/`:

```
my-project/
  knowledge/
    index.json      # Entry metadata and content
    papers/         # Convention for organizing PDF sources
    notes/          # Convention for organizing text notes
```

The `index.json` file contains all entries:

```json
{
  "entries": [
    {
      "id": "k-001",
      "source": "/path/to/paper.pdf",
      "source_type": "pdf",
      "title": "paper.pdf",
      "content": "... extracted text ...",
      "tags": [],
      "added_at": "2026-03-15T10:30:00+00:00"
    }
  ]
}
```

Each `KnowledgeEntry` has:

| Field | Description |
|-------|-------------|
| `id` | Sequential identifier (`k-001`, `k-002`, ...) |
| `source` | Original file path or URL |
| `source_type` | `"pdf"`, `"text"`, or `"url"` |
| `title` | Derived from filename (files) or the URL itself (URLs) |
| `content` | Full extracted text |
| `tags` | Tag list (currently empty, reserved for future use) |
| `added_at` | ISO 8601 timestamp |

The `papers/` and `notes/` subdirectories are created when the project workspace is set up. They are organizational conventions -- the actual extracted content lives in `index.json`, not in these directories.


## How Agents Use Knowledge

### Literature agent

The literature agent's primary role is searching and analyzing the knowledge store. When the planning agent or advisor agent flags that a literature search is needed, the literature agent:

1. Searches the knowledge store for relevant entries
2. Summarizes relevant findings
3. Provides domain context that other agents can use

### Context injection

During experiment loops, the orchestrator can inject knowledge context into agent prompts. When the planning agent requests literature support, relevant knowledge entries are retrieved and included as context for subsequent agent calls.

### Ingestion during project creation

When you create a project with `urika new`, the project builder agent scans the data source directory. If it finds PDF or text files alongside the data files (e.g., papers describing the dataset, methodology documents), it can automatically ingest them into the knowledge store. This means a project set up from a directory like:

```
my-data/
  participants.csv
  protocol.pdf
  analysis-notes.md
```

will have `protocol.pdf` and `analysis-notes.md` available in the knowledge store from the start, giving agents immediate access to domain context.


## KnowledgeStore API

For programmatic access:

```python
from urika.knowledge.store import KnowledgeStore

store = KnowledgeStore(project_dir)

# Ingest a source
entry = store.ingest("/path/to/paper.pdf")
entry = store.ingest("https://example.com/guide", source_type="url")

# Search
results = store.search("regression")  # Returns list[KnowledgeEntry]

# List and get
all_entries = store.list_all()
entry = store.get("k-001")
```

---

**Next:** [Models and Privacy](11-models-and-privacy.md)
