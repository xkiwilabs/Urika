# Dashboard Redesign — Design Document

**Status:** Draft for review · 2026-04-25

**Goal:** Promote the Urika dashboard from a static read-only viewer to a third primary interface (alongside CLI and TUI), with modern minimal aesthetics, multi-page navigation, editable settings, and live-streamed agent runs triggered from the browser.

**Replaces:** Phase 5 of the 2026-04-24 release-polish plan.

---

## Problem Statement

The current dashboard:
- Is **single-project only** — `urika dashboard PROJECT` is the only entry; no project picker.
- Is **read-only** — no settings editing, no agent invocation.
- Has **no live updates** — closing/reopening the page is the refresh mechanism.
- Has a **flat 1,090-line single template** — adequate for one viewer page, doesn't scale to multi-page.
- Looks **functional but amateur** per the user's own assessment — the bones (CSS variables, dark mode, Inter font) are there but typography hierarchy is flat, headers are uppercase enterprise-looking, density/spacing isn't editorial.

For a wider release, the dashboard needs to be a real third surface that casual users can rely on without ever touching a terminal beyond `urika dashboard`.

---

## User Journeys

### Journey A — casual user (no terminal beyond launch)

1. `urika dashboard` — no project arg.
2. Browser opens to **Projects list**: their projects with name, mode, experiments-count, last-touched.
3. They click a project → **Project home**: research question, recent activity, quick actions.
4. They click **Run** → an experiment starts; the page tails live output.
5. When done they click **Experiments** → **exp-001** → see the report, the slide deck, the artifacts.
6. They close the browser. The dashboard server stops on Ctrl+C in the launching terminal.

### Journey B — power user (TUI primary, browser as window)

1. `urika` launches TUI; they load `dht-target-selection`.
2. They type `/dashboard` in the TUI.
3. TUI starts a dashboard server in a background thread, opens the browser **directly to the project view** (not the projects list).
4. They run experiments in the TUI; the browser shows the same lockfile-detected state and tails the same log file.
5. They click **Settings** in the browser to edit a description; the TUI sees the file change on next read.
6. Closing the TUI shuts down the dashboard server.

### Journey C — power user (CLI direct)

1. `urika dashboard <project>` opens directly to that project view.
2. `urika dashboard` opens to the projects list.
3. Background experiments started elsewhere (TUI, another `urika run`) appear as "running" because the dashboard reads lockfiles and progress.json from the filesystem.

---

## Architecture

### Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **HTTP server** | FastAPI + Uvicorn | Async-native, SSE built in via `StreamingResponse`, write endpoints clean, Jinja2 integration first-class. Drop-in for `BaseHTTPRequestHandler` use case. |
| **Templates** | Jinja2 | FastAPI's default. No build step. Real `{% extends %}` template inheritance. |
| **Frontend interactivity** | HTMX + Alpine.js | Both via single CDN script tags. HTMX swaps server-rendered HTML fragments; Alpine handles the few client-only things (theme toggle, dropdown menus). No Node, no TS, no build pipeline. |
| **Styling** | Hand-written CSS in `static/app.css` | Modern minimal aesthetic — full control. CSS custom properties, no framework. |
| **Run orchestration** | Subprocess + SSE | Dashboard spawns `urika run PROJECT` as a child; pipes stdout to a `run.log` file; SSE endpoint tails the file to the browser. |

**Packaging:** FastAPI + Uvicorn + Jinja2 added to base `dependencies` in `pyproject.toml` (~12MB extra). Dashboard becomes first-class on `pip install urika`. Templates and `static/` ship inside the wheel via Hatchling's existing template-bundling pattern (already used for reveal.js).

### Coordination model

The three surfaces (CLI, TUI, dashboard) **never talk to each other directly**. They coordinate through the filesystem:

- **Lockfile** at `<project>/experiments/<exp>/.lock` — PID of the owning process. Already exists; cmd_run already detects stale vs live locks.
- **`progress.json`** in each experiment dir — append-only run log. Already exists.
- **`run.log`** (NEW) — line-buffered stdout/stderr from the run subprocess, written by whoever started the run. The dashboard tails this for live streaming.
- **`urika.toml` / `runtime.toml`** — settings. Edits from any surface are atomic file writes; other surfaces re-read on next access (no cache invalidation needed because they read fresh each time already).

