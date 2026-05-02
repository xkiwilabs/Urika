# Project Memory + Agent Instructions — Design Document

> **Status:** Design locked. Auto-capture is the default; inline `<memory>` markers in advisor + planning prompts. Phase 1 is implementation-ready once notifications + orchestrator-memory polish ship.

**Goal:** Give Urika projects a persistent memory layer that agents read at every run, so:

- Users don't have to re-supply the same instructions every experiment.
- Agents see what was discussed, decided, and tried across sessions.
- Cross-agent context (planner sees what advisor recommended; report agent sees what task agent observed) doesn't get lost.
- Long histories don't blow up context windows — they auto-summarise.

This is the project-scoped equivalent of the global Claude Code memory directory you already use (`~/.claude/projects/.../memory/`). Same shape, scaled down to one project.

---

## What's there today (gaps to close)

### Already exists
- `projectbook/advisor-history.json` — full advisor exchange log (append-only).
- `projectbook/advisor-context-summary.md` — rolling summary the advisor reads.
- `criteria.json` — versioned success criteria.
- `methods.json` — registry of methods tried.
- `progress.json` per-experiment — runs, observations, statuses.

### Gaps
- **No instruction history.** When the user passes `--instructions "focus on tree models"` to one run, that text is consumed once and forgotten. The next run's planner has no idea "tree models" was the user's preference.
- **No cross-agent memory.** Planner, task agent, evaluator each rebuild context per turn from raw files. They don't see each other's notes or decisions in any structured form.
- **Advisor history isn't summarised across all agent paths.** Per-turn end-of-loop advisor only just got context-summary injection (commit `a955c87b`). Other agents still don't.
- **No "decisions" log.** When the advisor says "let's not pursue X because Y", there's no place that records the *decision*. Only the conversation that led to it.

---

## Proposal: `<project>/memory/`

A directory with structured files mirroring CLAUDE.md's memory model, scaled to project scope.

```
<project>/memory/
├── MEMORY.md                  ← index file, ~150 chars per entry
├── user_role.md               ← who the user is, what they care about
├── feedback_<topic>.md        ← preferences captured across sessions
├── instructions_<topic>.md    ← standing instructions that apply to every run
├── decisions_<topic>.md       ← non-obvious decisions and their reasons
└── reference_<topic>.md       ← pointers to external resources
```

**Identical shape to the global Claude Code memory** — chosen deliberately so users who already understand that pattern need no new mental model.

### MEMORY.md

```markdown
# Urika Project Memory Index

## User
- [user_role.md](user_role.md) — Senior researcher, behavioral neuroscience

## Feedback
- [feedback_methods.md](feedback_methods.md) — Prefers tree-based models over deep nets
- [feedback_visuals.md](feedback_visuals.md) — Always wants confusion matrices in diagnostics

## Instructions
- [instructions_data_quality.md](instructions_data_quality.md) — Never silently impute; flag missingness
- [instructions_audience.md](instructions_audience.md) — Final report should target a paper review committee

## Decisions
- [decisions_target_definition.md](decisions_target_definition.md) — Excluded subject S012 from training

## Reference
- [ref_data_dictionary.md](ref_data_dictionary.md) — Data column definitions in the lab wiki
```

### Per-file structure

```markdown
---
name: feedback_methods
description: Prefer tree-based models (XGBoost, LightGBM) over deep nets — small N, interpretability matters
type: feedback
created: 2026-04-15
last_used: 2026-04-28
---

User has stated multiple times that for this project, tree-based methods are
the right family. Reasons given:
- N is small (~200 subjects).
- Interpretability is required for the paper.
- Deep nets would overfit and be unjustifiable in review.

**How to apply:** When the planner proposes a method, prefer XGBoost / LightGBM /
random forest over MLPs / transformers, unless the user explicitly opens that
door in this session's instructions.
```

---

## How agents read it

### At-start memory injection

Every agent that builds its prompt (planner, task agent, evaluator, advisor, report agent, etc.) reads `MEMORY.md` and includes it as a system-prompt prefix:

```
## Project Memory

The following persistent project memory shapes how you should approach this
project. Honor these preferences and decisions unless the user explicitly
overrides them in this session.

[contents of MEMORY.md and the files it references]
```

