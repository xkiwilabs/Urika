# Urika — Current Status

**Date:** 2026-04-30
**Version:** v0.3.2 (released)
**Branch:** `dev` ahead of `origin/dev` by 0 commits (pushed); `main`
synced and tagged `v0.3.2`.
**Tests:** 2498 passing in focused suites; full pytest --collect-only
reports 2498. TUI subset: 15 in `tests/test_tui/` + 5 in
`tests/test_cli_tui.py`.

The next planning doc is `dev/plans/2026-04-30-v0.4-roadmap.md`.

## v0.3.2 hardening release (just shipped)

Audit-driven release closing four bug families that v0.3.0/0.3.1
shipped:

- **Stop button** — SIGTERM handler in `cli/run.py` (was SIGINT only),
  `os.killpg(getpgid(pid), SIGTERM)` to reach process-group children,
  `_start_reaper` writeback for terminal status, SSE stream emits real
  state from `progress.json`.
- **Dashboard advisor chat no longer auto-fires experiments** —
  non-TTY guard at `_offer_to_run_advisor_suggestions`. Same pattern
  applied to every other destructive prompt
  (run_planning, run, present, report, build-tool).
- **Stale `claude-opus-4-7` settings auto-migrate** on first launch,
  backed up to `~/.urika/settings.toml.pre-0.3.2.bak`. Idempotent via
  `~/.urika/.migrated_0.3.2` marker.
- **`urika new` honors global default model** — was reading legacy
  flat `[runtime].model` only, now prefers
  `[runtime.modes.<mode>].model` (the canonical write path used by the
  dashboard form).
- **Prefer system `claude` CLI over the bundled SDK binary** — the
  bundled binary in `claude-agent-sdk 0.1.45` is v2.1.63 and rejects
  the request schema for newer Anthropic models.
- **Sessions tab now captures dashboard advisor chats** — CLI
  `urika advisor` writes an `OrchestratorSession` after a successful
  exchange (was TUI/REPL-only).
- **5 P0 error-surfacing fixes** — preserve type/traceback/cause across
  SDK adapter, orchestrator loop, dashboard runs Popen failure path,
  reaper thread exception, vault writes during dashboard form save.
- **Cross-interface invariant tests**
  (`tests/test_cross_interface_defaults.py`) pin: CLI wizard's
  `_CLOUD_MODELS` and dashboard's `KNOWN_CLOUD_MODELS` agree;
  `VALID_PRIVACY_MODES` agrees with `_VALID_PRIVACY_MODES`;
  `get_default_runtime(mode)` round-trips dashboard form PUT.
- **Transient + config errors pause-and-resume** rather than failing
  experiments mid-loop. New error categories `transient` (5xx /
  connection / timeout) and `config` (MissingPrivateEndpointError /
  APIKeyRequiredError).
- **`VALID_PRIVACY_MODES` fixed** — was `{open, private, university}`,
  now `{open, private, hybrid}`.

11 commits on `dev`, all pushed to `origin/dev` and `public/main`,
tagged `v0.3.2` (`3e093673`).

## What's built

### Core infrastructure

- **Project lifecycle** — create / register / list / inspect / delete
  / trash with `~/.urika/deletion-log.jsonl`. `core/workspace.py`,
  `core/registry.py`, `core/project_delete.py`.
- **Project Builder** — source scanning, data profiling, multi-file
  dataset support, builder prompts for interactive agent setup.
  `core/project_builder.py`, `core/source_scanner.py`,
  `agents/roles/project_builder.py`.
- **Experiment lifecycle** — create / list / load / progress tracking
  / delete. `core/experiment.py`, `core/experiment_delete.py`.
- **Session management** — start / pause / resume / complete / fail /
  lockfiles with PID-aware probes. `core/session.py`.
- **Progress tracking** — append-only JSONL with best-run queries.
  `core/progress.py`.
- **Labbook** — auto-generated `notes.md` / `summary.md` per
  experiment + `key-findings.md` per project, inline figures.
  `core/labbook.py`.
- **Versioned criteria** — immutable history of project success
  criteria. `core/criteria.py`.
- **Method registry** — tracks methods, metrics, status, supersession
  across runs. `core/method_registry.py`.
- **Usage / cost tracking** — per-project `usage.json` aggregating
  totals + per-session list. `core/usage.py`.
- **Auto-generated README.md** with agent-written summary.
  `core/readme_generator.py`.
- **Reveal.js presentation rendering** from slide JSON.
  `core/presentation.py`.