**This means a TUI run and a browser run look identical to anyone watching the project directory.** Cross-session awareness is free.

### Subprocess ownership

The dashboard server, when started, owns any run subprocesses it spawns. PID is written to the lockfile. If the dashboard server itself dies, the subprocess survives but the lockfile becomes stale; next surface to look at the project (TUI, another dashboard, CLI) will detect the stale lock and offer to clean up.

When the TUI launches its own dashboard via `/dashboard`, the dashboard server lives in a background thread of the TUI process; closing the TUI stops the dashboard. Standalone `urika dashboard` server lives until Ctrl+C.

### Streaming

Server-Sent Events (SSE), one-way, browser → server pulls. `text/event-stream` is supported by every modern browser without a library. SSE messages are simple `data: <line>\n\n` framed strings.

```
GET /api/runs/<exp_id>/stream → SSE
  - server tails run.log file (uses watchdog or polling at 0.5s)
  - emits "data: <line>\n\n" for each new line
  - emits "event: status\ndata: {"status":"completed"}\n\n" on lockfile removal
  - browser EventSource appends each line to a <pre> log viewer
```

If interactive prompts (click.prompt) are needed inside a run later, we upgrade that one path to WebSocket. For 0.2.x: SSE only, runs that use click.prompt get the same fallback they get under non-TTY today (use defaults / fail loudly).

---

## Page Map

```
/                              Projects list (or project home if last-used set)
/projects                      Projects list (explicit)
/settings                      Global settings (theme, default privacy, default endpoints)
/projects/<name>               Project home
/projects/<name>/settings      Project settings (description, question, mode, criteria, audience)
/projects/<name>/experiments   Experiment list
/projects/<name>/experiments/<exp_id>          Experiment detail (runs, methods, metrics)
/projects/<name>/experiments/<exp_id>/log      Live log tailing
/projects/<name>/experiments/<exp_id>/report   Rendered report.md
/projects/<name>/experiments/<exp_id>/presentation  Embedded reveal.js
/projects/<name>/methods                       Project-wide method registry
/projects/<name>/knowledge                     Knowledge base browser
/projects/<name>/run                           Run launcher (form + live log)
/projects/<name>/finalize                      Finalize launcher
/projects/<name>/files/<path>                  Raw file viewer (markdown / code / images)
```

API routes under `/api/`:

```
GET  /api/projects                                List all projects + summary
GET  /api/projects/<name>                        Project metadata + experiments index
GET  /api/projects/<name>/tree                   Filesystem tree (current /api/tree)
GET  /api/projects/<name>/file?path=...          Raw file (current /api/file)
GET  /api/projects/<name>/methods                Methods (current /api/methods)
GET  /api/projects/<name>/criteria               Criteria (current /api/criteria)
GET  /api/projects/<name>/stats                  Stats (current /api/stats)
PUT  /api/projects/<name>/settings               Update description/question/mode (versioned via revisions.json)
POST /api/projects/<name>/run                    Start a run; returns experiment_id
POST /api/projects/<name>/finalize               Start finalize
POST /api/projects/<name>/advisor                Run advisor with a question; returns response
GET  /api/runs/<exp_id>/stream                   SSE log stream
POST /api/runs/<exp_id>/stop                     Sets stop flag (existing pause_controller mechanism)
GET  /api/settings                               Global settings
PUT  /api/settings                               Update global settings
```

---

## Visual Design

**Aesthetic target:** Linear / Vercel docs / Stripe docs lineage — generous whitespace, clear typography hierarchy, restrained color, system fonts where possible, dark mode parity.

**Specific choices:**

