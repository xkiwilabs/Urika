# UI Polish + CLI Parity Implementation Plan (2026-04-27)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Three related issues found during smoke testing of the running-ops + log-streaming work — auto-dismiss of running-state UI, dashboard "+ New experiment" form mismatch with the CLI, and a "Test endpoint" button for private model endpoints.

**Architecture:** Polling for state changes (no websockets — stays consistent with existing SSE-only stack). CLI parity is one-way: dashboard reads `urika run --help` as the source of truth.

**Tech stack:** Existing FastAPI + HTMX + Alpine + Jinja. No new dependencies.

---

## Phase P1 — Auto-dismiss running-state UI on completion

### The problem

The Phase B running-ops work made the project banner ("Running: summarize") and the per-button running state ("Summarize running… view log") work correctly while an op is in flight. But once the op completes, neither updates without a manual page reload.

Concretely:
- User clicks Summarize → redirected to log page → log streams → completion event fires → CTAs appear on the log page (this part works).
- User navigates to project home BEFORE clicking the CTA → the "Summarize running…" button is still showing, and the project-wide banner still has a "summarize" chip — both stale until reload.
- This violates the contract the running-ops feature establishes ("buttons reflect current reality everywhere").

### The fix

Server side: nothing to change. `list_active_operations` already correctly reports the post-completion state (the `.lock` file is deleted by the drainer thread when the subprocess exits, so the helper returns an empty list).

Client side: each project-scoped page polls a tiny JSON endpoint every ~5s for the current set of active ops. When the set changes, the page does an HTMX swap of the banner + the buttons that depend on running state.

### Implementation

**B1.1: tiny "active ops" JSON endpoint.** Add `GET /api/projects/<n>/active-ops` returning `[{"type": ..., "experiment_id": ..., "log_url": ...}, ...]`. Same shape as `list_active_operations` already produces. Serve it as JSON; no template work.

**B1.2: client-side poller.** Add a small script (`urika-active-ops-poll.js`) loaded in `_base.html`:
- On every project-scoped page (detected by checking whether the banner element exists at page-load time), set up a 5s `setInterval`.
- On each tick, fetch `/api/projects/<n>/active-ops`.
- Compute a stable signature (e.g., sorted-JSON string of the response).
- If the signature changed since last tick, do `htmx.ajax('GET', window.location.href, {target: 'body', swap: 'morph:outerHTML'})` — i.e., re-render the current page in place. (Alternative: provide a more targeted swap of just the banner + button blocks, but full-page is simpler and the cost is negligible since these pages are small.)

The 5s interval is the right balance: fast enough that a completed op clears within seconds, slow enough that the network noise is invisible. Configurable via a JS constant.

**B1.3: prevent infinite poll loops.** Use `document.hidden` (page visibility API) to pause polling when the tab is hidden — saves bandwidth and stops accidental polling forever in stale tabs.

### Tests

- `test_active_ops_endpoint_returns_empty_when_idle`
- `test_active_ops_endpoint_returns_running_op_shape`
- `test_active_ops_endpoint_404_unknown_project`
- `test_base_template_includes_poll_script_on_project_pages`
- `test_base_template_omits_poll_script_on_global_pages` (no project context = no banner = no need to poll)

---

## Phase P2 — New Experiment form: match the CLI

### The problem

The dashboard's "+ New experiment" modal asks for:
- Experiment name
- Hypothesis
- Mode
- Audience
- Max turns
- Instructions

This doesn't match how `urika run` actually works. `urika run` doesn't take a name + hypothesis as primary inputs — those are derived from the planning agent's output during the run, OR from `--instructions` which is the steering input. The current form is a relic of an earlier design.

### The fix

Step 1: full audit of `urika run` CLI options. Read `src/urika/cli/run.py` end-to-end and produce a flag-by-flag inventory:
- Required positional args
- Every `--flag` with its semantics, default, and validation
- Conditional flags (only relevant in certain modes)
- Side effects (`--auto`, `--review-criteria`, `--resume`, `--draft`, etc.)

Step 2: redesign the modal. The form should:
- NOT ask for "experiment name" or "hypothesis" — those come from the planning agent during the run.
- Expose every relevant CLI flag in the same grouping the CLI uses.
- Default values match the CLI's defaults, NOT hardcoded "standard"/etc.
- Validate client-side where the CLI validates server-side (e.g. max_experiments must be positive int).