- **Versioned report writes** with timestamped backups.
  `core/report_writer.py`.
- **Persistent advisor memory** — append-only history + rolling
  context summary in `projectbook/`. `core/advisor_memory.py`.
- **Orchestrator session persistence** — `<project>/.urika/sessions/`
  with auto-prune at 20, preview text. `core/orchestrator_sessions.py`.
- **Tiered secrets vault** — process env → project `.env` → global
  keyring/file. Sidecar metadata, foot-gun guards, full dashboard
  CRUD on global + per-project tabs. `core/vault.py`,
  `core/secrets.py`, `core/known_secrets.py`.
- **Anthropic Consumer Terms §3.7 enforcement** — refuses to spawn a
  Claude SDK subprocess for cloud-bound agents without
  `ANTHROPIC_API_KEY`; scrubs OAuth tokens + Claude Code session
  markers in env passed to subprocess. `core/compliance.py`.
- **Privacy preflight** — bearer-token-aware GET to
  `/v1/models` for auth-protected private endpoints.
  `core/privacy.py`.
- **Notifications bus** — email / Slack / Telegram with remote
  command surface, dashboard test-send, canonical event vocabulary.
  `notifications/`.
- **Update banner** — GitHub Releases check, suppressed in non-TTY
  contexts. `core/updates.py`.
- **Hardware probe + venv detection** — for `urika setup`.
  `core/hardware.py`, `core/venv.py`, `core/anthropic_check.py`.

### Tools (24 built-in)

`tools/`: cluster_analysis, correlation_analysis, cross_validation,
data_profiler, descriptive_stats, feature_scaler, gradient_boosting,
group_split, hypothesis_tests, linear_mixed_model, linear_regression,
logistic_regression, mann_whitney_u, one_way_anova, outlier_detection,
paired_t_test, pca, polynomial_regression, random_forest,
random_forest_classifier, regularized_regression,
time_series_decomposition, train_val_test_split, visualization.

Plus agent-built project-specific tools via `tool_builder` agent.

### Knowledge pipeline

PDF / text / URL extractors → `KnowledgeStore` with keyword search.
Literature agent ingests + cross-references. `knowledge/`.

### Evaluation framework

Per-method leaderboard with primary-metric direction awareness.
9 metrics. `evaluation/`.

### Agent system (12 roles + Orchestrator)

- **Project Builder** — interactive project setup
- **Planning Agent** — designs the next analytical step
- **Task Agent** — writes Python code, runs experiments
- **Evaluator** — read-only scoring against criteria
- **Advisor Agent** — analyzes results, proposes next experiments
- **Tool Builder** — creates project-specific tools at runtime
- **Literature Agent** — searches papers, builds knowledge base
- **Data Agent** — extracts and prepares features in hybrid privacy
  mode
- **Report Agent** — experiment narratives + project summaries
- **Presentation Agent** — reveal.js slide decks from results
- **Project Summarizer** — high-level project synthesis
- **Finalizer** — selects best methods, writes standalone code,
  produces `findings.json`, `requirements.txt`, reproduce scripts
- **Orchestrator** — hybrid deterministic loop (planning → task →
  evaluator → advisor) plus the conversational `OrchestratorChat`
  that can call subagents via Bash

`agents/roles/`, `agents/registry.py`, `agents/runner.py`,
`agents/adapters/claude_sdk.py`.

### Orchestration

- **Experiment loop** — planning → task → evaluator → advisor each
  turn. `orchestrator/loop.py`, `loop_criteria.py`, `loop_display.py`.
- **Meta-orchestrator** — autonomous experiment-to-experiment mode.
  `orchestrator/meta.py`.
- **Finalize sequence** — finalizer → report → presentation → README.
  `orchestrator/finalize.py`, `loop_finalize.py`.
- **Conversational chat** — `OrchestratorChat` maintains conversation
  state, calls subagents via Bash, recommends slash commands for
  long-running operations. `orchestrator/chat.py`.

### Interfaces

Three peer interfaces sharing the same on-disk project state:

- **CLI** — `urika <command>`, ~25 commands. `cli/`. Every command
  has a `--json` flag for scripting.
- **Textual TUI (default)** — `urika` with no args. Three-zone layout
  (OutputPanel + InputBar + ActivityBar + StatusBar), background
  Workers for agent commands, OutputCapture routing print/click.echo
  to the panel, stdin bridge for interactive prompts (click.prompt /
  input), tab completion with contextual suggester. `tui/`.