- **Color palette:** grayscale (8 shades) + one accent (project's existing `#2563eb` blue) + semantic (red for errors, green for success). No more than 12 total colors across light + dark themes.
- **Typography:** Inter for UI, JetBrains Mono for code/logs. Clear scale: 13px small text → 14px body → 16px subheading → 20px section header → 28px page title. Weights: 400 / 500 / 600 only.
- **Spacing scale:** 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 px — derived from a single `--space-unit: 4px`.
- **Drop the uppercase-tracking section labels** in the sidebar — replaced with Title Case and a subtle leading icon (one SVG glyph per section).
- **Layout:** persistent left sidebar (240px, collapsible), top breadcrumb, content area maxes at ~1100px and centers on wider screens. No fixed-width sidebar items truncating ellipses — let things breathe.
- **Component vocabulary** (≤7 base components):
  - `card` — content containers with subtle border, radius 8px, shadow only on hover for interactive ones
  - `button` — primary / secondary / ghost variants
  - `list-item` — for tree nav, experiment lists, methods
  - `breadcrumb` — page navigation
  - `tag` — status chips (running / completed / paused / failed)
  - `metric` — large stat display for headline numbers
  - `log-line` — terminal-output line renderer with subtle agent-color accents
- **Mobile:** sidebar becomes drawer (Alpine `x-data` toggle). Content reflows. Not a primary target, but shouldn't be broken.
- **Empty states:** every list page shows a real empty-state with a hint of what to do next, not a blank panel.
- **Loading states:** skeleton loaders (CSS-only) for data fetches >200ms.

---

## Settings Editing

Two scopes:

- **Global** at `/settings` — theme, default privacy mode, default endpoints (the same data `urika config` and `urika notifications` edit). Backed by `~/.urika/settings.toml`.
- **Project** at `/projects/<name>/settings` — description, question, mode, audience, criteria preview/edit, notification channels, max-turns default. Backed by `<project>/urika.toml`. Edits go through the existing `core/revisions.update_project_field` so versions are preserved.

Form pattern: pure HTML forms, HTMX submits via `hx-put`, server returns the updated card fragment. Validation errors return as inline messages. Unsaved-changes detection (Alpine `x-data` form-state).

**Atomicity:** all writes use the existing `core/report_writer.write_versioned` (same as presentations and report.md) — atomic write to `<file>.tmp`, fsync, rename. No partial writes possible.

---

## Agent Invocation from the Browser

The "Run" page is the most novel surface. It looks like:

```
┌─ Run experiment ─────────────────────────────────────────┐
│                                                          │
│  Experiment name:   [exp-002-gradient-boost            ] │
│  Hypothesis:        [..........................        ] │
│  Max turns:         [   5 ▼]                             │
│  Audience:          [standard ▼]                         │
│  Mode:              [(•) single  ( ) meta  ( ) auto    ] │
│  Instructions:      [..........................        ] │
│                                                          │
│  [Cancel]                            [Start run ──→]    │
└──────────────────────────────────────────────────────────┘
```

When **Start run** is clicked:

1. POST `/api/projects/<name>/run` with the form.
2. Backend creates the experiment record, spawns `urika run PROJECT --experiment <id> --json [other flags]` as a subprocess, captures stdout to `<exp>/run.log`, writes PID to lockfile.
3. Returns `{"experiment_id": "..."}` — browser redirects to `/projects/<name>/experiments/<id>/log`.
4. Log page opens an SSE connection to `/api/runs/<id>/stream` and tails live.
5. While running, "Stop" button sends POST to `/api/runs/<id>/stop` which sets the existing pause_requested flag.
6. When the lockfile is removed (run ended), the SSE stream emits a status event; the browser shows "Completed" and surfaces links to report / presentation / methods.

**Concurrency:** if a run is already active for the project (lockfile present + PID alive), the Run page shows "an experiment is already running — view live →" instead of the form.

**Same flow, condensed forms,** for `/finalize`, `/advisor`, `/present`, `/build-tool`, `/evaluate`, `/plan`. Each maps to one of the existing CLI commands invoked as a subprocess. None of these need the dashboard to reimplement their logic.

---

## Backwards Compatibility

- **The current `BaseHTTPRequestHandler`-based dashboard is replaced wholesale.** No callers depend on its specific interface; it's a process boundary.
- **The current `urika dashboard PROJECT` CLI command** keeps the same flags but now also accepts no project arg (opens to projects list).
- **The current `dashboard.html` single-template** retires. The new templates live under `src/urika/dashboard/templates/`.
- **The current `/api/tree` / `/api/file` / `/api/raw` / `/api/stats` / `/api/methods` / `/api/criteria` endpoints** become `/api/projects/<name>/tree` etc. The data contracts stay; only the URL prefix changes. There are no external consumers of these — only the dashboard's own JS — so this isn't a breaking change for users.

---

## Security

The localhost + path-traversal-check + no-auth model from the current dashboard stays:

- Server binds to `127.0.0.1` only.
- Every file path served goes through `is_relative_to(<project_root>)`.
- Optional `--auth-token` for users tunneling the dashboard remotely (Phase 5.3 in the original plan, now part of this redesign).
- POST/PUT endpoints check the same auth token if set.
- The new "Run" surface is the most sensitive: it triggers Python subprocesses with the user's permissions. Documented loudly in `docs/18-security.md`. Constrained to `urika ` CLI invocations only; the form doesn't accept arbitrary command strings.

---

## Out of Scope (for this redesign)

- **Real-time multi-user collaboration.** Localhost, single user, full stop.
- **Authentication beyond a bearer token.** No user accounts, no sessions, no roles.
- **Rich-text WYSIWYG editing of markdown reports.** Edit-in-browser is for *settings* (structured fields). Reports stay markdown-source-of-truth, edited in your editor of choice.
- **Mobile-first design.** Phone usage is a happy accident; desktop is the target.
- **Dark mode auto-switching by OS preference.** Manual toggle only, persisted in localStorage.
- **Telemetry / usage analytics from the browser.** None.
- **Browser-based agent chat (orchestrator chat).** Stays a TUI feature for v0.2; can come later if there's demand.

---

## Estimated Scope

**Backend rewrite + page scaffold:** ~2 days
**Modern visual style + 7-component CSS library:** ~1.5 days
**Page implementations (projects list, project home, experiment detail, log tail, settings):** ~2.5 days
**Run/finalize/advisor invocation + SSE + lockfile coordination:** ~1.5 days
**Polish, dark mode parity, empty/loading states, edge cases:** ~1 day
**Tests + docs + smoke:** ~1 day

**Total: ~9–10 working days.** Substantially bigger than the original Phase 5's 3 tasks. Justifies its own implementation plan.

---

## Open Questions for the User

1. **Branding / logo** — keep the current "Urika" wordmark in blue, or evolve it? (I'd say keep it; that's the project's identity.)
2. **Auto-launch dashboard on `urika new`** — after a project is created interactively, should we offer "open dashboard now?" so new users see the polished view immediately? (Probably yes.)
3. **Persist last-opened project** — when `urika dashboard` is run with no args and there's a single project that was opened most recently, should it open directly to that project, or always show the projects list? (I'd default to projects list for predictability; power users can `urika dashboard PROJECT` directly.)
4. **Dashboard process lifecycle when launched from TUI** — agreed earlier: tied to the TUI session. Confirming.

---

## Approval

This document needs your sign-off before I write the implementation plan. Once approved:

1. I save this design to `dev/plans/2026-04-25-dashboard-redesign-design.md` (this file).
2. I invoke the writing-plans skill to produce `dev/plans/2026-04-25-dashboard-redesign.md` — a task-by-task breakdown along this design's seams.
3. Phase 5 of `2026-04-24-release-polish.md` becomes a single task that points at the new plan ("see dashboard-redesign plan").

Specifically I need confirmation on:

- **Stack:** FastAPI + Uvicorn + Jinja2 + HTMX + Alpine.js, hand-written CSS, no build step
- **Packaging:** all-in (web deps in base `dependencies`, ~12MB)
- **Run model:** dashboard owns subprocesses; TUI's `/dashboard` launches an in-thread server tied to the TUI session
- **Streaming:** SSE only (WebSocket deferred)
- **Settings editing:** in-browser forms for global + project; reports stay markdown-source
- **Aesthetic:** modern-minimal Linear/Vercel/Stripe-docs lineage; ≤7 base components

Sound right?
