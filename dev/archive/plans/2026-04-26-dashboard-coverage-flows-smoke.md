# Dashboard Coverage & In-Browser Flows — Smoke Test Results

Companion to `dev/plans/2026-04-26-dashboard-coverage-flows.md`. Captures the
state of automated and manual verification on 2026-04-26, after the
Phase 11 pass (modal-driven New Project / New Experiment, advisor chat,
finalize button, knowledge add, tools + criteria viewers, project-level
Privacy/Notifications full edit, mid-run prompt scaffolding, and
targeted visual polish).

## Manual browser checklist — pending

These are the user-facing checks that pytest cannot exercise. Walk
through them in a real browser at a real `urika dashboard` against a
project with at least one experiment, an advisor history, and a
populated knowledge base.

### Modals & lifecycle flows

- [ ] `+ New project` button on `/projects` → modal opens → submit
      creates a project → redirect to project home.
- [ ] `+ New experiment` button on `/projects/<n>/experiments` → modal
      opens → submit starts run → redirect to live log → log streams.
- [ ] Project home: **Finalize project** button → kicks off finalize,
      redirects to `/projects/<n>/finalize/log`, log streams, finishes
      cleanly.
- [ ] Knowledge page: **+ Add knowledge** button → modal → enter a
      path/URL → submit → ingested entry shows up at the top of the
      list.

### Advisor chat

- [ ] `/projects/<n>/advisor` renders the persistent transcript.
- [ ] Type a question, hit Send → answer appears in the transcript
      without a full page reload.
- [ ] Reload the page → history is still there (file-backed by
      `projectbook/advisor.json`).

### Tools & criteria viewers

- [ ] `/projects/<n>/tools` renders the registered tools list (built-ins
      plus any tool-builder additions).
- [ ] `/projects/<n>/criteria` renders the current `success_criteria`
      plus version history below it.

### Project settings — Privacy + Notifications

- [ ] Settings → **Privacy**: pick "Override global", set mode=private,
      save → `urika.toml` has a `[privacy]` block. Reload page → values
      persist.
- [ ] Switch back to "Inherit" → save → `[privacy]` block removed from
      `urika.toml`. Reload → picker returns to "Inherit".
- [ ] Settings → **Notifications**: per-channel inherit / enabled /
      disabled radios for slack / email / desktop. Extra recipients list
      editable. Save → `urika.toml` updated, reload preserves values.

### Visual polish (Phase 11A)

- [ ] **Theme toggle** is in the sidebar **bottom** (not the page
      header). Click → swap. Reload → preserved.
- [ ] **URIKA wordmark** in the sidebar header is bigger, centered, and
      accent-coloured.
- [ ] **Sidebar links** are muted by default, accent on hover, and
      accent + tinted background when on the matching page.
- [ ] **Status pills**: completed = green, running = blue, paused =
      yellow, failed = red, pending = gray. Tokens swap with the theme.

### Mid-run interactive prompts (when orchestrator support lands)

- [ ] Live log: when the orchestrator emits `event: prompt`, an inline
      answer form appears below the streamed log.
- [ ] Submitting the form continues the run (and the prompt form is
      replaced by an inline confirmation).
- [ ] Until the orchestrator side wires this through, only the SSE
      event handler + form rendering can be smoke-tested via a manual
      `event: prompt` injection.

### Cross-cutting

- [ ] No `/api/*` link is reachable by clicking through the UI (only via
      HTMX/fetch internally). Same audit as Phase 10.

## Automated verification

### pytest sweep

```
pytest -q
1738 passed, 101 warnings in 49.57s
```

Up from 1655 at the close of the Phase 10 polish smoke. Net change:
**+83 tests** added across Phase 11. Breakdown by phase:

- 11A (visuals): theme-toggle relocation, wordmark sizing, sidebar
  active-state and hover contracts, status-pill semantic colour tokens.
- 11B (modal primitive + New Experiment): `modal()` macro tests, button
  + modal rendering, the new POST flow, lock-aware button hiding.
- 11C (New Project modal + builder subprocess): `POST /api/projects`
  validation and subprocess-launch tests, redirect on success.
- 11D (project Privacy + Notifications full edit): inherit-vs-override
  state, toml round-trips, per-channel radio persistence.
- 11E (advisor + finalize + knowledge + tools + criteria): chat
  endpoint append-and-fragment, finalize button + log page,
  `POST /api/.../knowledge` ingestion, tools + criteria viewers.
