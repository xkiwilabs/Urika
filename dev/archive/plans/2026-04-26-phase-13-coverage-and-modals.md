# Phase 13 — Coverage & Modal Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the remaining gaps between the dashboard and the CLI/TUI surfaces. Every CLI command that takes user input now has a dashboard modal exposing every relevant flag; every "produces an artifact" command gets a "Re-run X" label when the artifact exists; usage/data inspection get dedicated pages. The dashboard becomes a complete remote-launch UI for the CLI subprocess fleet.

**Architecture:** Each new modal posts to a new (or existing) `/api/...` endpoint that spawns the matching `urika <cmd>` CLI subprocess with all form values forwarded as flags. SSE log streaming reuses the existing run-log infrastructure. Data inspection page reads via `urika.data.loader`. Usage page reads `usage.json` + per-experiment progress.

**Tech Stack:** No new server-side deps. New CDN script for charts: `Chart.js` (via unpkg, defer-loaded). All new templates reuse existing modal/tabs/list-item primitives.

**Replaces nothing.** Pure additions on top of the Phase 1–12 stack. Removes the "Phase 13 backlog" items recorded earlier.

**Decisions** (confirmed with user):

- `plan` is **NOT** added to the dashboard — it runs automatically inside `urika run`'s orchestrator loop every turn; the standalone `urika plan` command is a debug/preview tool with no actionable dashboard surface.
- Distributed agent buttons, NOT a unified "Agents hub" — each agent's modal lives where the context it operates on already lives.
- "Re-run X" labels when artifacts exist (mirroring the existing "Re-finalize project" pattern).
- Modal submits spawn the CLI subprocess with full flag forwarding; HTMX HX-Redirect navigates to the live-log page for long-running agents.
- Chart.js via CDN for the usage page (matches the HTMX/Alpine no-build aesthetic).

**Estimated total:** ~18 tasks across 6 phases.

---

## Phase 13A — Run / New Project / Finalize modal expansion

### Task 13A.1: Run-modal expanded options

**Files:**
- Modify: `src/urika/dashboard/templates/experiments.html` (the New Experiment modal)
- Modify: `src/urika/dashboard/runs.py` `spawn_experiment_run` — accept `auto`, `max_experiments`, `review_criteria`, `resume` kwargs.
- Modify: `src/urika/dashboard/routers/api.py` `api_project_run_post` — read those fields, validate, forward.
- Test: extend `test_api_run.py` to assert the new flags reach `spawn_experiment_run`.

Modal expands with an "Advanced" collapsible (Alpine `x-show`) containing:
- `<input type="checkbox" name="auto">` Run autonomously
- `<input type="number" name="max_experiments" min="1">` Max experiments (only when `auto`)
- `<input type="checkbox" name="review_criteria">` Review success criteria after each experiment
- `<input type="checkbox" name="resume">` Resume an interrupted run

Server-side validation: `max_experiments` requires `auto` to be true.

**Commit:**
```
feat(dashboard): run modal exposes --auto / --max-experiments / --review-criteria / --resume

The New Experiment modal grows an "Advanced" section with the
flags currently CLI-only. spawn_experiment_run forwards each to
the urika run subprocess.
```

---

### Task 13A.2: Finalize modal expanded options

**Files:**
- Modify: `src/urika/dashboard/templates/project_home.html` (the Finalize button area)
- Modify: `src/urika/dashboard/routers/api.py` `api_project_finalize` — read `instructions`, `audience`, `draft` form fields and forward.
- Modify: `src/urika/dashboard/runs.py` `spawn_finalize` — accept `draft` kwarg.

