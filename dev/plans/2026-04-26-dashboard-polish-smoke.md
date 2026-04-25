# Dashboard Polish — Smoke Test Results

Companion to `dev/plans/2026-04-26-dashboard-polish.md`. Captures the
state of automated and manual verification on 2026-04-26, after the
Phase 10 polish pass (sidebar bifurcation, artifact viewers, tabbed
settings, no-JSON-dump rule).

## Manual browser checklist — pending

These are the user-facing checks that pytest cannot exercise. Walk
through them in a real browser at a real `urika dashboard` against a
project with at least one experiment, one report, one presentation, and
one finalized findings file.

- [ ] Sidebar shows global links on `/projects` and `/settings`; back button + project nav inside a project.
- [ ] Theme toggle: light → dark → reload → preserved.
- [ ] Buttons: every visible button is colored (primary blue or ghost transparent), no bare-gray buttons.
- [ ] Project home: "Final outputs" cards appear when artifacts exist; click each one — no 404s.
- [ ] Experiment detail: "Generate report" button when no `report.md`; "View report" when present. Same for presentation. Files list shows uploaded artifacts.
- [ ] Click "Generate report" — runs finalize subprocess, log streams in, report appears after.
- [ ] Click "View presentation" — opens in new tab; reveal.js navigation works.
- [ ] Findings page renders structured (title, summary, metrics table) — no JSON dump.
- [ ] Methods page sorts client-side; no JSON in view-source.
- [ ] Settings (project): all 5 tabs render; saving Data → adds to `revisions.json`. Saving Models → updates `urika.toml`. Saving Notifications → updates `urika.toml`.
- [ ] Settings (global): all 4 tabs render; Privacy mode picker works; Notifications config persists.
- [ ] No `/api/*` link is reachable by clicking through the UI (only via HTMX/fetch internally).

## Automated verification

### pytest sweep

```
pytest -q
1655 passed, 75 warnings in 48.86s
```

Up from 1558 at the close of the Phase 9 redesign smoke. Net change:
**+97 tests** added across the polish phase. Breakdown by phase:

- 10A (sidebar bifurcation, dark default, visual audit): tests for
  mode-aware sidebar rendering, theme defaulting, button colour audit.
- 10B (markdown helper + per-experiment artifact viewers): tests for
  the markdown renderer, experiment report/presentation/file routes,
  reworked experiment detail composition.
- 10C (tabbed settings): tests for the tabs primitive, project
  settings (basics/data/models/privacy/notifications), global settings
  (privacy/models/preferences/notifications), `revisions.json` append
  on data save.
- 10D (no-JSON-dump rule): methods page sortable table, findings
  viewer (title/summary/metrics/references), regression test that no
  rendered page links to `/api/*`.
- 10E (project home final outputs): conditional rendering of report,
  presentation, and findings cards on the project home page.

### Dashboard package

```
pytest tests/test_dashboard/ -q
198 passed, 73 warnings in 5.05s
```

### Server startup smoke

```
$ timeout 6 python -c '<startup harness>'
Started: True on port 35613
GET /healthz:        200
GET /projects:       200
GET /settings:       200
GET /static/app.css: 200
```

Confirms: app factory, project list page, global settings page, and
the design-system CSS still serve correctly after every Phase 10
change. Same probe shape as the Phase 9 smoke, abbreviated to status
codes only — full content/header inspection is now covered by
dedicated pytest assertions.

## What changed since the Phase 9 smoke file

The Phase 9 file (`2026-04-25-dashboard-redesign-smoke.md`) captured a
**redesign baseline** — the dashboard had been ported off
`BaseHTTPRequestHandler` to FastAPI/Jinja/HTMX/Alpine and the basic
routes were in place, but several rough edges remained. Phase 10
addressed those:

| Phase 9 state | Phase 10 polish |
|---|---|
| Sidebar identical on every page | Mode-aware (global vs project + back button) |
| Light theme default | Dark theme default (matches TUI) |
| Mixed button styling | Audited: primary blue or ghost transparent, no bare-gray |
| Reports/presentations only via raw file links | Rendered HTML pages via dashboard's markdown helper + reveal.js iframe |
| No experiment-level artifact list | Files list per experiment, inline rendering for text/images |
| Settings = single flat form | Tabbed: 5 project tabs / 4 global tabs |
| Methods page leaked raw JSON | Sortable client-side table |
| Findings = raw JSON dump | Structured page (title, summary, metrics table, references) |
| `/api/*` paths leaked into rendered links | Audited and removed; HTMX/fetch only |
| Project home = sparse summary | "Final outputs" cards surface report/presentation/findings when present |

The Phase 9 manual checklist (registry, project home, settings save,
run launcher, theme toggle, sidebar nav) is implicitly re-verified by
the Phase 10 checklist — all of those flows still need to work for the
new ones to compose on top of them.

## Open follow-ups

Carried forward from the Phase 9 smoke file (still applicable):

- The run launcher's `instructions` form field is accepted by the API
  but not yet plumbed through to the spawned `urika run` subprocess.
- `audience = "standard"` is accepted by the finalize CLI but not by
  core's `VALID_AUDIENCES` set; the dashboard validates against core,
  so the wider value is unreachable through the UI. Pre-existing
  mismatch, out of scope.
- Bearer-token auth is unfriendly to browsers (no native mechanism to
  attach `Authorization` on top-level navigation). Cookie/query-param
  fallback is a future improvement; for now, front with a reverse proxy.

New, surfaced during Phase 10:

- The reveal.js iframe on `/projects/<name>/experiments/<id>/presentation`
  inherits the dashboard's theme variables but reveal.js itself ships
  its own light/dark theme. Visual mismatch is minor but worth a pass
  if/when a presentation theme is themed against the dashboard tokens.
- The "Generate report" button posts and then relies on the same SSE
  stream as `/api/projects/<name>/finalize/stream`. If two browser tabs
  click Generate simultaneously, the second click hits the existing
  `.finalize.lock` and silently no-ops back to the experiment page —
  the user gets no toast. A small "already running" inline notice would
  help; not critical for the polish phase.
- Tabs are pure Alpine — refresh resets to the first tab. For settings
  pages with five tabs, persisting last-selected tab in `localStorage`
  (same pattern as the theme toggle) would be a small UX win.

None of these block the Phase 10 plan being closed out.