- 11F (mid-run prompts): SSE `event: prompt` shape, answer form
  rendering, `POST /respond` endpoint contract.

### Dashboard package

```
pytest tests/test_dashboard/ -q
281 passed, 99 warnings in 7.03s
```

Up from 198 at the close of the Phase 10 polish smoke (**+83 dashboard
tests**, accounting for all of the Phase 11 net delta — every new test
this phase landed inside `tests/test_dashboard/`).

### Server startup smoke

```
$ timeout 6 python -c '<startup harness>'
Started: True on port 54215
GET /healthz:        200
GET /projects:       200
GET /settings:       200
GET /static/app.css: 200
```

Confirms: app factory, project list page, global settings page, and
the design-system CSS still serve correctly after every Phase 11
change. Same probe shape as the Phase 10 smoke.

## What changed since the Phase 10 smoke file

Phase 10 took the dashboard from "browseable" to "polished" — sidebar
bifurcation, dark default, audited buttons, rendered artifacts,
tabbed settings, no-JSON-dump rule, project-home final-output cards.
Phase 11 took it from "polished" to "primary interface": every common
project lifecycle event now has a browser surface, advisor chat lives
in the dashboard alongside the CLI/TUI, and the remaining visual rough
edges got cleaned up.

| Phase 10 state | Phase 11 additions |
|---|---|
| `/projects/<n>/run` page for launching runs | **+ New experiment** modal on the experiments list (run page deprecated) |
| No way to create a project from the browser | **+ New project** modal + `POST /api/projects` |
| Advisor only via CLI/TUI | `/projects/<n>/advisor` chat panel, shared transcript |
| Finalize only via CLI | **Finalize project** button + `/projects/<n>/finalize/log` page |
| Knowledge add only via CLI | **+ Add knowledge** modal + `POST /api/.../knowledge` |
| Tools + criteria — no surface | `/projects/<n>/tools` + `/projects/<n>/criteria` viewers |
| Project Privacy/Notifications view-only | Full edit with inherit-vs-override, persisted to `urika.toml` |
| Run live log streamed only stdout | SSE extended with `event: prompt` for mid-run questions |
| No mid-run answer surface | Inline answer form + `POST /respond` endpoint (orchestrator side pending) |
| Theme toggle in page header | Theme toggle in sidebar footer |
| Plain sidebar wordmark | Big centered URIKA wordmark in accent colour |
| Sidebar links plain | Muted / hover / active-state styling driven by request path |
| Status pills uniform | Semantic colour tokens (success / info / warning / danger / neutral) |

The Phase 10 manual checklist is implicitly re-verified by the
Phase 11 checklist — every flow from Phase 10 still has to work for the
new modals and chat panels to compose on top of them.

## Open follow-ups

Carried forward (still applicable):

- Bearer-token auth is unfriendly to browsers. Cookie/query-param
  fallback remains a future improvement.
- Tabs are pure Alpine — refresh resets to the first tab. Persisting
  last-selected tab in `localStorage` would be a small UX win.
- The reveal.js iframe still inherits its own light/dark theme,
  separate from dashboard tokens. Visual mismatch is minor.

New, surfaced during Phase 11:

- The **mid-run prompt** SSE event + answer form is fully wired on the
  dashboard side, but the orchestrator does not yet emit `event: prompt`
  during runs. Until that lands, the inline form is reachable only by
  injecting the event manually for testing. Tracked separately as the
  orchestrator-side follow-up.
- `POST /api/projects` runs `urika new --json --non-interactive`, which
  in turn shells out to the project-builder agent. Subprocess startup
  cost is non-trivial (~2–4s); the modal currently shows a spinner and
  blocks the user until the redirect. A streaming progress channel
  would be a nicer UX once the builder agent surfaces partial output,
  but it's not on the critical path.
- The Finalize button currently fires from the project home only. A
  per-experiment finalize entry point exists already (the "Generate
  report" button on experiment detail), so the project-level button is
  intentionally additive — not a duplicate. Worth a UX pass to make the
  distinction obvious if users get confused.
- Tools and criteria pages are read-only by design. Editing tools means
  invoking the tool-builder agent; editing criteria means
  `urika criteria edit`. Surfacing those as dashboard flows is out of
  scope for Phase 11 and probably belongs in a future "agent invocation
  from the dashboard" phase.

None of these block Phase 11 being closed out.