**Implementation:** A new helper in `src/urika/agents/memory.py` — `load_project_memory(project_dir) -> str` — reads `MEMORY.md`, follows links, concatenates the bodies. Cached per-call (~10ms). Each agent's `build_config` invokes it and injects into the system prompt template.

### When agents write to it

**Auto-capture is the default in v1.** Manual edit is the safety valve, not the primary write path. Most users will never open the Memory page; they'll talk to the advisor and run experiments and expect the system to learn from those interactions. Manual-only would mean memory stays empty for the 95% of users who don't curate.

This mirrors how Claude Code's own memory works — the assistant captures during conversation, the user edits if something needs correction.

#### Inline marker mechanism

Each capture-eligible agent's system prompt gains a small section instructing it to emit `<memory type="..."></memory>` blocks when it detects something durable. The orchestrator parses these out of the agent's text output, strips them from user-visible content, and writes one memory file per entry.

Example prompt section (added to advisor + planning agent prompts):

```markdown
## Project Memory Capture

When you observe one of the following, emit a structured marker. The
orchestrator strips these from the user-visible text and writes them to
the project memory. Only emit when genuinely durable — ephemeral
observations belong in your normal output, not memory.

Categories:
- <memory type="feedback">User strongly prefers X over Y because Z</memory>
- <memory type="decision">Chose to exclude subject S012 — too few trials</memory>
- <memory type="instruction">User wants every run to cross-validate by subject</memory>
- <memory type="user">User is a senior researcher in behavioral neuroscience</memory>
- <memory type="reference">Data dictionary lives in lab-wiki/data-spec.md</memory>

Don't emit memory blocks for: routine observations, single-run findings,
metrics, or anything already captured in progress.json / methods.json.
```

**Why inline markers vs a separate scribe agent:**
- No extra LLM round-trip per turn (cheaper, faster).
- Each agent knows what's memory-worthy in its own domain.
- Same pattern Claude Code uses — proven.

#### Which agents auto-capture in v1

| Agent | Captures? | Rationale |
|---|---|---|
| Advisor | ✓ Yes | Strongest source — detects user preferences, decisions, direction shifts. |
| Planning agent | ✓ Yes | Captures method-selection rationale that's worth remembering. |
| Task agent | ✗ No | Executional, low-value. |
| Evaluator | ✗ No | Scoring, not narrative. |
| Report agent | Defer | Could capture project-level decisions; revisit in v2. |

So just two agents touched in v1.

#### Manual write paths (always available)

1. **CLI:** `urika memory add <project> <topic> [--from-file PATH | --stdin]`.
2. **TUI:** `/memory add <topic>` (interactive prompt).
3. **Dashboard:** `/projects/<n>/memory` page with add/edit/delete.

These are the "I disagree with what the agent captured" / "I want to add something the agent missed" paths.

#### Per-project disable toggle

A project setting `[memory] auto_capture = true|false` (default `true`). Saved in `urika.toml`. When false, agents skip the memory-marker emission instructions in their prompts and the orchestrator ignores any markers that slip through. For users who want strict manual control.

### Auto-curation

The curator runs in the background, not as a user action. Three triggers:

1. **Threshold-based.** When `MEMORY.md` index exceeds 30 entries, OR the total injected size exceeds the **5K-token soft cap**, the curator runs at the start of the next agent invocation.
2. **Recency-based.** Entries with `last_used` older than 30 days get auto-archived to `memory/archive/<YYYY-MM>/`.
3. **Duplicate detection.** When the curator runs, it checks for entries that say substantively the same thing (semantic match decided by the curator agent itself) and merges them, preserving the freshest `last_used` and the union of supporting context.

Hard cap at **10K tokens** — past that, agents refuse to inject memory and surface a "memory budget exceeded — run curate" error.

The user never has to think about any of this. They open the Memory page only if they want to see what's been captured, edit a specific entry's wording, or delete something the agent was wrong about.

---

## Surfaces

### CLI
- `urika memory list <project>` — shows the index.
- `urika memory show <project> <topic>` — prints a memory file.
- `urika memory add <project> <topic> [--from-file PATH | --stdin]` — adds an entry.
- `urika memory delete <project> <topic>` — removes (trashes to `memory/.trash/`).
- `urika memory curate <project>` — runs the curator agent (deferred).

### TUI / REPL
- `/memory` — prints index.
- `/memory show <topic>`
- `/memory add <topic>` — prompts for content interactively.
- `/memory delete <topic>`

