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
| `/projects/<name>/knowledge` | Knowledge base entries for the project. |
| `/projects/<name>/knowledge/<id>` | A single knowledge entry. |
| `/projects/<name>/run` | Run launcher form (see below). |
| `/projects/<name>/experiments/<id>/log` | Live log streaming via SSE (see below). |
| `/projects/<name>/settings` | Project settings (tabbed: basics / data / models / privacy / notifications). |
| `/settings` | Global defaults (tabbed: privacy / models / preferences / notifications). |
| `/healthz` | Liveness probe. Always returns `{"status":"ok"}`. |

`/` redirects to `/projects`.


## Run launcher

`/projects/<name>/run` is a form for starting an experiment without leaving the browser. Fields:

- **Experiment name** -- becomes the experiment directory.
- **Hypothesis** -- free-text hypothesis for this experiment.
- **Mode** -- `exploratory`, `confirmatory`, or `pipeline` (defaults to the project mode).
- **Audience** -- `expert` or `novice`.
- **Max turns** -- orchestrator turn cap.
- **Additional instructions** -- optional steering for the orchestrator.

The form posts to `POST /api/projects/<name>/run`, which spawns `urika run` as a subprocess. The page returns an HTMX fragment with a "View live log" link pointing at `/projects/<name>/experiments/<id>/log`.

If an experiment is already running (a `.lock` file exists under any `experiments/<id>/`), the launcher hides the form and shows the live-log link directly so two sessions can't accidentally launch concurrent runs.

### Live log

The log page opens an `EventSource` against `GET /api/projects/<name>/runs/<id>/stream`. The endpoint:

1. Drains the existing `run.log` content as `data:` events.
2. Polls every 0.5s for new content.
3. When the `.lock` file disappears, emits `event: status\ndata: {"status":"completed"}` and closes.
4. If neither lock nor log exists, emits `event: status\ndata: {"status":"no_log"}` once and closes.

Finalization is streamed the same way at `GET /api/projects/<name>/finalize/stream`.


## Sidebar navigation

The sidebar is **mode-aware** — it shows different links depending on whether the user is inside a project or browsing globally.

- **Global mode** (active on `/projects` and `/settings`):
  - Projects (registry list)
  - Global settings
  - Theme toggle
- **Project mode** (active on any `/projects/<name>/...` route):
  - A "← Back to projects" link returns the user to the registry.
  - Project-scoped links: Home, Experiments, Methods, Findings, Knowledge, Run, Settings.

The mode is determined server-side from the request path; there is no client-side state. The same base template renders both — the project-mode links are conditional on a `project` template variable being set by the project routes.


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


## Settings UI

Two settings pages share the same tabbed form pattern. Tabs are a small Alpine.js primitive — no router, no URL fragments — so saving a tab's form does not navigate away.

- **Project settings** (`/projects/<name>/settings`) — writes to that project's `urika.toml`. Five tabs:
  - **Basics**: name, mode, audience, research question.
  - **Data**: dataset path, target column, feature columns. Saving appends a new entry to `revisions.json` so changes are auditable.
  - **Models**: per-agent model overrides (planning, task, evaluator, advisor, etc.).
  - **Privacy**: privacy mode (`local`, `hybrid`, `cloud`) and any path allow-listing.
  - **Notifications**: per-event notification toggles (run finished, finalize finished, advisor cleared).
- **Global settings** (`/settings`) — writes to `~/.urika/settings.toml` and seeds new projects. Four tabs:
  - **Privacy**: default privacy mode for new projects.
  - **Models**: default per-agent model assignments.
  - **Preferences**: default audience, max turns, theme preference.
  - **Notifications**: default notification configuration.

Both pages POST to a `PUT /api/...` endpoint that validates the payload and saves through the same `_write_toml` helper used by the CLI's `urika config`. See [Configuration](13-configuration.md) for the underlying file formats.


## Theme toggle

The light/dark toggle is pure Alpine + `localStorage`:

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


## Tech stack

- **FastAPI** -- routing and dependency injection.
- **Uvicorn** -- ASGI server, run on a daemon thread.
- **Jinja2** -- server-side templates.
- **HTMX** (CDN) -- form posts and partial swaps.
- **Alpine.js** (CDN) -- small reactive bits (theme toggle, conditional reveals).
- **Server-Sent Events** -- log streaming.

No build step. No JavaScript bundle. Everything is server-rendered HTML plus two CDN-loaded helpers.

---

**Next:** [Interactive TUI](16-interactive-tui.md)
