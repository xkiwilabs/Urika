# Dashboard

Urika ships a browser-based dashboard alongside the CLI and the TUI. It is the third primary interface for interacting with projects: read-only inspection, settings editing, and launching new runs all happen through server-rendered pages and HTMX-driven forms.

The dashboard reads and writes the same on-disk project files as the CLI and TUI, so the three surfaces stay in sync without any explicit message bus.


## Launching

Three entry points all start the same FastAPI app:

```bash
urika dashboard                  # opens /projects (registry list)
urika dashboard my-project       # opens /projects/my-project (project home)
```

From inside the TUI:

```
urika:my-project> /dashboard
```

The slash command starts a daemon-thread server on a free port and opens the browser at the project home page. `/dashboard stop` shuts running dashboards down. See [Interactive TUI](16-interactive-tui.md#slash-commands) for the full list of TUI commands.

By default the server binds `127.0.0.1` and picks a random free port. Override with `--port`:

```bash
urika dashboard --port 8765
```


## Pages

The dashboard is a multi-page app. Each route is a server-rendered Jinja template; HTMX is used for in-place updates, Alpine.js for small reactive pieces (like the theme toggle).

| Route | Description |
|-------|-------------|
| `/projects` | Registered projects with mode, question, recent activity. |
| `/projects/<name>` | Project home: summary card, recent experiments, final outputs. |
| `/projects/<name>/experiments` | All experiments for the project, with status and run counts. |
| `/projects/<name>/experiments/<id>` | Experiment detail: hypotheses, runs, report/presentation viewers, files. |
| `/projects/<name>/experiments/<id>/report` | Rendered experiment report (`report.md` → HTML). |
| `/projects/<name>/experiments/<id>/presentation` | Rendered experiment presentation (reveal.js). |
| `/projects/<name>/experiments/<id>/files/<path>` | Single experiment artifact viewer (text, image, or download). |
| `/projects/<name>/methods` | Project methods registry sorted by metric (client-side sortable table). |
| `/projects/<name>/findings` | Project findings: title, summary, metrics table (formatted, not JSON). |
| `/projects/<name>/report` | Project-level report (`projectbook/report.md` → HTML). |
| `/projects/<name>/presentation` | Project-level presentation (reveal.js). |
| `/projects/<name>/knowledge` | Knowledge base entries for the project, with an "+ Add knowledge" button (see below). |
| `/projects/<name>/knowledge/<id>` | A single knowledge entry. |
| `/projects/<name>/tools` | Registered tools listing (read-only viewer for the project tool registry). |
| `/projects/<name>/criteria` | Versioned success-criteria viewer (read-only). |
| `/projects/<name>/advisor` | Advisor chat panel — persistent transcript per project (see below). |
| `/projects/<name>/data` | Data sources registered for the project (Phase 13). |
| `/projects/<name>/data/inspect?path=...` | Schema, missing counts, head/tail preview for one file (Phase 13). |
| `/projects/<name>/usage` | Token / cost time-series charts and recent sessions table (Phase 13). |
| `/projects/<name>/projectbook/summary` | Rendered `projectbook/summary.md` from the summarizer agent (Phase 13). |
| `/projects/<name>/finalize/log` | Finalize log page: streams the running finalize subprocess via SSE. |
| `/projects/<name>/summarize/log` | Summarize log page: streams the running summarize subprocess via SSE (Phase 13). |
| `/projects/<name>/tools/build/log` | Build-tool log page: streams the running tool-builder subprocess via SSE (Phase 13). |
| `/projects/<name>/experiments/<id>/log` | Live log streaming via SSE (see below). |
| `/projects/<name>/settings` | Project settings (tabbed: basics / data / models / privacy / notifications). |
| `/settings` | Global defaults (tabbed: privacy / models / preferences / notifications). |
| `/healthz` | Liveness probe. Always returns `{"status":"ok"}`. |

The legacy `/projects/<name>/run` page was removed in Phase 11 — run launching now lives behind the **+ New experiment** modal on the experiments list (see [Modals](#modals-new-project--new-experiment) below).

`/` redirects to `/projects`.


## Modals: New Project + New Experiment

Phase 11 replaced the standalone `/run` page (and the missing `/new` page) with two modal dialogs that open in-place from the relevant list pages. Both share the same `modal()` Jinja primitive — a small accessible dialog with a backdrop, an Alpine `x-data` toggle, and a labelled close button.

- **+ New project** lives in the top-right of `/projects`. It opens a modal with the same questions the interactive `urika new` CLI asks: project name, dataset path, research question, mode, audience. Submitting POSTs to `POST /api/projects` (see below), which runs `urika new --json --non-interactive` as a subprocess and, on success, redirects the browser to the new project's home page.
- **+ New experiment** lives in the top-right of `/projects/<name>/experiments`. The modal carries forward the fields from the old `/run` form — experiment name, hypothesis, mode, audience, max turns, and additional instructions — and posts to `POST /api/projects/<name>/run`. On success the response is an HTMX redirect to the live log page.

If an experiment is already running (a `.lock` file exists under any `experiments/<id>/`), the New Experiment button is hidden in favour of a "View live log" link so two sessions can't accidentally launch concurrent runs. Same guard as before — only the surface changed.

### Live log

The log page opens an `EventSource` against `GET /api/projects/<name>/runs/<id>/stream`. The endpoint:

1. Drains the existing `run.log` content as `data:` events.
2. Polls every 0.5s for new content.
3. When the `.lock` file disappears, emits `event: status\ndata: {"status":"completed"}` and closes.
4. If neither lock nor log exists, emits `event: status\ndata: {"status":"no_log"}` once and closes.

Finalization is streamed the same way at `GET /api/projects/<name>/finalize/stream`.

### Mid-run interactive prompts

When the orchestrator pauses to ask a question (Phase 11F), the SSE stream emits a third event class alongside `data:` and `event: status`:

```
event: prompt
data: {"prompt_id": "<uuid>", "question": "Which model should I tune first?"}
```

The live-log page renders this as an inline answer form below the streamed log. Submitting the form POSTs to `POST /api/projects/<name>/runs/<exp>/respond` with the matching `prompt_id` and the user's answer; the orchestrator receives the answer and the run continues. Until the orchestrator side fully wires this through, the dashboard already accepts the events and renders the form — the orchestrator integration is the remaining piece.


## Advisor chat

`/projects/<name>/advisor` is the in-browser chat surface for the advisor agent. The page renders the persistent advisor transcript stored under `projectbook/advisor.json`, with a "Send" composer at the bottom. Submitting posts to `POST /api/projects/<name>/advisor`, which appends the user message, runs the advisor agent, appends the response, and returns an HTMX fragment with the new exchange. History persists across reloads — the same store is shared with the CLI's `urika advisor` and the TUI's `/advisor` slash command. See [Advisor](07-advisor.md) for the underlying memory model.


## Finalize button + log page

The project home page surfaces a **Finalize project** button when no `findings.json` exists yet (or always available as a re-run from the project menu). Clicking it POSTs to `POST /api/projects/<name>/finalize` to start the finalize subprocess and redirects the browser to `/projects/<name>/finalize/log`, which streams the finalize subprocess output via the same SSE pattern as the run live log. Concurrency is gated on `projectbook/.finalize.lock`.


## Knowledge add form

The knowledge page now has an **+ Add knowledge** button (top-right) that opens a modal accepting either a local file path or a URL. Submitting posts to `POST /api/projects/<name>/knowledge`, which runs the knowledge ingestion pipeline (PDF, text, or URL extractors as appropriate) and returns an HTMX fragment that re-renders the entries list with the new entry on top.


## Tools and criteria pages

- `/projects/<name>/tools` is a read-only listing of the project's registered tools (built-in plus tool-builder created), with name, signature, and short description per row.
- `/projects/<name>/criteria` renders the project's versioned success criteria — current criteria at the top, history below. Editing criteria remains a CLI workflow (`urika criteria edit`); the dashboard is read-only.


## CLI ↔ dashboard coverage map

| CLI command | Dashboard surface |
|---|---|
| `list` | `/projects` |
| `new` | **+ New project** modal on `/projects` → `POST /api/projects` |
| `run` | **+ New experiment** modal on `/projects/<n>/experiments` → `POST /api/projects/<n>/run` |
| `experiment` | `/projects/<n>/experiments` |
| `methods` | `/projects/<n>/methods` |
| `knowledge` (read) | `/projects/<n>/knowledge` |
| `knowledge add` | **+ Add knowledge** modal → `POST /api/projects/<n>/knowledge` |
| `results` | experiment-detail runs table |
| `report` | per-experiment + project-level report viewers |
| `present` | per-experiment + project-level presentation viewers |
| `finalize` | **Finalize project** button on project home → `/projects/<n>/finalize/log` |
| `advisor` | `/projects/<n>/advisor` chat panel |
| `config` | `/settings` (global) + `/projects/<n>/settings` (project) |
| `notifications` | settings tab — global + per-project, full edit |
| `update` | project settings PUT |
| `criteria` | `/projects/<n>/criteria` (read-only viewer) |
| `tools` | `/projects/<n>/tools` (read-only viewer) — **+ Build tool** modal launches `urika build-tool` (Phase 13) |
| `logs` | `/projects/<n>/experiments/<id>/log` |
| `status` | project home |
| `evaluate` | **Evaluate** button on experiment detail → `POST /api/projects/<n>/experiments/<id>/evaluate` (Phase 13) |
| `summarize` | **Summarize / Re-summarize project** button on project home → `POST /api/projects/<n>/summarize` (Phase 13) |
| `build-tool` | **+ Build tool** modal on project tools page → `POST /api/projects/<n>/tools/build` (Phase 13) |
| `inspect` | `/projects/<n>/data` and `/projects/<n>/data/inspect` (Phase 13) |
| `usage` | `/projects/<n>/usage` (Phase 13) |
| `plan` | **CLI-only** — agent invocation, not user-facing |
| `setup` | **CLI-only** — installation flow |
| `dashboard` | **CLI-only** (it starts this server) |

Anything marked **CLI-only** is intentional: those commands are either agent-invocation primitives that the orchestrator drives internally, local-data introspection that doesn't translate to a hosted view, or one-shot installation flows.


## Sidebar navigation

The sidebar is **mode-aware** — it shows different links depending on whether the user is inside a project or browsing globally.

- **Header**: a large, centered **URIKA** wordmark in accent colour.
- **Global mode** (active on `/projects` and `/settings`):
  - Projects (registry list)
  - Global settings
- **Project mode** (active on any `/projects/<name>/...` route):
  - A "← Back to projects" link returns the user to the registry.
  - Project-scoped links (canonical order): Home, Experiments, Advisor, Knowledge, Methods, Tools, Data, Usage, Settings. Advisor sits second after Experiments so the conversational entry point is one click away; Methods/Tools/Data cluster the analytical surfaces; Usage and Settings close the list.
- **Footer**: the theme toggle (moved here in Phase 11A from its previous location in the page header).

Sidebar links are muted by default, accent-coloured on hover, and accent + tinted-background when the current path matches the link's route. Active state is computed server-side from the request path.

The mode is determined server-side from the request path; there is no client-side state. The same base template renders both — the project-mode links are conditional on a `project` template variable being set by the project routes.


## Status pill colours

Status pills (used on experiment cards, run rows, finalize banner, etc.) use semantic colour tokens defined in `static/app.css`:

| Status | Token | Colour |
|---|---|---|
| `completed` | `--pill-success` | green |
| `running` | `--pill-info` | blue |
| `paused` | `--pill-warning` | yellow |
| `failed` | `--pill-danger` | red |
| `pending` | `--pill-neutral` | gray |

The tokens swap automatically under `[data-theme="dark"]`. Adding a new status means defining a new token + a small Jinja branch in the `status_pill()` macro.


## Artifact viewers

Reports, presentations, findings, and uploaded files are all served as **rendered HTML pages**, not as raw file downloads. The principle is:

> **JSON is for agents and scripts; pages render formatted views.**

This applies across the dashboard:

- **Experiment reports** (`/projects/<name>/experiments/<id>/report`) — `report.md` is rendered through the dashboard's markdown helper into the same theme as the rest of the UI. If no report exists, the experiment detail page shows a "Generate report" button that POSTs to the finalize endpoint and streams the log.
- **Experiment presentations** (`/projects/<name>/experiments/<id>/presentation`) — the reveal.js HTML produced by the presentation agent is served inside an iframe with the standard navigation bar; opening in a new tab gives full-screen reveal.
- **Experiment files** (`/projects/<name>/experiments/<id>/files/<path>`) — uploaded artifacts (CSVs, plots, JSON snapshots) are listed on the experiment detail page. Text files and images render inline; everything else gets a download link with content-type set correctly.
- **Project findings** (`/projects/<name>/findings`) — `findings.json` is parsed and rendered as a structured page: title, summary prose, metrics in a sortable table, references as a list. The raw JSON is still available at `/api/projects/<name>/findings` for agents.
- **Project report and presentation** — same pattern as the experiment-level versions, served from `projectbook/report.md` and `projectbook/presentation.html`.

The experiment detail page composes all of these into a single view: hypotheses, runs, an embedded report viewer (or "Generate" button), an embedded presentation link (or "Generate" button), and the file list.

The project home page surfaces the same artifacts as **"Final outputs"** cards — they appear whenever the corresponding file exists on disk. Each card links to the rendered page, never to the JSON.


## Project deletion (Danger zone)

Project settings (`/projects/<n>/settings`) ends with a **Danger zone** section. The "Move to trash" button is gated by a GitHub-style typed-name confirmation: the user must type the project name exactly before the button enables. Submitting `DELETE /api/projects/<n>` moves the project directory to `~/.urika/trash/<n>-<timestamp>/` and removes the registry entry; the response includes `HX-Redirect: /projects` so the browser lands on the projects list.

If the project has any `.lock` file underneath it (active run / finalize / evaluate), the danger zone renders a disabled state with the lock path instead of the active button — the same active-run guard the CLI enforces.

The projects list (`/projects`) shows an inline **Unregister** button next to any project whose registered path no longer exists on disk. Clicking it posts `DELETE` to the same endpoint, which falls into the registry-only branch (nothing to move — the folder is already gone).

Files are preserved in `~/.urika/trash/`. Empty the trash manually when you're sure. There's no Restore command — copy the directory back yourself if you ever need to.


## Settings UI

Two settings pages share the same tabbed form pattern. Tabs are a small Alpine.js primitive — no router, no URL fragments — so saving a tab's form does not navigate away.

- **Project settings** (`/projects/<name>/settings`) — writes to that project's `urika.toml`. Five tabs:
  - **Basics**: name, mode, audience, research question.
  - **Data**: dataset path, target column, feature columns. Saving appends a new entry to `revisions.json` so changes are auditable.
  - **Models**: per-agent model overrides (planning, task, evaluator, advisor, etc.).
  - **Privacy**: an **Inherit / Override global** picker. Inherit removes the `[privacy]` block from `urika.toml` and the project falls back to the global default. Override exposes privacy mode (`local`, `hybrid`, `cloud`) and any path allow-listing.
  - **Notifications**: per-channel **Inherit / Enabled / Disabled** radios (slack, email, desktop) plus an editable extra-recipients list. Same inheritance pattern as Privacy.
- **Global settings** (`/settings`) — writes to `~/.urika/settings.toml` and seeds new projects. Four tabs:
  - **Privacy**: default privacy mode for new projects.
  - **Models**: default per-agent model assignments.
  - **Preferences**: default audience, max turns, theme preference.
  - **Notifications**: default notification configuration.

Both pages POST to a `PUT /api/...` endpoint that validates the payload and saves through the same `_write_toml` helper used by the CLI's `urika config`. See [Configuration](13-configuration.md) for the underlying file formats.


## Theme toggle

The light/dark toggle lives in the sidebar footer (Phase 11A — it used to sit in the page header). It is pure Alpine + `localStorage`:

```html
<html data-theme="{{ theme | default('light') }}"
      x-data="{ theme: localStorage.getItem('urika-theme') || 'light' }"
      x-init="document.documentElement.dataset.theme = theme"
      :data-theme="theme">
```

The button flips `theme` and persists the choice. CSS variables in `static/app.css` switch on `[data-theme="dark"]`. No server round-trip; no cookie.


## Cross-surface coordination

The dashboard, CLI, and TUI all read and write the same project files. Coordination is filesystem-mediated:

| Signal | Path | Meaning |
|--------|------|---------|
| Active run | `experiments/<id>/.lock` | A run is in progress. The PID is the file content. |
| Active finalize | `projectbook/.finalize.lock` | A finalization sequence is running. |
| Active presentation | `experiments/<id>/.present.lock` | A presentation render is running. |
| Run output | `experiments/<id>/run.log` | Append-only stdout from the orchestrator. |
| Progress | `experiments/<id>/progress.json` | Append-only run records (status, metrics, timestamps). |
| Methods | `methods.json` | Project-wide method registry. |
| Criteria | `criteria.json` | Versioned success criteria. |

The dashboard never holds in-memory project state across requests; every page render reads from disk. As a result, a run started from the CLI shows up in the browser on the next refresh; a run started from the dashboard appears in the TUI's `/status` and `/results` immediately.

The dashboard is the sole writer to `run.log` for runs it spawns -- agents `print()` to stdout, the dashboard's subprocess wrapper tees that to the log file. This avoids interleaved writes.


## Auth

By default the dashboard binds `127.0.0.1` and accepts every connection. For shared or networked deployments use `--auth-token`:

```bash
urika dashboard --auth-token "$(openssl rand -hex 32)"
```

When set, every request other than `/healthz` and `/static/...` requires:

```
Authorization: Bearer <token>
```

The check uses `secrets.compare_digest` for constant-time comparison. `/healthz` is exempt so external health probes work; `/static/...` is exempt so a token-aware client can still load the CSS and JS.

**Limitation.** Browsers don't send `Authorization` headers on top-level page navigation, so the token mode is intended for token-aware HTTP clients (curl, internal tooling, reverse proxies that inject the header). For browser use over an untrusted network, front the dashboard with a reverse proxy that handles auth (e.g. an SSH tunnel, a VPN, or an OAuth proxy).


## API endpoints

The dashboard's HTMX/fetch endpoints (server-rendered pages above are the only thing users navigate to directly):

| Endpoint | Purpose | Phase |
|---|---|---|
| `POST /api/projects` | Create a new project — runs `urika new --json --non-interactive`. | 11C |
| `DELETE /api/projects/<n>` | Move the project to `~/.urika/trash/` and unregister it. 422 if a `.lock` file exists. | post-13 |
| `POST /api/projects/<n>/run` | Spawn an experiment run. | — |
| `GET  /api/projects/<n>/runs/<id>/stream` | SSE stream of the run log, including `event: prompt` for mid-run questions. | 11F |
| `POST /api/projects/<n>/runs/<exp>/respond` | Answer a mid-run interactive prompt. | 11F.2 |
| `POST /api/projects/<n>/finalize` | Kick off the finalize subprocess. | — |
| `GET  /api/projects/<n>/finalize/stream` | SSE stream of the finalize log. | — |
| `POST /api/projects/<n>/summarize` | Spawn the summarize subprocess. | 13C |
| `GET  /api/projects/<n>/summarize/stream` | SSE stream of the summarize log. | 13C |
| `POST /api/projects/<n>/experiments/<id>/evaluate` | Spawn the evaluate subprocess for an experiment. | 13B |
| `POST /api/projects/<n>/experiments/<id>/report` | Spawn the report subprocess for an experiment. | 13B |
| `POST /api/projects/<n>/tools/build` | Spawn the tool-builder subprocess. | 13D |
| `GET  /api/projects/<n>/tools/build/stream` | SSE stream of the tool-builder log. | 13D |
| `POST /api/projects/<n>/advisor` | Send a chat message to the advisor; appends to `projectbook/advisor.json`. | 11E.1 |
| `POST /api/projects/<n>/knowledge` | Add a knowledge entry from a path or URL. | 11E.3 |
| `PUT  /api/projects/<n>/settings/...` | Save settings tabs (basics/data/models/privacy/notifications). | — |
| `PUT  /api/settings/...` | Save global settings tabs. | — |
| `GET  /api/projects/<n>/findings` | Raw findings JSON (for agents/scripts; UI uses the rendered page). | — |

No rendered link in the dashboard points at an `/api/*` URL — they are exclusively HTMX/fetch targets.


## Phase 13 additions at a glance

For readers cross-referencing the Phase 13 plan (`dev/plans/2026-04-26-phase-13-coverage-and-modals.md`):

- **Modal flag expansion (13A).** Run, Finalize, and New Project modals now expose every meaningful CLI flag — `--instructions`, `--audience`, `--draft`, `--auto`, `--max-experiments`, `--review-criteria`, `--resume`. Whatever you can pass on the CLI is now selectable in the browser.
- **Per-experiment agent buttons (13B).** Experiment detail page got Evaluate, Generate / Re-generate report, and Generate / Re-generate presentation modals. Each spawns the matching CLI subprocess and HX-Redirects to the live log.
- **Project home expansion (13C).** Summarize / Re-summarize project button alongside Finalize. The summarizer's text output is persisted to `projectbook/summary.md` so the Re-summarize label flips on disk state, and a "Summary" card appears in Final outputs when present. `urika summarize` gained an `--instructions` flag for parity with other commands.
- **Tool builder in-browser (13D).** Project Tools page got a `+ Build tool` button that opens a modal with a free-text instructions textarea and posts to `urika build-tool`. Privacy gate fires before spawn — tool_builder runs in private mode under hybrid.
- **Data inspection (13E).** New `/projects/<n>/data` page lists registered data sources from `urika.toml`'s `[project].data_paths`. `/data/inspect?path=...` shows column / dtype / missing / numeric stats plus head(10) and tail(10) preview, using the same loader registry the agents use. Path traversal is blocked by an allow-list validator against `data_paths` plus `<project>/data`.
- **Usage charts (13F).** `/projects/<n>/usage` reads `usage.json`, shows totals plus token-over-time and cost-over-time line charts via Chart.js (4.4.1, CDN). Per-experiment / per-agent slices intentionally omitted — the usage schema doesn't carry that breakdown yet.
- **Macro DRY (13G.1).** `action_label("Generate", "report", has_report)` → "Generate report" / "Re-generate report". One macro replaces four inlined ternaries across `project_home.html` and `experiment_detail.html`.
- **Sidebar reorder (13G.2).** Canonical project-mode order is now Home / Experiments / Methods / Tools / Data / Knowledge / Advisor / Usage / Settings.


## Phase 11 additions at a glance

For readers cross-referencing the Phase 11 plan (`dev/plans/2026-04-26-dashboard-coverage-flows.md`):

- **Visuals.** Theme toggle moved to sidebar footer; URIKA wordmark big & centered; sidebar links got muted/hover/active states; status pills picked up semantic colour tokens.
- **Modal primitive.** Reusable `modal()` Jinja macro powers both **+ New project** and **+ New experiment**.
- **Project lifecycle in-browser.** Creating a project, launching an experiment, kicking off finalize, and adding knowledge are all dashboard surfaces now.
- **Advisor chat.** `/projects/<n>/advisor` panel shares the persistent transcript with the CLI/TUI.
- **Tools + criteria viewers.** Read-only pages for the two remaining surfaces previously only reachable from the CLI.
- **Project Privacy + Notifications full edit.** Inherit-from-global vs override semantics, persisted in `urika.toml`.
- **Mid-run prompts.** SSE event class extension + answer form + `POST /respond` endpoint, ready for the orchestrator-side wiring.


## Tech stack

- **FastAPI** -- routing and dependency injection.
- **Uvicorn** -- ASGI server, run on a daemon thread.
- **Jinja2** -- server-side templates.
- **HTMX** (CDN) -- form posts and partial swaps.
- **Alpine.js** (CDN) -- small reactive bits (theme toggle, conditional reveals, modals).
- **Server-Sent Events** -- log streaming, mid-run prompt delivery.

No build step. No JavaScript bundle. Everything is server-rendered HTML plus two CDN-loaded helpers.

---

**Next:** [Interactive TUI](16-interactive-tui.md)
