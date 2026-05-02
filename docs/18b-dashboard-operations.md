# Dashboard — Running Operations

How the dashboard tracks running operations via lockfiles, idempotent spawn endpoints, completion CTAs, the animated thinking placeholder, and project deletion. See [Pages and Navigation](18a-dashboard-pages.md), [Settings](18c-dashboard-settings.md), and [API](18d-dashboard-api.md) for the rest of the dashboard surface.

## Running operations

Lock files are the source of truth for which agent operations are currently running for a project. The dashboard never holds in-memory run state across requests — every page render walks the project tree and asks: which `.lock` files are present, and is the PID inside still alive?

The recognised lock shapes are:

| Lock file | Op type |
|---|---|
| `experiments/<id>/.lock` | run (experiment orchestrator) |
| `experiments/<id>/.evaluate.lock` | evaluate |
| `experiments/<id>/.report.lock` | report |
| `experiments/<id>/.present.lock` | present |
| `projectbook/.finalize.lock` | finalize |
| `projectbook/.summarize.lock` | summarize |
| `tools/.build.lock` | build_tool |

Each PID lock contains the subprocess PID. `urika.dashboard.active_ops.list_active_operations(project_name, project_path)` walks them, filters out stale ones (dead PID, empty file, non-numeric content), filters out JSON-write mutexes (`criteria.json.lock`, `usage.json.lock` from `urika.core.filelock` — basenames without a leading dot), and returns a flat list of `ActiveOp{type, project_name, experiment_id, lock_path, log_url}`.

Three surfaces read from this list:

**Idempotent spawn endpoints.** Every `POST` that spawns a subprocess (`/run`, `/finalize`, `/summarize`, `/experiments/<id>/evaluate`, `/experiments/<id>/report`, `/present`, `/tools/build`) checks for an existing live op of the same kind first. If one exists:
- HTMX request → 200 + `HX-Redirect` to the running op's log URL (the user lands on the live stream they were going to see anyway).
- Plain HTTP → 409 with `{"status": "already_running", "log_url": ..., "type": ...}` (curl / scripts can detect duplicates).

For experiment-level ops the match is scoped to `(type, experiment_id)` so two different experiments can run evaluators in parallel; for project-level ops there can only be one of each kind at a time.

**Trigger buttons reflect running state.** On the project home, experiment detail, project tools, and experiments-list pages, every button that spawns one of these ops reads its state from `running_by_type` / `running_by_exp` (passed into the template context). When the op is in flight, the button becomes an `<a class="btn btn--running">` linking directly to the log stream — pulsing dot, accent border — instead of an `<a>` that opens a modal. Idle buttons keep their normal label and modal flow.

**Persistent banner.** Every project-scoped page renders a `_base.html` banner above the heading: `Running: <type> · <experiment_id?>` chips, each linking to its own log stream. The chip pointing at the current page is suppressed (no self-link) by comparing `op.log_url` against `request.url.path + ?query`. The banner is only rendered if at least one chip survives that filter — empty banners don't render. Global pages (`/projects`, `/settings`, docs) don't get the banner.

### Animated thinking placeholder

While a stream is connecting (or quietly waiting between agent steps), the log page renders an animated placeholder: a urika-blue braille spinner at 200ms per frame with rotating activity verbs ("Thinking", "Reasoning", "Analyzing", "Processing", …) at randomized 4–8 frame intervals plus jitter. The cadence is intentionally non-uniform so it feels alive rather than mechanical.

The placeholder lives in `_thinking.html` (Jinja partial) backed by `static/urika-thinking.js` (`window.urikaThinking.start(el)` returning a `{stop()}` handle). Used by `advisor_chat.html`, `run_log.html`, `summarize_log.html`, `finalize_log.html`, and `tool_build_log.html`. Each log page stops the placeholder on the first SSE `data:` event AND on the completion `event: status`.

### Completion CTAs

When a stream ends, log pages fetch a small artifact-existence probe:

- Per-experiment ops use the existing `GET /api/projects/<n>/experiments/<id>/artifacts`.
- Project-level ops use the new `GET /api/projects/<n>/artifacts/projectbook` returning `{has_summary, has_report, has_presentation, has_findings}`.

The probe response unhides whichever "view the result" buttons are relevant — "View summary" after summarize, "View report" / "Open presentation ↗" / "View findings" after finalize, "Back to tools" after build-tool. Failed runs that wrote partial output still surface whatever DID land on disk; everything else stays hidden.


## Project deletion (Danger zone)

Project settings (`/projects/<n>/settings`) ends with a **Danger zone** section. The "Move to trash" button is gated by a GitHub-style typed-name confirmation: the user must type the project name exactly before the button enables. Submitting `DELETE /api/projects/<n>` moves the project directory to `~/.urika/trash/<n>-<timestamp>/` and removes the registry entry; the response includes `HX-Redirect: /projects` so the browser lands on the projects list.

If the project has any `.lock` file underneath it (active run / finalize / evaluate), the danger zone renders a disabled state with the lock path instead of the active button — the same active-run guard the CLI enforces.

The projects list (`/projects`) shows an inline **Unregister** button next to any project whose registered path no longer exists on disk. Clicking it posts `DELETE` to the same endpoint, which falls into the registry-only branch (nothing to move — the folder is already gone).

Files are preserved in `~/.urika/trash/`. Empty the trash manually when you're sure. There's no Restore command — copy the directory back yourself if you ever need to.


## See also

- [Dashboard — Pages and Navigation](18a-dashboard-pages.md)
- [Dashboard — Settings](18c-dashboard-settings.md)
- [Dashboard — API](18d-dashboard-api.md)
- [CLI Reference](16a-cli-projects.md)
- [Interactive TUI](17-interactive-tui.md)
- [Configuration](14a-project-config.md)