### Dashboard
- New sidebar entry **Memory** between Knowledge and Methods.
- `/projects/<n>/memory` — list view, add button, click-into-edit.
- Editable markdown in textarea; preview pane.

---

## Risks & open questions

### Risks
1. **Memory bloat.** Without curation, 50 sessions of feedback collect into a 100KB MEMORY.md that's injected into every agent prompt. Need a token budget.
2. **Stale memory misleading agents.** A user changes their mind and the old preference still fires. The curation phase must include "deprecate stale".
3. **Auto-capture noise.** Agent-driven memory writes add value when they catch something genuinely new and noise when they re-record obvious facts. Manual review pass needed before any entry is promoted.
4. **Cross-project leakage.** Memory is project-scoped; ensure `load_project_memory` never accidentally reads another project's memory or the global `~/.claude/.../memory/` directory.

### Decisions locked in

1. **Auto-capture is the default.** Inline `<memory type="...">` markers in advisor + planning agent prompts; orchestrator parses + strips. Per-project `auto_capture = false` toggle for users who want strict manual control.
2. **Injection point: system-prompt prefix only.** A `read_memory(topic)` tool call is a v2 consideration if context windows get tight.
3. **Token budget: 5K soft cap, 10K hard cap.** Curator auto-runs at soft cap; injection refuses past hard cap.
4. **Advisor-history stays separate from memory.** Advisor-history is the chronological transcript; memory is curated structure. They're complementary — cross-link via `last_used`.
5. **Memory ↔ `criteria.json`: don't merge, do cross-reference.** Criteria is structured machine-readable; memory is human-readable narrative.
6. **CLI/TUI/dashboard parity from day one** for add/list/delete. Curation is dashboard-only initially (longer interaction).

---

## Phased implementation

### Phase 1 — Read path + auto-capture write path (3-4 days)

- New `src/urika/core/memory.py` with:
  - `load_project_memory(project_dir) -> str` — concatenates `MEMORY.md` + linked files for system-prompt injection.
  - `parse_memory_markers(agent_text) -> list[MemoryEntry]` — extracts `<memory type="...">...</memory>` blocks.
  - `write_memory_entry(project_dir, entry)` — creates the file + updates `MEMORY.md` index.
  - `strip_memory_markers(agent_text) -> str` — removes blocks before the text reaches the user.
- Advisor + planning agent system prompts gain the `## Project Memory Capture` section (see above).
- Orchestrator post-processes each agent turn: parse markers → write entries → strip markers → emit cleaned text.
- CLI `urika memory list / show` for read-only inspection.
- Per-project `[memory] auto_capture = true|false` setting in `urika.toml`.
- Tests: loader, marker parser, end-to-end "advisor emits marker, file appears, user-visible text is clean".

This phase delivers both the read AND auto-capture paths so memory accumulates from real use immediately. Manual edit is via direct file editing until Phase 2.

### Phase 2 — Manual write surfaces (2-3 days)

- CLI `urika memory add / delete`.
- TUI `/memory` slash command (list / show / add / delete).
- Dashboard memory page: read, edit textarea, delete.
- Tests for each surface.

### Phase 3 — Curator (2-3 days)

- `memory_curator` agent role.
- `urika memory curate <project>` CLI command.
- Auto-trigger when `MEMORY.md` exceeds 30 entries OR injected size exceeds 5K tokens.
- Recency-based archive (entries with `last_used` older than 30 days move to `memory/archive/<YYYY-MM>/`).
- Duplicate detection + merge.
- Hard cap at 10K tokens — past that, agents refuse injection and surface "memory budget exceeded — run curate".

### Phase 4 — Polish (1-2 days)

- Dashboard archive viewer (browse `memory/archive/` entries).
- Per-project disable toggle UI in dashboard settings.
- Memory diff view (show what was captured this session vs prior).

**v1 = Phases 1 + 2 + 3 = ~8-10 days total.** Phase 4 is polish that can come after v1 is in real use.

---

## Recommendation

**Start with Phase 1.** This is the riskiest phase — it validates two questions at once:
1. Does memory injection actually shift agent behaviour? (try a small hand-curated memory with one feedback entry; observe whether the planner respects it)
2. Do agents reliably emit useful memory markers without flooding noise?

If both work, Phases 2 and 3 are mostly UI/agent-config work. If either fails, the design needs revisiting before more is built on top.
