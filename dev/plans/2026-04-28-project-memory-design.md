# Project Memory + Agent Instructions — Design Document

> **Status:** Design / discussion. Not ready for implementation. Open questions at the bottom — answer those before any plan-task spawn.

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

Two write paths:

1. **Explicit user gesture:**
   - CLI: `urika memory add <project> <topic> "<content>"` — drops a new file.
   - TUI: `/memory add <topic> "<content>"`.
   - Dashboard: `/projects/<n>/memory` page with simple add/edit/delete.
2. **Agent-driven capture (advanced, opt-in):**
   - When the advisor says "Recording: user prefers X", a parser detects the marker and creates the memory entry.
   - When a decision is made (e.g., advisor proposes excluding a subject and user accepts), the orchestrator creates a `decisions_*.md` entry.
   - Gate this behind a config flag — too automatic and memory bloats with low-value entries.

### Auto-summarisation

When `MEMORY.md` exceeds ~30 entries OR any single memory file exceeds ~500 lines, an agent (the **memory curator**, a new role) consolidates:
- Merges duplicate `feedback_*` entries.
- Promotes recurring observations to first-class entries.
- Archives stale instructions to `<project>/memory/archive/<date>/`.

Triggered manually via `urika memory curate <project>` or automatically every N sessions. **Not v1** — this is curation polish for a later phase.

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

### Open questions

1. **Auto-capture vs manual-only?** v1 should be **manual-only** (user/CLI/dashboard adds entries). Auto-capture is a v2 feature, gated behind a config flag.
2. **Where do agents inject memory?** System-prompt prefix only? Or also as a tool call (`read_memory(topic)`) so agents can query specific topics on demand? Recommend system-prompt prefix for v1; tool call as v2 if context windows get tight.
3. **Token budget?** Cap MEMORY.md at ~5K tokens (~3K words) when injected. Past that, the curator runs to consolidate. Hard cap at 10K tokens (~6K words).
4. **Should advisor-history be folded into memory?** Currently advisor-history is a separate concept (chronological transcript). Memory is curated/structured. They're complementary — keep separate, but cross-link via the `last_used` field in memory entries.
5. **What's the relationship to `criteria.json`?** Criteria is structured machine-readable; memory is human-readable narrative. Don't merge; do cross-reference.
6. **TUI/CLI/dashboard parity?** All three surfaces should support add/list/delete from day one. Curation is dashboard-only initially (it's a longer interaction).

---

## Phased implementation

### Phase 1 — Read-only memory (1-2 days)

- New `src/urika/core/memory.py` with `load_project_memory(project_dir) -> str`.
- Agent prompt templates updated to inject the result.
- CLI `urika memory list / show` (no add/delete yet).
- Tests for the loader and the agent prompt injection.

This phase delivers the value of "agents see persistent memory" without the write paths. Sole way to add entries is by manual file editing — but that's enough to validate the read path before building the UI.

### Phase 2 — Write paths (2-3 days)

- CLI add/delete commands.
- TUI `/memory` slash command.
- Dashboard memory page (read + edit + delete).
- Tests for each.

### Phase 3 — Curator (2-3 days, deferred)

- `memory_curator` agent role.
- `urika memory curate <project>` CLI command.
- Token budget enforcement.
- Auto-trigger heuristics.

### Phase 4 — Auto-capture (gated, 2-3 days, deferred further)

- Detection markers in advisor / planner output.
- Capture flow with user-confirm prompt.
- Per-project config to enable/disable.

**v1 = Phase 1 + Phase 2 = 3-5 days total.** Phases 3 and 4 are improvements once the basic system is in real use.

---

## Recommendation

**Start with Phase 1 only.** Validate that injection-into-prompt actually shifts agent behaviour (try a small hand-curated memory with one feedback entry; observe whether the planner respects it). If yes, proceed to Phase 2. If no, the entire premise is questioned — better to find out cheaply.

The Phase 1 → Phase 2 split also gives a natural pause-point for me to feed back to you before locking in the write-path UX.