The current button posts directly. Convert to modal:
- `<textarea name="instructions">`
- `<select name="audience">` with novice/standard/expert
- `<input type="checkbox" name="draft">` Draft mode (writes to `projectbook/draft/`, doesn't overwrite final outputs)

Re-finalize label is already in place (Phase 10D); the modal opens the same way.

**Commit:**
```
feat(dashboard): finalize modal exposes --instructions / --audience / --draft

Finalize button on project home now opens a modal mirroring the
CLI's full flag surface. Draft mode writes to projectbook/draft/
without overwriting the final outputs.
```

---

### Task 13A.3: New Project modal — instructions field

**Files:**
- Modify: `src/urika/dashboard/templates/projects_list.html` (the New project modal)
- Modify: `src/urika/dashboard/routers/api.py` `api_create_project` — accept `instructions` field; persist it (somewhere — TBD, probably `<project>/.urika/builder_instructions.txt` or just stash for the future builder-agent invocation).

Add `<textarea name="instructions">` capturing user steering for the project_builder agent (which Phase 11C deferred but will eventually run). For now: just persist the instructions text so it's not lost when the builder integration lands.

**Commit:**
```
feat(dashboard): new project modal exposes builder instructions

User can supply free-text instructions when creating a project
via the dashboard. The text is persisted to
<project>/.urika/builder_instructions.txt for the future
project_builder agent invocation (Phase 14+); the modal surface
is in place now so the input never gets dropped.
```

---

## Phase 13B — Experiment-detail agent modals

### Task 13B.1: Evaluate button + modal

**Files:**
- Modify: `src/urika/dashboard/templates/experiment_detail.html` (Outputs section gets new Evaluation row)
- Modify: `src/urika/dashboard/routers/api.py` — add `POST /api/projects/{name}/experiments/{exp_id}/evaluate`
- Modify: `src/urika/dashboard/runs.py` — add `spawn_evaluate(project_name, project_path, experiment_id, instructions, audience) -> int`
- Test: `tests/test_dashboard/test_api_evaluate.py`

Modal:
- `<textarea name="instructions">`
- `<select name="audience">`

Server spawns: `urika evaluate <project> <experiment_id> [--instructions ...] [--audience ...] --json`

Re-evaluate label when `<exp>/evaluation.md` (or whatever evaluator outputs — confirm by reading `urika.cli.agents` evaluate command) exists.

**Commit:**
```
feat(dashboard): per-experiment evaluate button + modal

Experiment detail page gets an Evaluate / Re-evaluate button
that opens a modal with instructions + audience inputs. Spawns
urika evaluate with the form values as flags. Re-run label when
the evaluator output exists.
```

---

### Task 13B.2: Generate report modal expansion

**Files:**
- Modify: `src/urika/dashboard/templates/experiment_detail.html` (Report row in Outputs section)
- Modify: `src/urika/dashboard/routers/api.py` — extend the existing report-generation flow OR (if no dedicated endpoint exists) add `POST /api/projects/{name}/experiments/{exp_id}/report` spawning `urika report`.

Investigate first: does `urika report` exist as a CLI command? If yes, mirror its flags (instructions, audience). If no, the report is generated as part of finalize — note that and skip this task (already covered).

If yes, modal:
- `<textarea name="instructions">`
- `<select name="audience">`

Re-generate label when `<exp>/report.md` exists.

**Commit:**
```
feat(dashboard): per-experiment report modal exposes instructions + audience

Generate / Re-generate report button on experiment detail now
opens a modal with the CLI's --instructions and --audience
flags. Re-run label when the report file exists.
```

---

### Task 13B.3: Generate presentation modal expansion

**Files:**
- Modify: `src/urika/dashboard/templates/experiment_detail.html` (Presentation row)
- Modify: `src/urika/dashboard/routers/api.py` `api_project_present` — already accepts experiment_id; expose instructions + audience form fields and forward.
- Modify: `src/urika/dashboard/runs.py` `spawn_present` — accept `instructions`, `audience` kwargs.

Modal:
- `<textarea name="instructions">`
- `<select name="audience">`

Re-generate label when `<exp>/presentation.html` (or `presentation/index.html`) exists.

**Commit:**
```
feat(dashboard): per-experiment presentation modal exposes instructions + audience

Generate / Re-generate presentation now opens a modal with the
CLI's --instructions and --audience flags forwarded to urika present.
```

---

## Phase 13C — Project-home agent modals

### Task 13C.1: Summarize button + modal

**Files:**
- Modify: `src/urika/dashboard/templates/project_home.html` (Project actions section)
- Modify: `src/urika/dashboard/routers/api.py` — `POST /api/projects/{name}/summarize`
- Modify: `src/urika/dashboard/runs.py` — add `spawn_summarize(project_name, project_path, instructions) -> int`
- Test: `tests/test_dashboard/test_api_summarize.py`

Investigate first: does `urika summarize` exist? Yes, per the CLI list. Read what it does and what flags it takes.

Modal:
- `<textarea name="instructions">`

Output likely lands in `projectbook/summary.md` (verify). Re-run label when it exists.

**Commit:**
```
feat(dashboard): project home — Summarize / Re-summarize button + modal

Spawns urika summarize <project> with optional instructions.
Re-run label appears when projectbook/summary.md exists.
```

---

## Phase 13D — Tools page: build-tool modal

### Task 13D.1: + Build tool button + modal

**Files:**
- Modify: `src/urika/dashboard/templates/tools.html` (project Tools page — only shows when scope=project)
- Modify: `src/urika/dashboard/routers/api.py` — `POST /api/projects/{name}/build-tool`
- Modify: `src/urika/dashboard/runs.py` — `spawn_build_tool`

Investigate first: `urika build-tool` CLI signature (`src/urika/cli/agents.py`). What does it require?

Likely modal:
- `<input type="text" name="name">` Tool name
- `<textarea name="description">` What the tool should do
- `<textarea name="instructions">` Additional steering

Spawns: `urika build-tool <project> --name <name> --description <description> [--instructions ...] --json`

**Commit:**
```
feat(dashboard): + Build tool button on project Tools page

Modal collects tool name + description + optional instructions,
spawns urika build-tool. New custom tool appears in the project
Tools list when generation completes.
```

---

## Phase 13E — Data inspection page

### Task 13E.1: New /projects/<n>/data page

**Files:**
- Create: `src/urika/dashboard/routers/pages.py` — add `project_data` route
- Create: `src/urika/dashboard/templates/data.html`
- Modify: `src/urika/dashboard/templates/_sidebar.html` — add "Data" link to project nav (between Methods and Tools, or wherever fits)
- Test: `tests/test_dashboard/test_pages_data.py`

Page shows:
- File picker (dropdown of detected data files in `<project>/data/` + `[project].data_paths`).
- Selected file's schema as a table: column name | dtype | missing % | unique values.
- Preview: first 10 rows in a scrollable data grid.

Reuse `urika.data.loader.load_dataset` to load. For the schema/missing/preview computation, call `pandas.DataFrame.dtypes`, `df.isna().mean()`, `df.head(10)` etc. — already what `urika inspect` does.

If no data file exists, empty state with a link to project Settings / Data tab.

**Commit:**
```
feat(dashboard): /projects/<n>/data — schema + missing + preview

Reads the project's configured data files (project.data_paths +
data/ directory) via urika.data.loader. Shows schema as a table
(column / dtype / missing % / unique count) and a preview of
the first 10 rows. File picker when multiple files exist.

Mirrors the urika inspect CLI command but with a real grid
instead of text output.
```

---

## Phase 13F — Usage page with Chart.js

### Task 13F.1: New /projects/<n>/usage page

**Files:**
- Create: `src/urika/dashboard/routers/pages.py` — `project_usage` route
- Create: `src/urika/dashboard/templates/usage.html`
- Modify: `src/urika/dashboard/templates/_base.html` — add Chart.js CDN script (defer-loaded, after Alpine)
- Modify: `src/urika/dashboard/templates/_sidebar.html` — add "Usage" link
- Test: `tests/test_dashboard/test_pages_usage.py`

Page shows charts:
1. **Tokens over time** — line chart, x=time, y=tokens, series=agent role.
2. **Cost over time** — line chart, x=time, y=USD.
3. **Per-experiment breakdown** — bar chart, x=experiment_id, y=tokens (with cost as label).
4. **Per-agent breakdown** — bar chart, x=agent role, y=tokens.

Source data: read `<project>/usage.json` (verify its shape) and aggregate `<project>/experiments/*/progress.json` for per-experiment usage.

If no usage data yet, empty state.

Chart.js loaded via CDN (`<script src="https://cdn.jsdelivr.net/npm/chart.js" defer></script>`). One `<canvas>` per chart, plus a small inline script that initializes them on page load with the JSON data embedded as `<script type="application/json" id="usage-data">...</script>`.

**Commit:**
```
feat(dashboard): /projects/<n>/usage — token/cost/agent charts

New page with four Chart.js charts: tokens over time by agent,
cost over time, per-experiment tokens (bar), per-agent tokens
(bar). Source: usage.json + per-experiment progress.json.
Empty state when no usage data has accumulated yet.

Chart.js loaded via CDN — matches the HTMX/Alpine no-build
aesthetic; no JS bundler introduced.
```

---

## Phase 13G — Polish + tests

### Task 13G.1: Re-run label helpers

**Files:**
- Modify: `src/urika/dashboard/templates/_macros.html` — add a `{% macro action_button(label_run, label_rerun, exists, ...) %}` that picks the right label based on whether the artifact file exists.

Apply to: Finalize, Summarize, Report, Present, Evaluate. Centralizes the existing logic so changes propagate.

**Commit:**
```
refactor(dashboard): centralize Run/Re-run label logic in a macro
```

---

### Task 13G.2: Update sidebar nav order

**Files:**
- Modify: `src/urika/dashboard/templates/_sidebar.html`

Project section after this phase has these links:
1. Home
2. Experiments
3. Methods
4. Tools
5. **Data** (new)
6. Knowledge
7. Advisor
8. **Usage** (new — bottom-ish, near settings)
9. Settings

**Commit:**
```
refactor(dashboard): sidebar order with Data + Usage links
```

---

### Task 13G.3: Update docs/19-dashboard.md

**Files:**
- Modify: `docs/19-dashboard.md`

Add Phase 13 sections:
- New buttons: Evaluate, Summarize, Build tool.
- Modal expansions: New Project (instructions), New Experiment (advanced flags), Finalize (draft), Report/Present (instructions+audience).
- New pages: /data, /usage.
- Coverage map updated: previously-deferred CLI commands now have surfaces.

**Commit:**
```
docs(dashboard): Phase 13 additions
```

---

### Task 13G.4: Final smoke checklist

**Files:**
- Create: `dev/plans/2026-04-26-phase-13-smoke.md`

Manual browser checklist:

- [ ] New Project modal: instructions field present, captured, persisted.
- [ ] New Experiment modal: Advanced section reveals --auto / --max-experiments / --review-criteria / --resume; values forwarded.
- [ ] Finalize modal: instructions + audience + draft fields; --draft writes to projectbook/draft/.
- [ ] Experiment detail Evaluate button: opens modal, runs, label changes to Re-evaluate after success.
- [ ] Experiment detail report/presentation buttons: modal + flags forwarded.
- [ ] Project home Summarize button: same pattern.
- [ ] Tools page + Build tool button: spawns build-tool, new tool appears.
- [ ] /data page: schema + missing % + preview; file picker switches files.
- [ ] /usage page: four charts populated, no console errors, empty state if no usage.
- [ ] All Re-run labels appear when expected; revert to Run when artifact removed.

Plus pytest count + live-server probe.

**Commit:**
```
docs(plan): Phase 13 smoke checklist
```

---

## Execution notes

- **Investigate before each agent-spawn task.** For evaluate / report / summarize / build-tool, read the CLI source first to confirm flag signatures and output paths. Don't guess — the modal field set must match the CLI.
- **Charts library**: Chart.js is the only new dependency. CDN loaded `defer` after Alpine. Don't bundle.
- **Re-run labels**: centralized macro after the first three or four uses prove the pattern. Don't refactor speculatively.
- **Tests**: every spawn endpoint gets a stub-spawn test; every page gets a 200 + content test + 404 unknown-project test.
- **Skills to invoke during execution:**
  - @superpowers:test-driven-development on every code task
  - @superpowers:verification-before-completion before marking complete
- **Stop conditions:** if any CLI command's actual signature doesn't match this plan (e.g. `urika summarize` doesn't exist or takes different flags), STOP that task and report — the plan needs an update.

## Future work (post-Phase 13)

- **SSE token streaming for advisor** — replace single POST with EventSource for real-time progress visibility.
- **Project_builder integration in New Project modal** — currently deferred. The instructions textarea is captured but the builder agent isn't invoked from the dashboard yet.
- **Mid-run interactive prompt UI** — Phase 11F shipped the SSE-side; orchestrator-side `URIKA-PROMPT:` emission is pending.
- **`plan` standalone surface** — if a real workflow emerges that needs it, add a "Preview next plan" button on experiment detail.
