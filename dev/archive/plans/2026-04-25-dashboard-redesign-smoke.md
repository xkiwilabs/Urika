# Dashboard Redesign — Smoke Test Results

Companion to `dev/plans/2026-04-25-dashboard-redesign.md`. Captures the
state of automated and manual verification on 2026-04-25.

## Automated verification

### pytest sweep

```
pytest -q
1558 passed, 25 warnings in 47.17s
```

Up from baseline 1473 (1488 before the redesign + 15 dashboard fixture
backports, then 1473 once we discounted those). Net change: +85 tests
added across the new dashboard package, and ‑29 tests deleted with the
old `BaseHTTPRequestHandler` implementation in Phase 9.1.

### Server startup smoke

```
$ python -c '<startup harness>'
Started: True on port 39449
GET /healthz:        200 {'status': 'ok'}
GET /projects:       200  content-length=12475  has-htmx=True   has-css=True
GET /static/app.css: 200  content-length=11889  has-accent=True
```

Confirms: app factory wires templates + static + routers correctly,
HTMX/Alpine CDN tags are emitted, and the design-system CSS is served
with its `--accent` custom property intact.

### Routes inspected

26 routes registered:

| Method | Path |
|---|---|
| GET | `/healthz` |
| GET | `/` (redirect → `/projects`) |
| GET | `/projects` |
| GET | `/projects/{name}` |
| GET | `/projects/{name}/experiments` |
| GET | `/projects/{name}/experiments/{exp_id}` |
| GET | `/projects/{name}/experiments/{exp_id}/log` |
| GET | `/projects/{name}/methods` |
| GET | `/projects/{name}/knowledge` |
| GET | `/projects/{name}/knowledge/{entry_id}` |
| GET | `/projects/{name}/run` |
| GET | `/projects/{name}/settings` |
| GET | `/settings` |
| GET | `/api/projects` |
| PUT | `/api/projects/{name}/settings` |
| PUT | `/api/settings` |
| POST | `/api/projects/{name}/run` |
| GET | `/api/projects/{name}/runs/{exp_id}/stream` |
| POST | `/api/projects/{name}/runs/{exp_id}/stop` |
| GET | `/api/projects/{name}/experiments/{exp_id}/artifacts` |
| POST | `/api/projects/{name}/finalize` |
| GET | `/api/projects/{name}/finalize/stream` |
| POST | `/api/projects/{name}/present` |
| POST | `/api/projects/{name}/advisor` |
| MOUNT | `/static/*` |

## Manual browser smoke — pending

The plan's Task 9.4 calls for a manual browser walk-through:

- [ ] `urika dashboard <smoke-project>` opens browser; projects list shows.
- [ ] Click into project → home renders with question + recent experiments.
- [ ] Click Settings → edit description → Save → form returns "Saved" fragment, file on disk reflects the change.
- [ ] Click Run → fill form → Start → SSE-streamed log appears → run completes.
- [ ] Click Theme toggle → dark mode applies → reload → preserved (localStorage).
- [ ] Click sidebar Knowledge / Methods / Experiments → all render.

These were not run as part of this implementation pass. They should be
walked once the user has time at a machine. The endpoints they exercise
are all covered by the pytest suite at the unit level, so any browser-
specific issues will be CSS/JS rather than backend.

## Open follow-ups

- The Task 6.3 endpoint accepts an `instructions` form field but does
  not yet plumb it through to the spawned `urika run` subprocess. The
  CLI currently picks up project-level instructions from elsewhere.
- The plan refers to `audience = "standard"` as a forward-looking value
  in several places; core's `VALID_AUDIENCES` is still `{"expert",
  "novice"}`. The dashboard validates against the actual core set; the
  finalize CLI accepts the wider `{"novice", "standard", "expert"}` set
  — that mismatch predates this work and is out of scope.
- Phase 9.3 auth is bearer-token only. Browser flows still work without
  a token; with a token, the user must access the dashboard through a
  client that can attach the `Authorization: Bearer <token>` header.
  Cookie/query-param fallback is a future improvement.