- **Classic REPL fallback** — `urika --classic`. `repl/`.
- **Dashboard** — `urika dashboard [project]`. FastAPI multi-page app
  with HTMX + Alpine. Run launcher modal, live SSE log streaming,
  advisor chat, sessions list, secrets/vault CRUD, settings forms,
  notifications test-send, danger zones, light/dark theme, optional
  bearer-token auth. `dashboard/`.

### RPC server

JSON-RPC server for external tooling. `rpc/`.

### Real-world testing

Tested on DHT target selection data (35 experiments, 288 methods),
plus other behavioral / cognitive / linguistic datasets per
`testing-plan.md`.

## CLI commands (25+)

`new`, `list`, `status`, `inspect`, `delete`, `update`, `experiment`
(create/list/delete), `run`, `results`, `methods`, `tools`, `report`,
`logs`, `knowledge`, `advisor`, `evaluate`, `present`, `plan`,
`finalize`, `build-tool`, `criteria`, `usage`, `summarize`,
`dashboard`, `setup`, `config` (api-key/secret/notifications/
endpoints/...), `notifications`, `venv` (create/status), `tui`.

`--classic` flag on `urika` switches to the classic REPL. Every
command supports `--json` for non-TTY scripting.

## Deferred to v0.4

See `dev/plans/2026-04-30-v0.4-roadmap.md` for the full track
breakdown. Highlights:

- **SecurityPolicy enforcement** via SDK `can_use_tool` hook
  (advisory-only today; v0.3.2 CHANGELOG promised this).
- **Bash allow-list hardening** — `urika ; rm -rf /` currently
  matches the prefix; closes alongside SecurityPolicy.
- **Multi-provider thin abstraction** — abstraction is ~60% real;
  v0.4 closes the seam so contributors can add OpenAI / ADK / Pi
  adapters. Second working adapter end-to-end deferred to v0.5.
- **Project memory Phase 1** — design locked at
  `2026-04-28-project-memory-design.md`; not built.
- **GitHub integration** — user-named feature; thin scope (`gh` CLI
  shellout) for v0.4, thick (pygit2 + device-flow OAuth + dashboard
  Connect button) for v0.5.
- **Experiment comparison view** — table-stakes feature for
  experiment-tracking; data is on disk, just needs a UI.
- **Shell completion**, **dataset hash + drift detection**,
  **cost-aware budget** — small user-facing wins.
- **TUI v2 polish** — replace private-Textual-attribute access in
  `_TuiWriter._post_line`, regression test for orchestrator-chat →
  Bash → urika → SDK env-scrub chain through the TUI worker, Esc-key
  binding parity with CLI pause module.

Plus the consistency-sweep PR for ~12 small P1s carried over from the
v0.3.2 audits (audience default unification, max_turns default
unification, email password masked in CLI, surface swallowed
exceptions across the loop / parsing / CLI, dashboard form
validation, etc.).

## Active plan docs

After the 2026-04-30 cleanup, `dev/plans/` holds:

- `2026-04-10-agent-runtime-abstraction-design.md` (Track 3 reference)
- `2026-04-10-agent-runtime-implementation.md` (Track 3 reference)
- `2026-04-24-release-polish.md` (Track 6 + LiteLLM-as-multi-provider
  alternative)
- `2026-04-27-feature-priorities.md` (still-active prioritization)
- `2026-04-28-project-memory-design.md` (Track 2 — locked,
  unimplemented)
- `2026-04-30-v0.4-roadmap.md` — **canonical v0.4 scope**
- `2026-04-30-securitypolicy-enforcement.md` (Track 1)
- `2026-04-30-github-integration.md` (Track 5)
- `2026-04-30-multi-provider-thin-abstraction.md` (Track 3)
- `2026-04-30-experiment-comparison-view.md` (Track 4)
- `2026-04-30-dataset-hash-drift.md` (Track 4)
- `2026-04-30-cost-aware-budget.md` (Track 4)
- `2026-04-30-shell-completion.md` (Track 4)

73 stale designs (v0.1 / v0.2 / pre-v0.3.2 shipped designs +
completed smoke checklists) moved to `dev/archive/plans/`.

## Cleanup outstanding

- **`dev/archive/typescript-tui/`** (~186 MB / 7,649 files) — the
  v2-TS-pivot was abandoned 2026-04-12 per
  `project_tui_v2_status.md`. Listed for deletion in
  `2026-04-24-release-polish.md` Phase 1 Task 1.1, never executed.
  Drop in a Track 1 PR or a standalone `chore` commit.
