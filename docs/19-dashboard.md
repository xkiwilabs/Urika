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
| `/projects/<name>` | Project home: summary card, recent experiments, quick links. |
| `/projects/<name>/experiments` | All experiments for the project, with status and run counts. |
| `/projects/<name>/experiments/<id>` | Experiment detail: hypotheses, runs, links to report/presentation/log. |
| `/projects/<name>/methods` | Project methods registry sorted by metric. |
| `/projects/<name>/knowledge` | Knowledge base entries for the project. |
| `/projects/<name>/knowledge/<id>` | A single knowledge entry. |
| `/projects/<name>/run` | Run launcher form (see below). |
| `/projects/<name>/experiments/<id>/log` | Live log streaming via SSE (see below). |
| `/projects/<name>/settings` | Project settings: privacy mode, audience, model overrides. |
| `/settings` | Global defaults (`~/.urika/settings.toml`): privacy, audience, max turns. |
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


## Settings UI

Two settings pages share the same form-based pattern:

- **Project settings** (`/projects/<name>/settings`) -- writes to that project's `urika.toml`.
- **Global settings** (`/settings`) -- writes to `~/.urika/settings.toml` and seeds new projects.

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
