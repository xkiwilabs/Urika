# Dashboard — API and Tech Stack

Cross-surface coordination, the dashboard's HTMX/fetch API endpoints, and the underlying tech stack. See [Pages and Navigation](18a-dashboard-pages.md), [Operations](18b-dashboard-operations.md), and [Settings](18c-dashboard-settings.md) for the rest of the dashboard surface.

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


## API endpoints

The dashboard's HTMX/fetch endpoints (server-rendered pages above are the only thing users navigate to directly):

| Endpoint | Purpose |
|---|---|
| `POST /api/projects` | Create a new project — runs `urika new --json --non-interactive`. |
| `DELETE /api/projects/<n>` | Move the project to `~/.urika/trash/` and unregister it. 422 if a `.lock` file exists. |
| `POST /api/projects/<n>/run` | Spawn an experiment run. |
| `GET  /api/projects/<n>/runs/<id>/stream` | SSE stream of the run log, including `event: prompt` for mid-run questions. |
| `POST /api/projects/<n>/runs/<exp>/respond` | Answer a mid-run interactive prompt. |
| `POST /api/projects/<n>/runs/<exp>/stop` | Send SIGTERM to a running experiment. |
| `POST /api/projects/<n>/runs/<exp>/pause` | Request pause-at-next-turn for a running experiment. |
| `POST /api/projects/<n>/finalize` | Kick off the finalize subprocess. |
| `POST /api/projects/<n>/finalize/stop` | Send SIGTERM to a running finalize. |
| `GET  /api/projects/<n>/finalize/stream` | SSE stream of the finalize log. |
| `POST /api/projects/<n>/summarize` | Spawn the summarize subprocess. |
| `POST /api/projects/<n>/summarize/stop` | Send SIGTERM to a running summarize. |
| `GET  /api/projects/<n>/summarize/stream` | SSE stream of the summarize log. |
| `POST /api/projects/<n>/experiments/<id>/evaluate` | Spawn the evaluate subprocess for an experiment. |
| `POST /api/projects/<n>/experiments/<id>/report` | Spawn the report subprocess for an experiment. |
| `POST /api/projects/<n>/runs/<exp>/present/stop` | Send SIGTERM to a running presentation generation. |
| `POST /api/projects/<n>/tools/build` | Spawn the tool-builder subprocess. |
| `POST /api/projects/<n>/build-tool/stop` | Send SIGTERM to a running tool-builder. |
| `GET  /api/projects/<n>/tools/build/stream` | SSE stream of the tool-builder log. |
| `POST /api/projects/<n>/advisor` | Send a chat message to the advisor; spawns `urika advisor` and HX-Redirects to the log stream. |
| `POST /api/projects/<n>/advisor/stop` | Send SIGTERM to a running advisor. |
| `GET  /api/projects/<n>/advisor/stream` | SSE endpoint tailing `projectbook/advisor.log` while the advisor subprocess runs. |
| `DELETE /api/projects/<n>/sessions/<id>` | Trash an orchestrator chat session JSON file. HTMX-driven row swap. |
| `POST /api/settings/notifications/test-send` | Send a test notification through every configured channel; returns per-channel success/failure JSON. |
| `POST /api/projects/<n>/knowledge` | Add a knowledge entry from a path or URL. |
| `PUT  /api/projects/<n>/settings/...` | Save settings tabs (basics / data / privacy / models / notifications / secrets). |
| `PUT  /api/settings/...` | Save global settings tabs. |
| `GET  /api/projects/<n>/findings` | Raw findings JSON (for agents/scripts; UI uses the rendered page). |

No rendered link in the dashboard points at an `/api/*` URL — they are exclusively HTMX/fetch targets.


## Tech stack

- **FastAPI** -- routing and dependency injection.
- **Uvicorn** -- ASGI server, run on a daemon thread.
- **Jinja2** -- server-side templates.
- **HTMX** (CDN) -- form posts and partial swaps.
- **Alpine.js** (CDN) -- small reactive bits (theme toggle, conditional reveals, modals).
- **Server-Sent Events** -- log streaming, mid-run prompt delivery.

No build step. No JavaScript bundle. Everything is server-rendered HTML plus two CDN-loaded helpers.

---

**Next:** [Notifications](19a-notifications-channels.md)


## See also

- [Dashboard — Pages and Navigation](18a-dashboard-pages.md)
- [Dashboard — Operations](18b-dashboard-operations.md)
- [Dashboard — Settings](18c-dashboard-settings.md)
- [CLI Reference](16a-cli-projects.md)
- [Interactive TUI](17-interactive-tui.md)
- [Configuration](14a-project-config.md)
