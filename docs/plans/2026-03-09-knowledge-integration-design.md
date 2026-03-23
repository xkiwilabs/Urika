# Knowledge CLI & Orchestrator Integration Design

**Date**: 2026-03-09
**Status**: Approved
**Context**: Wire the knowledge pipeline into CLI commands and the orchestrator loop.

---

## 1. Knowledge CLI Commands

Three subcommands under `urika knowledge`:

### `urika knowledge ingest <project> <source>`

- `<source>` is a file path or URL
- Resolves project via `_resolve_project`, creates `KnowledgeStore(project_path)`, calls `store.ingest(source)`
- Prints: `Ingested: k-001 "filename.pdf" (pdf)`

### `urika knowledge search <project> <query>`

- Searches knowledge store by keyword (case-insensitive)
- Prints matching entries: ID, title, source type, content snippet (first 100 chars)

### `urika knowledge list <project>`

- Lists all entries in the store
- Prints: ID, title, source type

All follow existing CLI patterns — `_resolve_project`, click arguments/options, clean output.

---

## 2. Orchestrator Integration

Two integration points in `loop.py`:

### Pre-loop knowledge scan

Before the orchestrator loop starts, run the literature agent once to ingest any un-ingested files in `knowledge/`. Build a knowledge summary (titles + snippets) and prepend it to the initial task prompt so the task agent has domain context from turn 1.

### On-demand mid-loop

After the suggestion agent runs, check for `needs_literature` flag (same pattern as existing `needs_tool`). If set, run the literature agent with the suggestion context, then include new findings in the next task prompt.

### Knowledge summary helper

`build_knowledge_summary(project_dir) -> str` in `orchestrator/knowledge.py`. Loads the `KnowledgeStore` and returns a formatted string of entry titles + content snippets (truncated). Used by the pre-loop scan and injected into prompts.

---

## 3. File Changes

| Action | File | What |
|--------|------|------|
| Modify | `src/urika/cli.py` | Add `knowledge` group with `ingest`, `search`, `list` |
| Modify | `src/urika/orchestrator/loop.py` | Pre-loop literature scan + on-demand `needs_literature` |
| Create | `src/urika/orchestrator/knowledge.py` | `build_knowledge_summary()` helper |
| Modify | `tests/test_cli.py` | CLI tests for knowledge commands |
| Create | `tests/test_orchestrator/test_knowledge_integration.py` | Integration tests |

No new packages or dependencies. Pure wiring.

---

## 4. What This Does NOT Do

- No changes to agent roles or prompts
- No new core modules
- No web search integration (future)
- No vector/semantic search (future)
