# Running Operations + Log Streaming — Smoke Test Results

Companion to `dev/plans/2026-04-27-running-ops-and-log-streaming.md`.
Captures the state of automated and manual verification on 2026-04-27
after the running-ops + log-streaming work shipped end-to-end.

## Automated verification

```
pytest -q
2098 passed in ~57s
```

Baseline at start of the running-ops feature: 2025 passing.
Net change: **+73 tests** across the six commits.

Breakdown by phase:

- **B1** (`list_active_operations` helper): +15 tests in
  `test_active_ops.py` — happy path per op type, stale PID, empty
  lock, filelock mutex ignored, missing project path, multi-op,
  most-specific match wins.
- **B2** (idempotent spawn endpoints): +18 tests across
  `test_api_summarize.py`, `test_api_finalize.py`,
  `test_api_build_tool.py`, `test_api_run.py`, `test_api_evaluate.py`,
  `test_api_report.py`, `test_api_present.py` — HTMX redirect, 409
  JSON, cross-experiment isolation.
- **B3** (buttons reflect running state): +17 tests in
  `test_pages_project.py` and `test_pages_tools_criteria.py` —
  idle/running for each button type.
- **B4** (running-ops banner): +7 tests in
  `test_active_ops_banner.py` — absent without ops, multi-op,
  cross-page visibility, self-link suppression, experiment-id chip,
  global-page absence.
- **B5.1** (shared thinking partial): +7 tests in
  `test_thinking_partial.py` — partial renders, JS file served,
  every log page includes the partial.
- **B5.2** (completion CTAs): +9 tests across
  `test_api_artifacts_projectbook.py` (4) and
  `test_pages_project.py` / `test_pages_tools_criteria.py` (5) —
  artifact probe shape, per-template CTAs, no-probe for tool-build
  log.

## Commit log (dev branch)

```
ff5d5aa6 feat(dashboard): completion CTAs on summarize / finalize / build-tool log pages
7e182917 feat(dashboard): shared animated thinking placeholder across advisor + log pages
a1be4bda feat(dashboard): persistent running-ops banner across project pages
8f724182 feat(dashboard): buttons reflect running state and link to live log
cdad3254 feat(dashboard): spawn endpoints redirect to existing log when op already running
db0f9975 feat(dashboard): list_active_operations helper detects live agent locks
fefbc0ba docs(plan): running ops + log streaming
```

## Manual checklist — pending

These verify the end-to-end flow against a real `urika dashboard` on
a project with at least one experiment.

### Live-stream + buffering (Phase A regression check)

- [ ] Start any agent op (`Summarize`, `Finalize`, `Re-generate report`,
      etc.). The log page should stream lines as the agent works —
      tool calls, agent messages, etc. — within a few seconds, not
      dump everything at the end.
- [ ] The thinking placeholder (urika-blue spinner + rotating verbs)
      shows above the log while connecting. As soon as the first SSE
      line arrives, the placeholder disappears.
- [ ] Verb cadence feels natural — not robotic 3s ticks. The verbs
      change at slightly different intervals each time.

### Idempotent spawn (B2)

- [ ] Click **Summarize project**. Get redirected to the live log.
- [ ] Hit Back. The button now reads **Summarize running… view log**
      with a pulsing dot.
- [ ] Click that button. You land directly on the live log (no new
      spawn — verify by checking PID in `projectbook/.summarize.lock`
      is unchanged).
- [ ] From a curl (no `hx-request` header):
      `curl -X POST http://localhost:<port>/api/projects/<n>/summarize`
      returns 409 with `{"status":"already_running","log_url":...}`.
- [ ] Once the op completes, the button label flips back to
      **Summarize / Re-summarize** and clicking it opens the modal.

### Per-button running state (B3)

For each of these triggers, verify the running-link variant appears
when its op is in flight and the modal-button variant otherwise:

- [ ] **Project home** → Summarize, Finalize.
- [ ] **Experiment detail** → Evaluate, Generate report, Generate
      presentation. Per-experiment scoping: a running evaluator on
      `exp-001` shows the running link on `exp-001`'s page but NOT
      on `exp-002`'s page.
- [ ] **Tools (project scope)** → `+ Build tool` flips to running.
      Global `/tools` page never shows the button (or its running
      variant).
- [ ] **Experiments list** → `+ New experiment`. Any running
      experiment in the project blocks the button (project-scoped
      by design).

### Persistent running-ops banner (B4)

- [ ] Start Summarize. Navigate to Methods, Tools, Knowledge, Data,
      Usage, Settings, Advisor — every project page shows the
      "Running:" banner with a clickable "summarize" chip.
- [ ] Click the chip from any of those pages → land on the live log.
- [ ] On the summarize log page itself, the banner still renders if
      OTHER ops are running, but the self-pointing chip is hidden.
- [ ] Start a second op concurrently (e.g. an experiment run on
      `exp-001` while summarize is still running). Banner shows two
      chips: "summarize" and "run · exp-001". Both clickable.
- [ ] Visit `/projects` (global list) → no banner.
- [ ] Visit `/settings` (global) → no banner.

### Completion CTAs (B5.2)

- [ ] Summarize completes → log page shows "View summary" button
      below "Back to project home". Clicking opens the rendered
      summary.
- [ ] Finalize completes → log page shows "View report",
      "Open presentation ↗" (new tab), "View findings" buttons —
      whichever artifacts now exist.
- [ ] Build tool completes → log page shows "Back to tools →".
- [ ] If Finalize fails partway, only the artifacts that DID write
      surface as buttons (the others stay hidden).

### Stale-lock recovery

- [ ] While an op is running, hard-kill the urika subprocess
      (`kill -9 <pid>` from a terminal). Reload the dashboard. The
      banner clears, the button reverts to its idle state, and you
      can spawn a fresh op without manually deleting the lock file.
- [ ] Touch a `.summarize.lock` (empty file) — should not block;
      the banner stays clear.
- [ ] Touch a `criteria.json.lock` (filelock mutex shape) — should
      never appear in the banner; doesn't block deletion either.

### Negative / safety

- [ ] No `/api/*` URL is reachable by clicking through the project
      UI on any new running-state surface — banners and buttons all
      link to user-facing pages, not the API.
- [ ] Banner self-link suppression handles the per-experiment log's
      `?type=` correctly: on `/log?type=evaluate`, an evaluate chip
      for the same experiment is hidden but a run chip for the same
      experiment (different `?type`) still renders.
