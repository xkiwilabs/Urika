# Dashboard — Pages and Navigation

Dashboard launching, pages and routes, modals (New Project / New Experiment), live log streaming, mid-run prompts, advisor chat, sessions, sidebar navigation, status pills, artifact viewers, and the theme toggle. See [Operations](18b-dashboard-operations.md), [Settings](18c-dashboard-settings.md), and [API](18d-dashboard-api.md) for the rest of the dashboard surface.

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

The slash command starts a daemon-thread server on a free port and opens the browser at the project home page. `/dashboard stop` shuts running dashboards down. See [Interactive TUI](17-interactive-tui.md#slash-commands) for the full list of TUI commands.

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
| `/projects/<name>/advisor/log` | Live SSE stream of the running `urika advisor` subprocess (see below). |
| `/projects/<name>/sessions` | Recent orchestrator chat sessions, newest first, with Resume / Delete actions (see below). |
| `/projects/<name>/data` | Data sources registered for the project. |
| `/projects/<name>/data/inspect?path=...` | Schema, missing counts, head/tail preview for one file. |
| `/projects/<name>/usage` | Token / cost time-series charts and recent sessions table. |
| `/projects/<name>/projectbook/summary` | Rendered `projectbook/summary.md` from the summarizer agent. |
| `/projects/<name>/compare` | Side-by-side metric comparison across selected experiments. |
| `/projects/<name>/finalize/log` | Finalize log page: streams the running finalize subprocess via SSE. |
| `/projects/<name>/summarize/log` | Summarize log page: streams the running summarize subprocess via SSE. |
| `/projects/<name>/tools/build/log` | Build-tool log page: streams the running tool-builder subprocess via SSE. |
| `/projects/<name>/experiments/<id>/log` | Live log streaming via SSE (see below). |
| `/projects/<name>/settings` | Project settings (tabbed: basics / data / privacy / models / notifications / secrets). |
| `/settings` | Global defaults (tabbed: privacy / models / preferences / notifications / secrets). |
| `/healthz` | Liveness probe. Always returns `{"status":"ok"}`. |

Run launching lives behind the **+ New experiment** modal on the experiments list (see [Modals](#modals-new-project--new-experiment) below). `/` redirects to `/projects`.


## Modals: New Project + New Experiment

Two modal dialogs open in-place from the relevant list pages. Both share the same `modal()` Jinja primitive — a small accessible dialog with a backdrop, an Alpine `x-data` toggle, and a labelled close button.

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

When the orchestrator pauses to ask a question, the SSE stream emits a third event class alongside `data:` and `event: status`:

```
event: prompt
data: {"prompt_id": "<uuid>", "question": "Which model should I tune first?"}
```

The live-log page renders this as an inline answer form below the streamed log. Submitting the form POSTs to `POST /api/projects/<name>/runs/<exp>/respond` with the matching `prompt_id` and the user's answer; the orchestrator receives the answer and the run continues. Until the orchestrator side fully wires this through, the dashboard already accepts the events and renders the form — the orchestrator integration is the remaining piece.


## Advisor chat

`/projects/<name>/advisor` is the in-browser chat surface for the advisor agent. The page renders the persistent advisor transcript stored under `projectbook/advisor-history.json`, with a "Send" composer at the bottom. Submitting posts to `POST /api/projects/<name>/advisor`, which appends the user message, runs the advisor agent, appends the response, and returns an HTMX fragment with the new exchange. History persists across reloads — the same store is shared with the CLI's `urika advisor` and the TUI's `/advisor` slash command. See [Advisor](07-advisor-and-instructions.md) for the underlying memory model.

### Advisor subprocess + log streaming

The dashboard's advisor is a real subprocess of `urika advisor`, not an
in-process call. Submitting a message:

1. `POST /api/projects/<n>/advisor` writes a `.advisor.lock` file (PID),
   spawns `urika advisor` as a detached subprocess, drains stdout into
   `projectbook/advisor.log`, and HX-Redirects the browser to the live
   stream page.
2. The live stream page (`GET /projects/<n>/advisor/log`, template
   `advisor_log.html`) tails the log file via SSE
   (`GET /api/projects/<n>/advisor/stream`).
3. On completion: the advisor's user message + response are persisted to
   `projectbook/advisor-history.json` (the same store used by CLI
   `urika advisor` and TUI `/advisor`).
4. While the subprocess is alive, the running-ops banner shows an
   "advisor" chip — running advisor and a separate experiment run can
   coexist (different lock files, different log streams).

The transcript view at `GET /projects/<n>/advisor` reads the persisted
history. When called with `?session_id=<id>`, it also pre-loads an
orchestrator chat session's messages above the transcript as read-only
context (the **Resume** button on the Sessions list links here).


## Sessions list

### `/projects/<n>/sessions`

Lists recent orchestrator chat sessions for the project, newest first.
Sessions are persisted automatically when you chat with the orchestrator
from the terminal (REPL/TUI) — launch `urika` and start typing, or use
slash commands. Each row shows:

- The session's first user message (preview, truncated to 80 characters).
- Turn count (number of user-assistant exchanges).
- Last-updated timestamp.
- **Resume** button — navigates to `/projects/<n>/advisor?session_id=<id>`,
  which pre-loads the prior session's messages above the advisor composer
  as read-only context.
- **Delete** button — `DELETE /api/projects/<n>/sessions/<id>` trashes
  the session JSON file. HTMX-driven row swap-out on success.

Sessions auto-prune to the most recent 20 per project on each save (see
`src/urika/core/orchestrator_sessions.py`).

Empty state: "No sessions yet. Sessions are saved automatically when you
chat with the orchestrator from the terminal."


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
| `knowledge ingest` | **+ Add knowledge** modal → `POST /api/projects/<n>/knowledge` |
| `results` | experiment-detail runs table |
| `report` | per-experiment + project-level report viewers |
| `present` | per-experiment + project-level presentation viewers |
| `finalize` | **Finalize project** button on project home → `/projects/<n>/finalize/log` |
| `advisor` | `/projects/<n>/advisor` chat panel |
| `config` | `/settings` (global) + `/projects/<n>/settings` (project) |
| `notifications` | settings tab — global + per-project, full edit |
| `update` | project settings PUT |
| `criteria` | `/projects/<n>/criteria` (read-only viewer) |
| `tools` | `/projects/<n>/tools` (read-only viewer) — **+ Build tool** modal launches `urika build-tool` |
| `logs` | `/projects/<n>/experiments/<id>/log` |
| `status` | project home |
| `evaluate` | **Evaluate** button on experiment detail → `POST /api/projects/<n>/experiments/<id>/evaluate` |
| `summarize` | **Summarize / Re-summarize project** button on project home → `POST /api/projects/<n>/summarize` |
| `build-tool` | **+ Build tool** modal on project tools page → `POST /api/projects/<n>/tools/build` |
| `inspect` | `/projects/<n>/data` and `/projects/<n>/data/inspect` |
| `usage` | `/projects/<n>/usage` |
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
  - Project-scoped links (canonical order): Home, Experiments, Advisor, Sessions, Knowledge, Methods, Tools, Data, Usage, Settings. Advisor sits second after Experiments so the conversational entry point is one click away; Sessions sits next to Advisor since the two are linked (Resume from Sessions pre-loads into the Advisor chat); Methods/Tools/Data cluster the analytical surfaces; Usage and Settings close the list.
- **Footer**: the theme toggle.

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


## Theme toggle

The light/dark toggle lives in the sidebar footer. It is pure Alpine + `localStorage`:

```html
<html data-theme="{{ theme | default('light') }}"
      x-data="{ theme: localStorage.getItem('urika-theme') || 'light' }"
      x-init="document.documentElement.dataset.theme = theme"
      :data-theme="theme">
```

The button flips `theme` and persists the choice. CSS variables in `static/app.css` switch on `[data-theme="dark"]`. No server round-trip; no cookie.


## See also

- [Dashboard — Operations](18b-dashboard-operations.md)
- [Dashboard — Settings](18c-dashboard-settings.md)
- [Dashboard — API](18d-dashboard-api.md)
- [CLI Reference](16a-cli-projects.md)
- [Interactive TUI](17-interactive-tui.md)
- [Configuration](14a-project-config.md)