Step 3: update `spawn_experiment_run` in `runs.py` if any new flag is missing from the spawn helper's pass-through list.

Step 4: rewrite the relevant tests (test_api_run.py + test_pages_experiments.py).

### What the new modal probably looks like

Based on prior knowledge of `urika run`:

```
+ New experiment

  Instructions (optional, multi-line textarea)
    "What should this experiment focus on? Describe the question you
     want answered or the approach you want tried."

  Audience            [project default: standard ▼]
  Mode                [project default: exploratory ▼]   <- note: the project's mode, not the experiment

  Advanced (collapsible)
    Max turns                 [int, default = 5]
    Auto mode                 [☐] (run multiple experiments unattended)
      Max experiments         [int, default = 10] (only when auto is on)
    Review criteria first     [☐] (let advisor revise success criteria before this run)
    Resume                    [☐] (continue an interrupted run)

  [Cancel]  [Run experiment]
```

Verify each item against actual CLI behavior in Step 1 before locking the form.

### Tests

- `test_new_experiment_form_has_no_name_or_hypothesis_fields` (regression — these were the wrong questions)
- `test_new_experiment_form_pre_selects_project_audience`
- `test_new_experiment_form_pre_selects_project_mode`
- `test_new_experiment_form_advanced_section_is_collapsible`
- `test_new_experiment_modal_forwards_every_relevant_flag` (parameterized — each flag → spawn call kwarg)
- `test_run_cli_accepts_every_flag_the_modal_offers` (parity check — for each flag the modal posts, ensure the CLI accepts it)

---

## Phase P3 — Test endpoint button for private models

### The problem

Privacy/Models settings let a user configure a private endpoint (`base_url`, `api_key_env`, `default_model`). There's currently no way to verify the endpoint is reachable without firing a real agent run. `_test_endpoint` exists in `src/urika/cli/_helpers.py` (line 160) — used by interactive `urika config`. Dashboard has nothing.

### The fix

**P3.1: server-side test endpoint.** Add `POST /api/settings/test-endpoint` that takes JSON `{"base_url": "...", "api_key_env": "..."}` and:
- Reuses `_test_endpoint(url)` from `urika.cli._helpers` (already returns bool).
- Optionally also checks the env var is set (returns separate bool).
- Returns `{"reachable": bool, "api_key_set": bool, "details": str}`.

3-second timeout (already in `_test_endpoint`). Never blocks for long.

**P3.2: client-side button.** On Global Settings → Privacy tab and Project Settings → Privacy tab, next to each endpoint definition: a small "Test" button.
- Click → POST to the test endpoint with the current form values (read from Alpine state, not from saved TOML — we want to test what the user is about to save).
- While testing → button disables, dot pulses, "Testing…" label.
- On result → inline status:
  - `✓ Reachable` (green)
  - `✗ Unreachable: <details>` (red)
  - Plus a separate row: `API key URIKA_API_KEY: ✓ set` or `✗ unset`

Tested values are never persisted by this endpoint — pure read-only check.

### Tests

- `test_endpoint_test_returns_reachable_for_mock_200`
- `test_endpoint_test_returns_unreachable_for_connection_refused`
- `test_endpoint_test_returns_unreachable_for_timeout`
- `test_endpoint_test_reports_api_key_unset`
- `test_endpoint_test_reports_api_key_set` (use monkeypatch.setenv)
- `test_endpoint_test_button_renders_on_global_settings_privacy_tab`
- `test_endpoint_test_button_renders_on_project_settings_privacy_tab`
- `test_endpoint_test_endpoint_does_not_persist_values` (a separate test — POSTing should not write to settings.toml)

---

## Execution order

1. **P1 (auto-dismiss)** — small, self-contained, immediate UX win. ~½ day.
2. **P2 (new experiment redesign)** — biggest scope. CLI audit first, then form redesign, then tests. Likely a full day. Potentially needs user feedback on the proposed form layout BEFORE locking it in. Recommend: do the audit, share the proposed form with the user, then implement.
3. **P3 (test endpoint)** — small, mechanical. ~½ day.

Total: ~2 days of work. NO `Co-Authored-By:` lines on any commit. Follow the same patterns as the running-ops phases (TDD, ruff clean on changed files, single phase = single commit).

## After this plan completes

Per the user note: project creation via the dashboard is the next manual smoke test. That'll happen after these three are done.
