# Changelog

All notable changes to Urika will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.2] - 2026-05-07

Hardening release driven by a comprehensive 6-surface code audit
(CLI, TUI, Dashboard, Core, Code health, Tests) plus two beta-user
bug reports (advisor→/run silent failure, agent simulating data on
first experiments). Eleven internal "packages" of fixes, 2844 tests
passing (+161 new), zero regressions.

### Security

- **OAuth scrub completeness** — `core/compliance.py::_OAUTH_TOKEN_VARS`
  was defined but never used; only two of nine OAuth/identity tokens
  were blanked when spawning the bundled `claude` CLI subprocess.
  Critically, `CLAUDE_CODE_OAUTH_REFRESH_TOKEN` was left live, so
  the access-token blank could be re-minted by the subprocess. Now
  the constant is iterated and includes all 9 OAuth tokens (refresh,
  identity, websocket-auth, file-descriptor variants) + 9 nested-
  session markers (CLAUDE_CODE_SESSION_ID/KIND/NAME/LOG, REMOTE,
  TMUX, AGENT, ACTION, RESUME).
- **Privacy fail-closed on corrupt config** — `core/privacy.py` and
  `agents/config.py` no longer silently default to "open mode" when
  `urika.toml` fails to parse. `FileNotFoundError` → open
  (legitimate), `TOMLDecodeError` → fail-closed with a clear error.
- **Endpoint hostname check** — `agents/config.py:194` URL match
  changed from substring (`"anthropic.com" in url`) to
  `urlparse().hostname` + suffix match. Closes
  `http://anthropic.com.evil.com` getting cloud's larger context-
  window allocation.
- **Vault file race closed** — `vault.py` `FileBackend` now creates
  files via `os.open(O_CREAT|O_EXCL, 0o600)` instead of write-then-
  chmod. No window between file creation and mode set during which
  another local user could read.
- **`urika new --json` requires `--overwrite`** — pre-fix the
  flag-less `--json` path silently `shutil.rmtree`'d any existing
  project of the same name (data loss for scripted-create users).

### Added

- **Atomic JSON state writes** — new `core/atomic_write.py`
  (`write_text_atomic`, `write_json_atomic`) using temp-file +
  `os.replace` + parent-dir fsync. Migrated 9 sites: `registry.py`,
  `orchestrator_sessions.py`, `session.py`, `advisor_memory.py`,
  `progress.py`, `criteria.py`, `method_registry.py`, `usage.py`,
  three sites in `vault.py`. SIGTERM mid-write no longer corrupts
  state files. Advisor history corrupt-file is preserved as
  `.corrupt-<ts>.json` instead of silently zeroed.
- **Real-data-only enforcement** — `task_agent_system.md` and
  `data_agent_system.md` now have explicit "Critical: Real Data
  Only" sections forbidding data simulation, fabrication, or
  substitution. Lists canonical forbidden patterns
  (`np.random.normal` for inputs, `sklearn.datasets.make_*`,
  hardcoded `pd.DataFrame({...})` literals, `simulate_*` /
  `fake_*` / `dummy_*` helpers, "simulating because too long"
  comments) with explicit allowed-uses-of-randomness carve-out for
  legitimate train/test shuffling, bootstrap resampling FROM real
  data, model init, CV seeds. STOP-and-report instead of substitute
  when data genuinely cannot be loaded.
- **Runtime data-integrity scanner** — new `core/data_integrity.py`
  scans each turn's method scripts for real-data signals
  (`pd.read_*`, `np.load`, project `data_paths` basenames, urika
  tool imports) and synthetic-data signals (`make_*`, `simulate_`
  helpers, "synthetic data" comments). Emits a SUSPECT warning to
  the live log + dashboard SSE when a turn produces synthetic-only
  runs, so the suspicion lands in `run.log` rather than being
  silently recorded as a real result.
- **`urika unlock <project> [exp_id]`** — new CLI command for
  clearing stale lockfiles. Safe by default: refuses to unlock if
  the lock's PID is alive AND its process name (via
  `/proc/<pid>/comm`) looks like Urika. `--force` overrides for
  PID-recycle false positives. Closes the user-reported "stops
  with lockfile message on a project from an older release" flow.
- **`/setup` slash registered in TUI/REPL** — pre-fix `"setup"`
  was listed in `tui/app.py::_WORKER_COMMANDS` but had no handler;
  typing `/setup` printed "Unknown command".
- **Five missing slash commands wired** — `/summarize`,
  `/sessions [list|export]`, `/memory [list|show|delete]`,
  `/venv [create|status]`, `/experiment-create` now reachable from
  the TUI/REPL with the same effect as the equivalent shell
  commands.
- **getpass bridge for the TUI** —
  `tui/agent_worker._install_getpass_bridge` patches
  `click.termui.hidden_prompt_func` once at import. Pre-fix
  `click.prompt(hide_input=True)` (4 sites in `cli/config.py` for
  API-key entry plus `cli/config_notifications.py` for SMTP
  password) called `getpass.getpass`, which on POSIX opens
  `/dev/tty` directly, bypassing both `sys.stdin` and the TUI's
  stdin bridge — the prompt blocked indefinitely.
- **Vendored htmx, alpine, chart.js** under
  `dashboard/static/vendor/`. Dashboard now works offline / air-
  gapped. Pre-fix these loaded from unpkg.com / cdn.jsdelivr.net.
- **Sidebar links for Compare + Criteria** — both pages rendered
  correctly but were reachable only via deeplink.
- **SSE disconnect detection** — all 5 SSE endpoints
  (`/runs/<id>/stream`, `/finalize/stream`, `/summarize/stream`,
  `/tools/build/stream`, `/advisor/stream`) now poll
  `request.is_disconnected()`. Pre-fix a closed browser tab left
  the generator polling disk every 0.5s until the lockfile
  disappeared, leaking coroutine slots under load.
- **Per-project `context_window` + `max_output_tokens`** form
  fields on the dashboard's project Settings → Privacy tab. The
  v0.4.1 fields were on global Settings only; the per-project API
  parser silently dropped them when typed in the per-project form.
- **`pytest` markers `slow` and `integration`** registered in
  `pyproject.toml`. Long-running SSE tests + the pytest-wrapped
  smoke harness (`tests/test_smoke/test_smoke_open.py`) marked
  appropriately. Default `pytest` is now ~1 minute (down from ~7).
- **`urika logs` actually tails `run.log`** — pre-fix the
  docstring claimed "Show experiment run log" but the body only
  printed `progress.json` runs/metrics; `run.log` was never
  opened. `--summary` preserves the legacy progress-summary view;
  `--tail N` controls trailing line count.

### Changed

- **Empty legacy lockfiles treated as stale unconditionally** —
  pre-v0.3 (commit 2fdae4b4) `acquire_lock` used `path.touch()`
  which created EMPTY lock files. Current release ALWAYS writes
  the PID. Pre-fix the acquire-lock code refused for 6 hours
  after an empty lock's mtime — catching brand-new releases
  bouncing off ancient locks left over from pre-v0.3 crashes.
  Now: any empty lock = pre-v0.3 leftover = stale, clean it up
  immediately. Better error message in `start_session` points the
  user at the new `urika unlock` recovery command.
- **`/advisor` invokes the actual `advisor_agent` role** — pre-fix
  `cmd_advisor` delegated to `_handle_free_text` which runs
  `OrchestratorChat` (a different agent with a different system
  prompt and no access to `advisor_memory`). The shell `urika
  advisor` always invoked the real role; the slash now matches.
  Persists exchanges via `advisor_memory.append_exchange`,
  parses suggestions on the response.
- **TUI free-text injection blocked while busy** — pre-fix the
  TUI queued the text and replayed it after the worker exited,
  with stale-context, drain-race, and silent-bury problems plus
  inconsistency with the REPL's blocking-prompt model. Now: a
  one-line panel hint pointing the user at /stop, /pause, or
  "open another terminal for a parallel chat." Slash dispatcher
  also rejects free-text during non-/run agents (where queued
  text was previously dead-stored). Reader-feed and queue-during-
  /run paths preserved (legitimate uses for click.prompt
  injection inside the orchestrator loop).
- **/pause cooperative flag only written during /run or /resume**
  — pre-fix typing `/pause` during `/finalize` or `/report` wrote
  a `pause_requested` flag that the next /run picked up and
  immediately paused on. Now `cmd_pause` checks
  `active_command in ("run", "resume")`.
- **/resume preserves `advisor_first` + `review_criteria`** — pre-
  fix /resume silently dropped both flags to False even when the
  original /run had them on. Now read from `[preferences]` in
  `urika.toml` and forwarded through `ctx.invoke(cli_run, ...)`.
- **Remote `/run` accepts `--no-advisor-first` / `--advisor-first`**
  — pre-fix the worker hardcoded `advisor_first=True` for remote
  callers, leaving Slack/Telegram users unable to opt out.
- **Remote command map driven by the live registry** — pre-fix
  `_REMOTE_COMMAND_MAP` was a hardcoded list of 9 names that
  drifted away from the registry; new v0.4.2 slashes were silently
  unreachable from Slack/Telegram. Now built from `GLOBAL_COMMANDS
  ∪ PROJECT_COMMANDS` minus an explicit `_REMOTE_BLOCKED_COMMANDS`
  block-list (interactive editors, destructive admin actions).
- **REPL `/summarize` runs as an agent command** — pre-fix it ran
  on the main thread and blocked the prompt for the duration of a
  multi-minute agent call.
- **REPL parses advisor suggestions on free-text reply** — pre-fix
  `_handle_free_text` defined `_offer_to_run_suggestions` a few
  lines below but never called it; the REPL had the same advisor→
  /run silent-fail-to-pending bug as the TUI. Now both UIs are
  parity-locked on the suggestion path.
- **Update banner suppressed under `--json`** — pre-fix a user
  running `urika list --json` from an interactive TTY got a banner
  prepended to the JSON document, breaking parsers.
- **`cli/run_planning.py::_best_metric_val` honors
  `_LOWER_IS_BETTER`** — pre-fix `max(nums)` ranked RMSE=12.3
  above RMSE=0.42 (worst-as-best for error metrics). Now prefers
  a higher-is-better metric when present and inverts when only
  lower-is-better metrics are available.
- **`packaging.version.Version` for update comparison** — pre-fix
  `_parse_version` truncated at first non-int (`0.4.0rc1` → `(0,4)`
  → equal to `0.4.0` → wrong pre-release ordering).
- **Token accounting separates fresh / cache-create / cache-read**
  — `AgentResult` gained `input_tokens_only`, `cache_creation_in`,
  `cache_read_in` fields. `core/usage.py::estimate_cost` applies
  Anthropic's 1.25× cache-creation premium and 0.10× cache-read
  discount when the breakdown is supplied. Pre-fix everything was
  billed at fresh-input rates, overstating cost for cache-heavy
  workloads.
- **TUI `/pause` reachable while busy** — pre-fix
  `_ALWAYS_ALLOWED_COMMANDS = {"quit", "stop"}` rejected `/pause`,
  making the documented "pause mid-experiment" feature
  structurally unreachable from the TUI.
- **TUI remote chat parses suggestions** — Slack/Telegram users
  hit the same advisor→/run silent fail bug that Package H fixed
  for the local InputBar path; the parallel `_run_remote_chat`
  worker is now updated too.
- **`set_agent_active` initialises the processing clock** — pre-
  fix only `set_agent_running` set `_processing_start`, so REPL
  paths (which only call `set_agent_active`) accumulated zero
  processing time. Every REPL session logged `processing_ms=0` to
  `usage.json`.
- **`clear_project` mirrors `load_project`** — pre-fix it only
  nulled three fields, leaking notification-bus thread, pending
  suggestions, and usage counters across project deletions.
- **REPL `cmd_advisor` correctly handles `_run_single_agent`'s
  `str` return type** — caught the I-7 regression where the
  `result.get(...)` call swallowed an AttributeError and silently
  no-opped both `append_exchange` and `parse_suggestions`.

### Fixed

- **Orchestrator leaderboard inside the per-run loop** — pre-fix
  the leaderboard update sat OUTSIDE the inner `for run in runs:`
  loop, referencing the loop variable after iteration ended. On
  any turn that produced multiple runs (multi-method exploration,
  ensemble experiments) only the LAST run's metrics ever reached
  the leaderboard.
- **JSON-fence regex accepts single-line code blocks** — pre-fix
  the regex required a literal newline between the language tag
  and body, silently dropping ` ```json {...} ``` `.
- **`parse_run_records` validates metrics is a dict** — pre-fix
  an agent emitting `"metrics": "great"` (string) created a
  RunRecord whose downstream consumers crashed on `.values()`.
- **Email channel health check** — pre-fix returned `(True, "")`
  for any relay that accepted NOOP without auth even when
  `MAIL FROM` would be rejected at send time. Now probes
  `MAIL FROM` when no password env is configured.
- **`UserCancelled` detected by `isinstance` not string compare**
  — pre-fix `type(exc).__name__ == "UserCancelled"` would match
  any class anywhere named UserCancelled.
- **`cli_display._is_tty()` re-evaluates per call** — pre-fix
  `_IS_TTY` was frozen at import; Textual swaps `sys.stdout` after
  import, turning spinners into permanent no-ops in the TUI.
- **Orchestrator session ID collision at second resolution** —
  pre-fix `_timestamp_id` returned `%S` precision; two sessions
  in the same wall-clock second collided. Now appends a 4-hex
  random suffix.
- **Empty-string secrets distinguishable from unset** — vault
  `get` uses `is not None` checks at all 3 tiers.
- **Bare `except:` in `core/session.py:165`** narrowed to
  `except Exception:` so `KeyboardInterrupt` propagates cleanly.

### Removed

- **TypeScript TUI launcher (`urika tui` CLI command)** — the TS
  TUI was archived to `dev/archive/typescript-tui/` and gitignored
  from main, but the launcher in `src/urika/cli/tui.py` shipped on
  main as a discoverable command pointing at vaporware. The
  Python Textual TUI (`urika` no-args, the documented default) is
  unchanged.

### Internal

- 161 new tests across 12 new test files plus updates to existing
  tests for the new contracts. Suite now 2844 total (1 skipped),
  runs in ~65 seconds (down from ~7 minutes after the slow-marker
  hardening + sleep removals).
- 5 of 45 audit findings refuted by direct code reading rather
  than agent reports — caught two false-positive "fixes for fixes"
  before they shipped.

## [0.4.1] - 2026-05-03

Hardening release. No new feature surface — closes the v0.4.x bug
backlog discovered after v0.4.0 shipped, plus instrumentation for
the prompt-bloat investigation that ultimately deprioritised the
work originally planned. Hybrid-mode E2E smoke run end-to-end
against the marketing dataset (vLLM + Anthropic split, 50 agent
calls, 87.5% cache hit, no `ContextWindowExceededError`).

### Added

- **Per-endpoint `context_window` + `max_output_tokens`** on
  `[privacy.endpoints.<name>]`. Closes the v0.4 E2E private-mode
  smoke regression where local vLLM endpoints (32K window)
  returned HTTP 400 `ContextWindowExceededError` because the
  bundled `claude` CLI defaulted to a 32K output request that
  alone filled the window. Auto-default by URL: `anthropic.com` →
  200000 / 32000 (no behaviour change for cloud), anything else →
  32768 / 8000 (conservative; leaves 24K for input). Forwarded to
  the CLI via `CLAUDE_CODE_MAX_CONTEXT_TOKENS` and
  `CLAUDE_CODE_MAX_OUTPUT_TOKENS` env vars. Configurable via the
  dashboard's Settings → Privacy tab and via `urika.toml` /
  `~/.urika/settings.toml` directly.
- **Per-Bash-tool-call timeout cap** via
  `[preferences].max_method_seconds` (default 1800 s = 30 min).
  Pre-fix a deadlocked training script (infinite loop, stuck GPU
  op, hung network call) could wedge an experiment for hours. The
  `can_use_tool` permission callback now clamps every Bash tool
  call to the configured ceiling via
  `PermissionResultAllow.updated_input`. Smaller-than-cap requests
  pass through unchanged so quick health checks stay fast. 0 /
  negative falls back to the default — no "no-cap" mode by design.
- **CLI launcher: "Run autonomously (no prompts)" option.** The
  bare `urika run <project>` settings dialog gained an `Autonomous`
  status line in the header and a new menu option that flips
  `auto=True` for a single-experiment run. Pre-fix users who
  expected the loop to flow advisor → planner → run without
  confirmation had to know about the `--auto` flag.
- **`URIKA_PROMPT_TRACE_FILE` instrumentation.** When set,
  `ClaudeSDKRunner.run` appends one JSONL record per agent call
  with system / prompt bytes, tokens broken down by
  input / cache_creation / cache_read, output tokens, and
  duration. Companion script `dev/scripts/analyze_prompt_trace.py`
  summarises the per-agent table. Off by default — zero overhead
  beyond an env-var lookup.
- **Cookbook docs page**
  `21-cookbook-long-running-training.md` covering the
  multi-minute-per-method project shape: `max_turns` sizing,
  budget calibration, stop / resume semantics, the prompt-trace
  loop, and a defensive metric-write template.

### Fixed

- **SIGTERM after criteria met no longer downgrades completed
  status.** Pre-fix the dashboard's Stop button (or any SIGTERM)
  arriving while `_generate_reports` was producing the
  per-experiment narrative overwrote the on-disk `completed`
  status with `stopped` and exited 1. A successful run with a
  user-abandoned cosmetic narrative pass showed up as a failure.
  `stop_session` now refuses to downgrade a terminal status; the
  CLI's signal handler exits 0 when it detects the
  already-completed case and prints a clarifying message.
- **Documentation page on pip-installed Urika** now works.
  Pre-fix the dashboard's `/docs` page rendered `Documentation
  not available` and linked to a placeholder
  `github.com/yourorg/urika` URL because `docs/` only shipped
  with editable installs. The wheel now bundles the `docs/` tree
  at `urika/_docs/` via `hatch.build.targets.wheel.force-include`
  and the resolver checks the bundled location. Empty-state copy
  + GitHub link fixed to point at the real repo.
- **Sessions tab empty-state copy** re-written to disambiguate
  what creates sessions (Advisor tab, `urika advisor` CLI, TUI
  free-text) from what doesn't (`urika run`, `urika finalize`).
  Pre-fix users who ran `urika run` and saw an empty Sessions tab
  assumed the feature was broken.

### Investigated, not changed

- **Prompt-bloat global trim (originally v0.4.1 #2):** dropped.
  Live-trace data from a real run showed 88.6% prompt-cache hit
  ratio and a 200:1 output:fresh-input token ratio. Trimming
  user-prompt blobs would save tens of fresh input tokens per
  turn against an output stream of ~21K tokens — not a meaningful
  lever. Plan rewritten in
  `dev/plans/2026-05-02-prompt-bloat-and-context-budget.md` —
  the per-endpoint declarations above (Layer 2 in the original
  plan) were kept because they solve a different problem
  (local-model context exceeded); the global audit (Layer 1) is
  cancelled.

## [0.4.0] - 2026-05-02

First feature-complete v0.4 release. Bundles every v0.4 track
(SecurityPolicy enforcement, multi-provider runtime abstraction,
project memory Phase 1, experiment comparison view, dataset hash +
drift detection, cost-aware budget, shell completion, sessions list/
export) plus Windows hardening, sensible defaults, and per-agent
model curation discovered during pre-release testing.

### Added (post-rc2)

- **Reasoning vs execution model split** — when the user picks Opus
  as the open-mode or hybrid-mode default in `urika config`, the
  wizard now auto-pins **reasoning agents** (`planning_agent`,
  `advisor_agent`, `finalizer`, `project_builder`) to that Opus
  tier and **execution agents** (`task_agent`, `evaluator`,
  `report_agent`, `presentation_agent`, `tool_builder`,
  `literature_agent`, `data_agent`, `project_summarizer`) to
  `claude-sonnet-4-5`. Sonnet performs indistinguishably from Opus
  on "execute this plan" / "format these numbers" / "apply rule to
  metric" tasks and saves ~5× per call. Net ~50–65% cost reduction
  per experiment with zero quality impact. Sonnet/Haiku defaults
  skip the split entirely (already at the cheaper tier). Single
  source of truth in new `urika.core.recommended_models`.
- **`urika config [PROJECT] --reset-models`** — re-applies the
  reasoning/execution split to an existing project's `urika.toml`
  or, without `PROJECT`, to every configured mode in
  `~/.urika/settings.toml`. Idempotent. Hybrid projects keep their
  data-agent + tool-builder private-endpoint pin across the
  rebuild. Designed for upgrading from pre-v0.4.0 settings files
  or after manual drift.
- **Dashboard "Reset to recommended defaults" button** on the
  Models tab in both `/settings` (global) and `/projects/<n>/settings`
  (project-scoped). New endpoints: `POST /api/settings/models/reset`
  and `POST /api/projects/<n>/settings/models/reset`. Same shared
  helper as the CLI flag; confirmation dialog + Alpine-driven
  progress + inline success/failure message.

### Changed (post-rc2)

- **Per-experiment finalize no longer auto-writes the project-level
  narrative.** The post-criteria-met sequence in
  `orchestrator/loop_finalize._generate_reports` was running TWO
  agent-written narratives back-to-back: the experiment-level
  one (`experiments/<id>/labbook/narrative.md`, fast and
  per-experiment) and a project-level one
  (`projectbook/narrative.md`, summarising "all experiments and
  the research progression"). The project-level pass added
  10–25 minutes of cloud-LLM tail to every successful
  experiment and is fundamentally redundant — `urika report`
  produces the same narrative on demand with a leaner prompt,
  and `urika finalize` produces the canonical
  `projectbook/final-report.md` from the structured
  `findings.json` at end-of-project. Removed the inline pass;
  per-experiment narrative + per-experiment presentation are
  unchanged. **Agent feedback loop is unaffected** — the planner
  and advisor never read `projectbook/narrative.md`; their
  cross-experiment memory is `methods.json` + `criteria.json`
  + `advisor-history.json` + `advisor-context.md` (rolling
  summary refreshed per advisor call) + project memory.
- **`max_turns_per_experiment` default unified at 5** across every
  surface (was 10). Five sites flipped (factory `settings.py`, CLI
  fallback, TUI defaults helper, dashboard New-Experiment modal,
  dashboard global Settings page). Cap on a stuck-loop experiment's
  worst-case spend drops from ~$1+ to ~$0.50; well-set criteria
  still converge in 2–3 turns. Override per experiment via
  `urika run --max-turns N` or per project via `[preferences]
  max_turns_per_experiment`.
- **Dashboard New-Experiment modal max-turns input** now reads from
  the project's `[preferences].max_turns_per_experiment` (with
  global-default fallback) rather than hardcoding the value.
  Editing the project-level preference now flows through to the
  modal — single source of truth.

### Fixed (post-rc2)

- **Bearer-token auth for non-Anthropic private endpoints.** The
  bundled Claude Agent SDK CLI sends the auth header based on
  which env var it sees: `ANTHROPIC_API_KEY` → `x-api-key`,
  `ANTHROPIC_AUTH_TOKEN` → `Authorization: Bearer`.
  api.anthropic.com expects the former; vLLM, LiteLLM, OpenRouter,
  and most OpenAI-compatible private endpoints expect the latter
  and 401 with "Ensure Key has 'Bearer ' prefix" otherwise. Pre-fix
  urika set `ANTHROPIC_API_KEY` for all configured endpoints, so
  every private-mode agent call 401-ed. Two-part fix: (a)
  `urika.agents.config.build_agent_env_for_endpoint` now sets
  `ANTHROPIC_AUTH_TOKEN` (and clears `ANTHROPIC_API_KEY`) for
  non-Anthropic base URLs; (b)
  `urika.core.compliance.scrub_oauth_env` no longer
  unconditionally blanks `ANTHROPIC_AUTH_TOKEN` — it preserves
  deliberately-set values (the parent-leakage protection still
  blanks the var when absent). `CLAUDE_CODE_OAUTH_TOKEN` is still
  unconditionally blanked (no legitimate use in a Urika subprocess).
- **System claude CLI v2.1.124+ trailing exit-1 in streaming mode.**
  The system-installed `claude` CLI (which urika prefers for newer
  request schemas, e.g. `claude-opus-4-7`) exits 1 in streaming
  bidirectional mode *after* successfully streaming the final
  `ResultMessage`. Pre-fix, every multi-agent step in urika
  (advisor, build-tool, plan, run, evaluate, report, present,
  finalize) treated this as a hard failure even though the work
  completed cleanly. The adapter now detects "we already saw a
  clean ResultMessage" (`num_turns > 0` AND `not is_error`) and
  returns `success=True` with the captured state. Counter-cases —
  exit before any ResultMessage (credit-low, auth) and exit after
  `is_error=True` — still propagate as failures with the
  classified category. Also installs a `logging.Filter` on
  `claude_agent_sdk._internal.query` that drops the SDK's noisy
  `Fatal error in message reader: ...` log line when our adapter
  has already tolerated the error. Captures the bundled CLI's
  stderr for the first time so future post-stream errors actually
  reach urika logs (the SDK transport hardcoded a useless
  placeholder before).
- **`urika new` no longer spawns live agent under non-TTY stdin.**
  Two paths in `urika new` invoked the project-builder LLM agent
  loop with no stdin guard: the clarifying-questions loop and the
  post-creation "offer to run an experiment" prompt (whose
  default-on-EOF auto-fired `urika run`). Every CliRunner-based
  unit test of `urika new` was silently making real API calls
  until something killed it, and any CI script running
  `urika new --data foo.csv` without `--description` was paying
  for an unwanted agent loop. Both paths now skip when
  `sys.stdin.isatty()` is False or `URIKA_NO_BUILDER_AGENT=1` is
  set. `--json` mode was already safe via its own fast path.
- **Windows: SSE log streamers crashed on cp1252 bytes** (e.g.
  `0x97` em-dash) emitted by the bundled claude CLI's tool-use
  markers. All ten SSE endpoints (`run` / `evaluate` / `report` /
  `present` / `finalize` / `summarize` / `build-tool` / `advisor`
  / `_log` paths in `dashboard/routers/api.py`) now open log files
  with `errors="replace"` so a stray byte renders as `?` instead
  of tearing down the dashboard's live log view with
  `UnicodeDecodeError`.
- **Windows: stdout/stderr UnicodeEncodeError on box-drawing chars.**
  Python on Windows defaults `sys.stdout` to the active console
  code page (typically `cp1252`), which can't encode urika's
  `╭─╮` banner / spinner / TUI glyphs. `cli/_base._ensure_utf8_streams`
  now reconfigures both streams to UTF-8 with `errors="replace"`
  at import time (before Click parses anything), no-op on
  already-UTF-8 streams. Survives streams that lack
  `reconfigure()` (older Python, exotic test wrappers).
- **CLI smoke harness greps too aggressively.** The bare
  `Fatal error in message reader` string is no longer a FAIL
  trigger — the adapter already tolerates it cleanly. The harness
  now only flags the actionable `can_use_tool callback requires`
  streaming-mode regression marker or a Python traceback that
  references the adapter module.

### Docs (post-rc2)

- **20 → 32 user-facing docs** — split six over-long pages into
  focused sub-pages so reference material stays search-friendly
  and reading material stays linear. `12-built-in-tools.md` →
  `12a/12b`, `13-models-and-privacy.md` → `13a/13b`,
  `14-configuration.md` → `14a/14b`, `16-cli-reference.md` →
  `16a/16b/16c/16d/16e`, `18-dashboard.md` →
  `18a/18b/18c/18d`, `19-notifications.md` → `19a/19b`. Every
  cross-reference inside `docs/` and the top-level `README.md`
  was rewritten to point at the right sub-page; orphaned
  `contributing-an-adapter.md` was added to the index.
- **Audit pass** corrected the dashboard's actual default port
  (random free port, override with `--port`; `--auth-token`
  documented), the `task_agent`'s actual allowed bash list
  (`python` + `pip` + `pytest`), the dashboard settings tab counts
  (project: 6 with Secrets, global: 5 with Secrets), the project
  tree (added `memory/`, `.urika/sessions/`, etc.), and stripped
  every internal "(Phase 11/13)" annotation from
  `18a-dashboard-pages.md` that had been leaking into the public
  docs.
- **Windows install troubleshooting** — `01-getting-started.md`
  now covers the `WinError 32` urika.exe file-lock and the
  cp1252 console-encoding self-fix.

### Plans

- **`dev/plans/2026-05-02-prompt-bloat-and-context-budget.md`** —
  three-layer plan for v0.4.1 covering prompt-assembly trim,
  per-endpoint `context_window` declaration + output-token clamp,
  and summarisation fallback. Tracks the issue surfaced by the
  v0.4 E2E private-mode smoke (32K-context vLLM endpoint hit a
  94K-char advisor prompt + 32K-token output-cap request).

- **System claude CLI v2.1.124+ trailing exit-1 in streaming mode.**
  The system-installed `claude` CLI (which urika prefers for newer
  request schemas, e.g. `claude-opus-4-7`) exits 1 in streaming
  bidirectional mode *after* successfully streaming the final
  `ResultMessage`. Pre-fix, every multi-agent step in urika
  (advisor, build-tool, plan, run, evaluate, report, present,
  finalize) treated this as a hard failure even though the work
  completed cleanly. The adapter now detects "we already saw a
  clean ResultMessage" (`num_turns > 0` AND `not is_error`) and
  returns `success=True` with the captured state. Counter-cases —
  exit before any ResultMessage (credit-low, auth) and exit after
  `is_error=True` — still propagate as failures with the
  classified category. Also installs a `logging.Filter` on
  `claude_agent_sdk._internal.query` that drops the SDK's noisy
  `Fatal error in message reader: ...` log line when our adapter
  has already tolerated the error. Captures the bundled CLI's
  stderr for the first time so future post-stream errors actually
  reach urika logs (the SDK transport hardcoded a useless
  placeholder before).
- **Windows: SSE log streamers crashed on cp1252 bytes** (e.g.
  `0x97` em-dash) emitted by the bundled claude CLI's tool-use
  markers. All ten SSE endpoints (`run` / `evaluate` / `report` /
  `present` / `finalize` / `summarize` / `build-tool` / `advisor`
  / `_log` paths in `dashboard/routers/api.py`) now open log files
  with `errors="replace"` so a stray byte renders as `?` instead
  of tearing down the dashboard's live log view with
  `UnicodeDecodeError`.
- **Windows: stdout/stderr UnicodeEncodeError on box-drawing chars.**
  Python on Windows defaults `sys.stdout` to the active console
  code page (typically `cp1252`), which can't encode urika's
  `╭─╮` banner / spinner / TUI glyphs. `cli/_base._ensure_utf8_streams`
  now reconfigures both streams to UTF-8 with `errors="replace"`
  at import time (before Click parses anything), no-op on
  already-UTF-8 streams. Survives streams that lack
  `reconfigure()` (older Python, exotic test wrappers).
- **CLI smoke harness greps too aggressively.** The bare
  `Fatal error in message reader` string is no longer a FAIL
  trigger — the adapter already tolerates it cleanly. The harness
  now only flags the actionable `can_use_tool callback requires`
  streaming-mode regression marker or a Python traceback that
  references the adapter module.

## [0.4.0rc2] - 2026-04-30

Second v0.4 release candidate. Closes the remaining v0.4 tracks
(2, 5, and the rest of 4) on top of rc1.

### Added

- **Project memory Phase 1** (Track 2). New
  `<project>/memory/MEMORY.md`-indexed directory of structured
  markdown entries (user / feedback / instruction / decision /
  reference). `urika.core.project_memory` provides
  `load_project_memory(project_dir)` for system-prompt injection,
  `save_entry(...)` / `delete_entry(...)` for writes, and
  `parse_and_persist_memory_markers(project_dir, agent_text)` —
  strips `<memory type="...">...</memory>` markers from agent
  output and persists each as an entry. Per-project disable via
  `[memory] auto_capture = false` in `urika.toml`. Soft cap 5 KB
  (warns), hard cap 20 KB (truncates with marker). Phase 2-4
  (advisor/planner-emit prompts, curator agent, dashboard page,
  TUI slash command) defer to v0.5.
- **`urika memory list / show / add / delete`** CLI group as the
  manual surface over Phase 1.
- **Planner reads context summary + project memory** at
  `build_config` time. Pre-v0.4 only the advisor saw the rolling
  context summary; the planner had to rediscover prior decisions
  from `advisor-history.json` on its own.
- **`urika sessions list / export`** (Track 2 cheap win). Export
  an `OrchestratorSession` to Markdown (default — sharing) or JSON
  (full fidelity). Both stdout and `-o file`.
- **Experiment comparison view** (Track 4). New
  `GET /projects/<n>/compare?experiments=exp-001,exp-002` route
  renders a side-by-side metric table. Pre-v0.4 users had to open
  separate experiment-detail tabs and compare in their head —
  table-stakes for the experiment-tracking competitive set.
- **Cost-aware budget** (Track 4). `urika run --budget USD` flag
  pauses the experiment at the next turn boundary when accumulated
  cost crosses the budget; resumable. `urika run --dry-run` adds
  a cost estimate row using the project's prior session costs
  (last 7 non-zero, range + median × planned experiments).

### Fixed

- **TUI `_TuiWriter._post_line` prefers public `asyncio` API**
  over Textual's private `app._loop` / `app._thread_id` for the
  same-thread check. Fallback to private-attribute path is
  preserved for older Textual versions. Pre-v0.4 a Textual upgrade
  that renamed the private attrs would silently break thread-safe
  routing.
- **TUI `SystemExit` handler in `agent_worker.py` only exits the
  app for the explicit `/quit` command.** Pre-v0.4 every
  `SystemExit` (e.g. `urika config secret` wizards calling
  `raise SystemExit(0)` on user-cancel) silently quit the TUI
  behind the user's back.

## [0.4.0rc1] - 2026-04-30

First v0.4 release candidate. v0.4.0 is positioned as the **first
feature-complete Urika system, stable enough for extensive user
testing**. Strip GitHub integration out (deferred to v0.5) and Urika
is still a complete research-analysis platform.

This RC1 closes Tracks 1 (carry-overs from v0.3.2 deferrals),
3 (multi-provider thin abstraction), and most of 4 (user-facing
features: shell completion, dataset hash + drift detection).
Tracks 2 (project memory Phase 1), 5 (TUI polish), and the rest of
4 (experiment comparison view, cost-aware budget) follow in
subsequent RCs.

### Added

- **SecurityPolicy enforcement via SDK `can_use_tool` callback.**
  Pre-v0.4 the `writable_dirs` / `readable_dirs` /
  `allowed_bash_prefixes` / `blocked_bash_patterns` fields on
  every agent role were advisory only. v0.4 wires them into a real
  `can_use_tool` coroutine the SDK invokes before each tool
  dispatch. Bash commands shlex-parsed; shell metacharacters
  (`;`, `&&`, `||`, `|`, backticks, `$(`, `>`, `>>`, `<`, `&`,
  newline) rejected outright. Path operations canonicalised
  (collapse `..`, follow symlinks). Closes the orchestrator
  Bash bypass (`urika ; rm -rf /` was matching the prefix string).
- **Stop endpoints for non-run operations.** New `POST` routes:
  `/projects/<n>/advisor/stop`, `/finalize/stop`,
  `/summarize/stop`, `/build-tool/stop`, and
  `/runs/<exp>/present/stop`. All use the same SIGTERM-to-process-
  group pattern as `/runs/<exp>/stop`. Pre-v0.4 long-running
  advisor / finalize / build-tool / present invocations had no
  kill switch from the dashboard.
- **Multi-provider thin abstraction.** `AgentRunner` ABC gains
  `required_env` and `supported_tools` classmethods. New
  `urika.runners` entry-point group lets external packages
  register adapters (`OpenAIRunner`, `GoogleADKRunner`, etc.)
  without modifying core. New `list_backends()` enumerates every
  resolvable name. New `docs/contributing-an-adapter.md` walks
  contributors through the seam. End-to-end second adapter is
  deferred to v0.5.
- **Dataset hash + drift detection.** `urika new` records SHA-256
  of every data file under `[project.data_hashes]` in
  `urika.toml`. `urika status` re-hashes registered files and
  surfaces drift with a yellow warning. `--json` mode includes
  `data_drift`. Closes a long-standing reproducibility gap:
  pre-v0.4 there was no record at all, so editing a data file
  silently between experiments was undetectable.
- **`urika completion install / script / uninstall`.** Native
  bash / zsh / fish completion via Click 8's built-in generator.
  Auto-detects shell from `$SHELL`. Writes scripts to
  `~/.urika/completions/urika.<shell>`.
- **`OrchestratorSession` is now a real source of truth** in
  documented form (was already shipping in v0.3.2 but undocumented
  in CHANGELOG until this entry).

### Fixed

- **Cross-interface default consistency** — `audience` (`"standard"`
  everywhere — was 4 sites disagreeing on novice/standard/expert),
  `max_turns_per_experiment` (10 everywhere — was CLI=5, REPL=5,
  dashboard=10).
- **`KNOWN_AGENTS` (dashboard pages.py + api.py) adds
  `project_summarizer`** so the per-agent model-override grid
  renders all 12 agents instead of 11.
- **Email password input in CLI notifications wizard now masks**
  via `click.prompt(hide_input=True)`. Pre-v0.4 echoed plaintext
  while the dashboard's matching field always masked.
- **`VALID_SESSION_STATUSES` includes `pending` and `starting`.**
  Pre-v0.4 the set omitted these even though `experiment.json`
  and `progress.json` both used `pending` as the seed status.
- **Surface swallowed exceptions across orchestrator + cli +
  vault** — `loop_criteria.py` `pause_session` / `fail_session`,
  `loop.py` `resume_session` / `start_session`, `parsing.py`
  malformed JSON blocks (was a silent `continue` — most common
  reason `criteria_met` was missed), `cli/_base.py` `UrikaError`
  `__cause__` chain, `core/vault.py` `_read_env_file` and
  `_read_meta` failures.
- **`default_max_turns` upper bound** (200) in dashboard form
  validation. Pre-v0.4 the field accepted any positive int, so
  a paste of 999999 let every experiment run effectively forever.
- **`_toml_value` quotes inline-table keys** that aren't valid TOML
  bare keys (file paths contain `/` and `.`). Required for
  `[project.data_hashes]` to round-trip.

### Changed

- **`SecurityPolicy` docstring** updated to drop the "ADVISORY ONLY"
  warning (now actually enforced at runtime).
- **`task_agent.allowed_bash_prefixes`** gains `"pytest"` (was on
  `tool_builder` only). Required so ad-hoc pytest invocations from
  task_agent don't get denied under the new enforcement.
- **`OrchestratorChat._build_config` allowlist** updated from
  `["urika ", "CLAUDECODE= urika "]` to `["urika"]` — the
  pre-v0.4 string-prefix form was broken under shlex tokenisation
  AND was the bypass that made `urika ; rm -rf /` match.
- **`get_runner()` factory** now opens via entry points; raises
  with an actionable message + link to
  `docs/contributing-an-adapter.md` for unknown backends.

## [0.3.2] - 2026-04-30

Hardening release. v0.3.0/0.3.1 shipped four families of bugs that share one
root cause: contracts that hold in one path silently break in another (CLI
default ≠ dashboard default; advisor prompt assumes TTY but dashboard spawns
with `stdin=DEVNULL`; bundled `claude` CLI rejects newer model schema; Stop
button sends SIGTERM but CLI only handles SIGINT). v0.3.2 closes those four
families and pins them with regression tests.

### Fixed

- **Dashboard advisor chat no longer auto-fires multi-hour experiment runs from chat messages.** The CLI's "Run these experiments? [Yes]" prompt fell through to the default option on EOF when `dashboard.spawn_advisor` invoked `urika advisor` with `stdin=DEVNULL`, silently launching a 100+ minute experiment from what the user typed as a question. `_offer_to_run_advisor_suggestions` now skips the prompt entirely on non-TTY callers and prints a hint pointing at the dashboard's "New experiment" button. The Textual TUI's stdin bridge stays interactive so TUI users still see the prompt.
- **Stop button on a running experiment now actually stops the run AND flips the card to "stopped".** The dashboard sent SIGTERM but the CLI only handled SIGINT, so `stop_session` never wrote the terminal status — the card stayed on the seed `"pending"` value forever. Four-part fix: CLI's `_cleanup_on_interrupt` now handles SIGTERM symmetrically; `api_run_stop` writes `"stop"` to `<project>/.urika/pause_requested` first (graceful, lets the loop call `stop_session` at the next turn boundary) before escalating to `os.killpg(getpgid(pid), SIGTERM)` — process-group, not just the leader, so SDK-spawned `claude` and nested `urika` agents also exit; `runs._start_reaper` writes `progress.json["status"]="stopped"` (or `"failed"`) before unlinking the lock for non-zero exits as defense in depth; the SSE log stream now reads the actual terminal state from `progress.json` instead of always emitting `"completed"` regardless of how the run ended.
- **Sessions tab now captures dashboard advisor chats.** Pre-v0.3.2 only the TUI / REPL paths wrote orchestrator-session records; the dashboard's advisor chat (which spawns `urika advisor` via `runs.spawn_advisor`) silently never produced one — users reported running multiple advisor turns and seeing nothing in Sessions. CLI `urika advisor` now writes an `OrchestratorSession` record to `<project>/.urika/sessions/` after a successful exchange.
- **Stale `claude-opus-4-7` settings get migrated automatically on first launch.** v0.3.0/0.3.1 dashboard forms defaulted every agent in open mode to 4-7, but the bundled `claude` CLI inside `claude-agent-sdk 0.1.45` (v2.1.63) sends the deprecated `thinking.type.enabled` request shape that 4-7 rejects with HTTP 400, surfacing as "Fatal error in message reader: exit code 1". One-shot migration `migrate_settings()` (called from CLI startup and dashboard startup, idempotent via marker file at `~/.urika/.migrated_0.3.2`) detects 4-7 in any per-mode default or per-agent override slot, backs up `~/.urika/settings.toml` to `settings.toml.pre-0.3.2.bak`, and rewrites the broken positions to `claude-opus-4-6`. Users with the public `claude` CLI installed can re-pin 4-7 from the dashboard afterward — the runtime adapter prefers system `claude` on PATH (v2.1.100+ knows the current `thinking.type.adaptive` schema).
- **`urika new` now honors the global default model set in the dashboard.** `core/project_builder.py` was reading legacy flat `[runtime].model` while the dashboard form wrote `[runtime.modes.<mode>].model` — fresh projects from `urika new` silently ignored every default the user configured. `get_default_runtime(mode)` now prefers the per-mode key, falling back to flat for pre-0.3 layouts.
- **SDK adapter prefers system `claude` on PATH over the bundled binary.** `claude-agent-sdk 0.1.45` ships claude CLI v2.1.63 — too old to speak the request schema for newer models. The adapter now resolves `shutil.which("claude")` unconditionally and uses it when present; falls back to bundled when no system CLI is installed. Prevents the "Fatal error in message reader" symptom for users with a current `claude` CLI even if their `claude-opus-4-7` pin survived migration.
- **`compliance.scrub_oauth_env` extended to zero `CLAUDE_CODE_*` session markers.** Without this, agents launched from a Claude-Code-owned shell inherited `CLAUDECODE` etc. via the SDK's `{**os.environ, **options.env}` merge and the bundled CLI refused to launch nested. The orchestrator chat's inline scrub block (which previously only zeroed three of the four markers and missed both OAuth tokens) now delegates to the same helper; `dashboard/runs.py:_build_env` applies it as defense in depth so dashboard-spawned `urika run` children stay clean too.
- **Real subprocess stderr now surfaces from the SDK adapter.** Pre-v0.3.2 the adapter blindly forwarded `ProcessError.stderr` even when it was the SDK's hardcoded `"Check stderr output for details"` placeholder, masking the real cause (e.g. the API rejecting `thinking.type.enabled` with HTTP 400). Detect and discard the sentinel; preserve `type(exc).__name__`, exit code, and traceback via `logger.exception`.
- **Per-turn orchestrator crashes now leave a full traceback in `run.log`.** A `KeyError` parsing an evaluator block became "Experiment failed: 'criteria_met'" with no traceback anywhere; the broad per-turn catch now `logger.exception`s before returning so the SSE tailer carries the diagnostic.
- **Dashboard subprocess launch failures now appear in the run log.** `dashboard/runs.py:_spawn_detached` writes a `URIKA-LAUNCH-FAILED:` marker line into the log file the SSE tailer is watching when `Popen` itself raises (ENOEXEC, missing python, env too big), then re-raises so the route returns 500. Pre-v0.3.2 the FD was closed empty in `finally` and the route returned 200 + a phantom PID.
- **Reaper-thread crashes no longer leave orphan locks.** `_start_reaper`'s `proc.wait()` is now wrapped in try/except so a daemon-thread exception can't leave the lock forever (the "ghost run" failure mode you'd previously have to clear by hand).
- **Vault write failures during dashboard settings save now surface to the user.** Pre-v0.3.2 the privacy-endpoint and notifications form save handlers wrapped `vault.set_global` in `except Exception: pass` — the form returned a green "Saved" while secrets silently didn't write, so the next agent run mysteriously failed auth. Failures are now logged at error level AND collected into a per-request list shown in the response (HTML or JSON) so users see "Saved (with N secret-store warnings)".
- **Transient network errors and config errors now pause the experiment instead of failing it.** `_classify_error` adds `"transient"` (5xx / connection_reset / connection_refused / timeout / bad gateway) and `"config"` (MissingPrivateEndpointError / APIKeyRequiredError) categories, both added to `_PAUSABLE_ERRORS`. A network blip mid-loop or a misconfigured project pauses (resumable from the dashboard's Resume button) instead of killing a multi-hour autonomous run.
- **SDK adapter accumulates cost/tokens across multi-`ResultMessage` streams.** Pre-v0.3.2 these were set (not summed), so a subagent's usage was clobbered by the final ResultMessage's usage. Cache-token fields (`cache_creation_input_tokens`, `cache_read_input_tokens`) now also count.
- **Dashboard's `VALID_PRIVACY_MODES` list fixed.** Contained the defunct `"university"` mode and was missing `"hybrid"`; canonical set is now exactly `{open, private, hybrid}` and `pages.py` agrees with `api.py`.
- **Non-TTY guards extended to remaining destructive prompts.** `cli/run_planning.py:_determine_next_experiment` (twin of the advisor auto-fire bug), `cli/run.py` settings dialog and resume selector, `cli/agents_present.py`, `cli/agents_report.py`, `cli/agents.py` advisor and build-tool no-arg paths — all now skip the prompt or fall through to a safe default on non-TTY callers.

### Added

- **Cross-interface invariant tests** (`tests/test_cross_interface_defaults.py`). Pin five contracts that pre-v0.3.2 drift broke: CLI wizard's `_CLOUD_MODELS` and dashboard's `KNOWN_CLOUD_MODELS` agree; dashboard template's hardcoded fallback model is in `KNOWN_CLOUD_MODELS`; `VALID_PRIVACY_MODES` agrees with `_VALID_PRIVACY_MODES`; `get_default_runtime(mode)` round-trips what the dashboard form PUT writes; `python -m urika` is a valid module entry point. Future drift fails fast at CI time rather than mid-experiment.
- **Regression tests for stop / migration / classifier**: SIGTERM-exit terminal status writeback (3 tests), `_classify_error` coverage of all six categories (8 tests), `migrate_settings` rewrite + idempotence + no-op paths (4 tests), `get_default_runtime` per-mode preference (3 tests), upgraded stop endpoint signals process group + writes flag file (1 test).

### Changed

- **Dashboard model picker default lowered to `claude-opus-4-6`** in all six hardcoded sites (`pages.py:KNOWN_CLOUD_MODELS`, two `cloud_models` lists, `runtime_model_placeholder`, four `global_settings.html` fallback expressions). 4-7 stays selectable for users with the public `claude` CLI installed.
- **CLI `_CLOUD_MODELS` constant hoisted to module scope** in `cli/config.py` so the cross-interface invariant test can import it. 4-7 added as a selectable option with a "requires public claude CLI on PATH" description so it's offered alongside 4-6 / sonnet-4-5 / haiku-4-5.
- **Install docs reordered for beginners** (`docs/01-getting-started.md` and README): `Step 1 Prerequisites → Step 2 Install Urika → Step 3 API key → Step 4 Verify → Troubleshooting`. Python is now an explicit Step 1 with per-OS install commands; Claude CLI is documented as **recommended, not required** (the SDK ships its own bundled binary that handles 4-6/sonnet/haiku; users only need to install Node + `claude` if they want 4-7 or future Anthropic models). PEP 668 `externally-managed-environment` callout lives in Step 2 (the install step itself), not buried elsewhere. Troubleshooting table covers PEP 668, the "Fatal error in message reader" symptom, missing PATH, npm EACCES, missing API key, missing `urika` binary.

### Known limitations (deferred to 0.4)

- **`SecurityPolicy` is advisory only.** The `writable_dirs` / `readable_dirs` / `allowed_bash_prefixes` / `blocked_bash_patterns` fields on every agent role are documented as enforced sandboxing but currently aren't consumed at runtime — the only real sandbox is `allowed_tools` + `cwd`. The orchestrator chat's "block raw data reads via `cat */data/`" rules are paper. Real fix requires wiring these into the SDK's `PreToolUse` hook; landing in 0.4 alongside the multi-provider adapter scaffolding.
- **Orchestrator's Bash allow-list is bypassable.** `allowed_bash_prefixes=["urika ", ...]` is a string-prefix check that `urika ; rm -rf /` matches. Same fix path as above (SDK hook integration).

## [0.3.1] - 2026-04-29

Hotfix release driven by first-time Windows install feedback. Three issues that blocked fresh `pip install urika` users — primarily on Windows, but the fixes are platform-agnostic and improve the experience everywhere.

### Fixed

- **Dashboard `TypeError: unhashable type: 'dict'` on first page load.** Newer Starlette versions (≥0.40) removed the deprecated `TemplateResponse(name, context)` positional signature; the dict was being treated as Jinja `globals` and passed as a hash key, which fails. Migrated all 29 dashboard `TemplateResponse` call sites in `routers/pages.py` (26) and `routers/docs.py` (3) to the modern `TemplateResponse(request, name, context)` signature. Resolves the 269 v0.3-era deprecation warnings as a side benefit.
- **Vault backend selection respects test monkeypatching.** `urika.core.secrets._vault()` now only forces a `FileBackend` when `_SECRETS_PATH` has been monkeypatched away from the home-directory default (so existing test redirection still works). Otherwise it lets `SecretsVault` pick the best available global backend — OS keyring when `urika[keyring]` is installed and probes successfully, file fallback otherwise. Matches what `urika config secret` writes to.
- **Dashboard refreshes credentials on page render.** `/settings` (the global settings page) and `/api/settings/test-endpoint` now call `load_secrets()` before reading `ANTHROPIC_API_KEY` / private-endpoint env vars. Means a key added via `urika config api-key` or `urika config secret` (in another shell since the dashboard process started) becomes visible without restarting the dashboard.
- **Privacy preflight sends bearer token to auth-protected private endpoints.** `urika.core.privacy.check_private_endpoint` was building the GET `/v1/models` request with no `Authorization` header. An auth-protected vLLM / LiteLLM / OpenAI-compatible local endpoint behind an API key returned 401/403, `urlopen` raised `URLError`, and the gate reported "Local model unreachable" — even though the endpoint was running and the agent runtime had the right key. Fix: when `api_key_env` names a set env var, the preflight sends `Authorization: Bearer <token>` (loaded via the same `load_secrets()` refresh as above). Unauthenticated endpoints (default Ollama) unaffected — no header sent when `api_key_env` is blank or the var is unset.

### Added

- **`urika config secret`** — interactive CLI command for storing arbitrary named credentials in the global vault (private vLLM keys, HuggingFace tokens, third-party API credentials). Mirrors `urika config api-key` but works for any name. Includes a foot-gun guard that catches users pasting a value (e.g. `sk-...`) into the name prompt and asks them to confirm. Same vault backs the credential indirection (`bot_token_env`, `api_key_env`, `password_env`) used elsewhere — the dashboard's Privacy and Notifications tabs continue to store names; this command stores values.
- **Update banner now suppressed when stdout isn't a TTY** — was corrupting JSON output for `urika ... --json` consumers and adding noise to CI / piped sessions. Display also no longer prints `vv0.3.1` when GitHub tags use a `v` prefix.

### Tests

- 2418 → 2421 (+3 regression tests for the privacy preflight bearer-token paths).


## [0.3.0] - 2026-04-29

The "three interfaces, one platform" release. Urika now treats CLI, TUI, and dashboard as equal first-class interfaces, ships a hardened notifications subsystem with end-to-end test-send, finishes orchestrator session memory with a dashboard surface, and (most importantly) aligns with Anthropic's Consumer Terms §3.7 by requiring `ANTHROPIC_API_KEY` for all usage and actively blocking the subscription OAuth path the April 2026 enforcement targeted.

### Compliance (must-read)

- **Urika now requires an `ANTHROPIC_API_KEY`** for any command that spawns an agent. Per Anthropic's [Consumer Terms §3.7](https://www.anthropic.com/legal/consumer-terms) and the April 2026 Agent SDK clarification, a Claude Pro / Max subscription cannot be used to authenticate the Claude Agent SDK that Urika depends on. The full rationale is in [`docs/20-security.md`](docs/20-security.md#provider-compliance).
- **Three-layer safety net** prevents accidental subscription use:
  1. CLI startup prints a yellow warning when `ANTHROPIC_API_KEY` is unset (silence with `URIKA_ACK_API_KEY_REQUIRED=1`).
  2. The Anthropic SDK adapter raises `APIKeyRequiredError` before spawning when no key is found and the agent is bound for `api.anthropic.com`. Private endpoints (`ANTHROPIC_BASE_URL`) and non-Claude models are exempt.
  3. The subprocess environment scrubs `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_AUTH_TOKEN` so the spawned `claude` cannot fall back to OAuth even if the user has those vars set. Source: `src/urika/core/compliance.py`.
- New `urika config api-key` interactive command saves the key into `~/.urika/secrets.env` (chmod 0600). `urika config api-key --test` fires a real round-trip request to Anthropic to verify the key works (≈ $0.0001 per test).
- Dashboard Settings page surfaces a banner when no key is set and a positive "API key configured" indicator with a Test button when set.

### Added

**Three interfaces, one platform**

- New `docs/02-interfaces-overview.md` chapter introduces CLI / TUI / dashboard as equal-first-class interfaces with a task-by-task cheat-sheet table covering create-project, run, pause/stop, resume, results, advisor, sessions, finalize, knowledge, notifications, etc.
- Documentation reorder for v0.3 — Dashboard chapter jumps from #19 to #18 (sandwiched with TUI and CLI Reference instead of buried at the end). Knowledge Pipeline pulled forward to #10. Five user-facing how-to docs gain "From the dashboard" subsections to close three-mode coverage gaps.
- README replaces "Two ways to use Urika" framing with three-interface positioning + a short comparison table.

**Notifications: dashboard parity**

- New `POST /api/settings/notifications/test-send` endpoint with a **Send test notification** button on the dashboard's Notifications tab. Tests un-saved form data so users can validate credentials before clicking Save. Per-channel results render inline with the SDK's actual error string (e.g. Slack `invalid_auth`, Gmail `530 Authentication Required`).
- Slack settings tab now exposes previously-missing inbound config fields (App token env var, Allowed channels, Allowed users) so Socket Mode commands can be enabled without hand-editing TOML.

**Orchestrator session memory: dashboard surface**

- New `/projects/<n>/sessions` page with the Sessions sidebar tab (between Advisor and Knowledge). Lists up to 20 most-recent orchestrator chat sessions per project with preview text, turn count, last-updated timestamp, **Resume** button, and **Delete** button (HTMX swap).
- New `DELETE /api/projects/<n>/sessions/<id>` endpoint trashes a session.
- `GET /projects/<n>/advisor?session_id=<id>` pre-loads a prior orchestrator session's messages above the advisor transcript as read-only context.
- Auto-prune at save: `save_session` now caps each project at the most recent 20 sessions.
- REPL project-switch hint now shows session preview + relative time ("Previous session from 2 hours ago: \"Why are tree counts so skewed…\"").

**CLI commands now documented + new ones**

- `urika config api-key` (new — interactive setup) and `urika config api-key --test` (new — verify the key works end-to-end).
- `urika notifications`, `urika summarize`, `urika tui`, `urika experiment delete`, `urika dashboard --auth-token`, `urika run --dry-run`, `urika run --review-criteria` — all shipped earlier but were missing from the CLI reference; now documented in `docs/16-cli-reference.md`.

**TUI slash commands now documented**

- `/pause`, `/stop`, `/copy [N]`, `/notifications`, `/delete-experiment` — shipped earlier but were missing from the slash-command tables in `docs/17-interactive-tui.md`.

**Documentation**

- `docs/14-configuration.md` now covers `~/.urika/settings.toml` (annotated schema) and `~/.urika/secrets.env` (format + the env-var-name indirection pattern that channels use).
- `docs/17-notifications.md` adds Troubleshooting and Caveats sections — per-channel error tables (Email / Slack / Telegram) with symptom → cause → fix, plus caveats covering email batching, health-check filtering, inline-keyboard scope, and the "channel-message-not-Slack-slash-command" Slack convention.
- `docs/19-notifications.md` (was 17) clarifies that Slack inbound commands work via channel messages, NOT via Slack-side Slash Commands API registration.
- `docs/03-core-concepts.md` and `docs/12-built-in-tools.md` reframe the 24 built-in tools as a "seed library" — not a fixed catalogue. Documents the **tool builder** agent's role in creating project-specific tools on demand, both automatically (via planner `needs_tool: true` flag) and explicitly (via `urika build-tool`, `/build-tool`, dashboard Build tool modal).

### Changed

**Notifications: vocabulary unification (foundation for everything else above)**

- Canonical event-type vocabulary in `notifications/events.py` (`EVENT_METADATA` keyed by frozen `EventMetadata` dataclass with emoji, priority, label). All channels read from this single source of truth instead of maintaining their own per-event maps.
- Previously-dropped events (`experiment_paused`, `experiment_stopped`, `meta_paused`, `meta_completed` on Slack) now render with their proper emoji and route through the right priority builder. The default ℹ fallback is no longer hit for any canonical event.
- Bus mapper (`_map_progress_event`) now translates orchestrator phase strings for `experiment_completed/failed/paused/stopped`. The orchestrator emits canonical phase events at every termination point so non-CLI surfaces (TUI direct-orchestrator-call, future programmatic callers) get notifications without going through the CLI direct-`notify()` path.
- Per-channel `health_check()` probes auth/config (Slack `auth_test`, Telegram `Bot.get_me`, Email SMTP `NOOP`). Failing channels are excluded from dispatch at `bus.start()` with a clear WARNING log instead of dying silently mid-run.
- Shared formatter helpers in `notifications/formatting.py` (`format_event_emoji`, `format_event_label`, `format_event_summary_line`) eliminate duplication across channels.

**Dashboard usage page is now provider-aware**

- Cost figures throughout are explicitly labelled as estimates ("Est. cost", "Tokens (est.)") with a top-of-page disclaimer pointing users to their model provider's console for authoritative billing. The disclaimer is provider-agnostic — Anthropic, OpenAI, Google, and private endpoints all map cleanly when the multi-provider runtime lands.

### Fixed

**Dashboard notification settings: 4 silent persistence bugs**

The dashboard SAVE handler and template GETs were using non-canonical key names that the channel constructors don't read. A user-saved notification config silently didn't activate at runtime. The dashboard's test-send code path masked the bugs by mapping correctly when constructing test-send channels. Fixed:
- Email password env: `smtp_password_env` → `password_env` (channel reads `password_env`).
- Email SMTP user: `smtp_user` → `username` (channel reads `username`).
- Email SMTP host: `smtp_host` → `smtp_server` (channel reads `smtp_server`). Templates have a legacy fallback so existing TOML files keep populating the form.
- Slack bot token env: `token_env` → `bot_token_env` (channel reads `bot_token_env`).
- Project email override: writes `to` (loader merges into channel's `to`) instead of `extra_to` (silently ignored).
- Project telegram override: writes `chat_id` instead of `override_chat_id` (silently ignored).

A new round-trip test (`PUT /api/settings → build channel from TOML → assert credential is reachable`) guards against regression.

**Notifications: silent failures and event-loop bugs**

- `EmailChannel._send_email` no longer swallows SMTP exceptions — failures now propagate so test-send and the bus dispatcher can surface them. Previously a misconfigured Gmail relay reported "✓ sent" with no email actually delivered.
- `TelegramChannel.health_check` and `send` now run their asyncio work in a fresh OS thread so calling them from inside a running event loop (FastAPI handler) no longer raises "Cannot run the event loop while another loop is running".
- Telegram routing now reads canonical metadata priority for routing decisions, not just emoji — fixes asymmetric formatting between Slack and Telegram for the same canonical event.

**Compliance, secrets, and dashboard auth surfacing**

- Dashboard `test-send` endpoint refreshes `~/.urika/secrets.env` before constructing channels, so credentials added by `urika notifications` (in another shell) are visible without restarting the long-lived dashboard process.
- Sessions list empty-state copy fixed — sessions are saved by terminal orchestrator chat, not by the advisor.
- `docs/19-dashboard.md` advisor file path corrected (`advisor-history.json`, not `advisor.json`); broken `07-advisor.md` link fixed; two contradictory sidebar-order claims reconciled to match `_sidebar.html`.
- `docs/16-interactive-tui.md` Session Memory section: removed false `urika --resume` claim (no such flag — use `/resume-session` inside the TUI). `/new-session` flipped from "(planned)" to documented.
- `docs/20-security.md` task-agent code path corrected (`experiments/<id>/methods/`, not `code/`).

**Misc**

- Dashboard sessions list page: Resume button now uses `btn--primary` (blue), Delete uses `btn--danger` (red); rows vertically centred with breathing room. Was crammped at the right edge with no colour.
- TUI `/resume-session` no longer suggests a project name on tab completion — it takes a session number, not a project.
- Email channel: SMTP user field gains placeholder + help text ("usually the same as From address") so first-time setup is less ambiguous; save handler drops empty values so the channel's own fallback (`username = config.get(..., self._from)`) kicks in.
- Email password env field gains inline note pointing to https://myaccount.google.com/apppasswords for Gmail App Password setup.

### Documentation: stale claims fixed

- Tool count: 18 → 24 across `README.md`, `docs/README.md`, `docs/03-core-concepts.md`, `docs/12-built-in-tools.md`. Six new tool entries added with full property tables (`cluster_analysis`, `linear_mixed_model`, `pca`, `polynomial_regression`, `regularized_regression`, `time_series_decomposition`). Tool categories grew from 5 to 7 (added Dimensionality Reduction + Time Series).
- Agent count: 11 → 12 across `docs/03-core-concepts.md`, `docs/11-agent-system.md`, `README.md`, `CLAUDE.md`. The previously-undocumented **Project Summarizer** agent is now in `docs/11-agent-system.md` with its full property table.
- Audience defaults: docs now correctly describe three modes (`novice`, `standard`, `expert`) with `standard` as the default. Was claiming two modes with `expert` as default in `docs/14-configuration.md` and `docs/16-cli-reference.md`.

### Tests

- 2288 → 2395 tests (+107). New coverage for canonical event metadata, channel emoji/priority routing, bus mapper run-status branches, send-test helper, dashboard test-send endpoint + Send-test button, Slack inbound-field round-trip, per-channel health checks, bus startup filtering, dashboard sessions list page, session delete endpoint, advisor `?session_id=` pre-load, auto-prune on save, project-switch hint with relative time, API-key compliance helpers (CLI warning, hard refusal, OAuth scrub), `urika config api-key` interactive flow, `urika config api-key --test` end-to-end check, dashboard notification round-trip regression, and dashboard compliance banner.


## [0.2.0] - 2026-04-25

A polish-and-foundations release. User-visible improvements to presentations and the TUI; a substantial internal refactor that splits six 1,100+ line files into focused modules; release-readiness work including security documentation and CI.

### Added

**Presentations**
- New `standard` audience mode (now the default) — verbose speaker notes, restrained on-slide bullets. Sits between `expert` (terse) and `novice` (full plain-English walkthrough).
- Speaker notes are now required on every slide and render into reveal.js's speaker-view (`<aside class="notes">`, press `S` in a deck). The slide is the headline; the notes carry the explanation.
- New `explainer` slide type — lead sentence + short paragraph body — for method-introduction slides.
- Visible "Figure missing: <path>" placeholder when an agent references a figure that doesn't exist (was previously a silent broken `<img>`).

**CLI**
- `urika run --dry-run` — preview the planned pipeline (agents, tools, writable directories, where task-agent code will be written) without invoking any agent.
- `urika config provider/model` subcommands and `--audience standard` choice everywhere `--audience` is accepted.

**TUI**
- `/copy [N]` slash command — copy the last N output-panel lines to the clipboard via `pyperclip`. Terminal-agnostic fallback for sessions where Shift+drag doesn't forward.
- Opt-in per-command timeout in the worker — `_COMMAND_TIMEOUTS` dict maps command name → seconds, prevents forever-hangs on handlers that block on non-stdin resources.

**Notifications**
- Slack channel now supports `allowed_channels` and `allowed_users` allowlists; unauthorized interactions are dropped with a WARNING log. Startup warns if neither list is set (the bot is unrestricted).

**Errors**
- New typed-error hierarchy in `urika.core.errors` — `UrikaError` base + `ConfigError`, `AgentError`, `ValidationError` subclasses with optional actionable hints. CLI top-level handler renders them as `Error: <msg>` + `hint: <hint>` and exits 2 without a traceback.

**Documentation**
- New `docs/18-security.md` — explains agent-generated code execution, permission boundaries, secrets, dashboard/notifications security posture.

**CI**
- GitHub Actions workflow tests Python 3.11 + 3.12 with ruff + pytest on every push/PR to `main` and `dev`.

### Changed

**Refactoring (behavior-preserving)** — six files over 1,100 lines split along natural seams; every public entry-point preserved via re-exports. No external API changes.
- `orchestrator/loop.py` 1,114 → 647 lines + `loop_criteria.py`, `loop_display.py`, `loop_finalize.py`
- `cli/agents.py` 1,186 → 564 lines + `agents_report.py`, `agents_finalize.py`, `agents_present.py`
- `cli/project.py` 1,198 → 112 lines + `project_new.py`, `project_inspect.py`
- `cli/run.py` 1,269 → 933 lines + `run_planning.py`, `run_advisor.py`
- `repl/commands.py` 1,274 → 826 lines + `commands_registry.py`, `commands_run.py`, `commands_session.py`
- `cli/config.py` 1,341 → 369 lines + `config_setup.py`, `config_notifications.py`
- `cli_display.py` 967 → 546 lines + `cli_display_panels.py`

**Defaults**
- Default audience for `report` / `present` / `finalize` agents is now `standard` (was `expert`).

**Dependencies**
- `textual` pinned to `>=8.0,<9.0` to protect against major-version breakage in `tui/capture.py`'s private-attribute use
- `claude-agent-sdk` pinned to `>=0.1,<1.0`
- New: `pyperclip>=1.8` (for `/copy`)

### Fixed

- 18 pre-existing lint errors across the tree (mostly unused imports from older refactors); CI now starts green.

### Removed

- The archived TypeScript TUI experiment at `dev/archive/typescript-tui/` (9,772 tracked lines). Preserved in git history at commit `e07e747c` if ever needed.

### Tests

- 1,389 → 1,472 tests (+83). New coverage for: audience modes, presentation speaker notes + explainer slide + missing-figure placeholder, `/copy` command, worker-command timeout, Slack allowlist, typed-error rendering, `_agent_run_start` helper, plus 16 tests filling gaps in `orchestrator/meta.py`, `core/labbook.py`, and `dashboard/renderer.py`.


## [0.1.0] - 2026-03-30

Initial pre-release.

### Added

- Multi-agent orchestration system with 11 specialized agent roles
- Experiment lifecycle: planning, task execution, evaluation, advisory loop
- Meta-orchestrator for autonomous multi-experiment campaigns
- Finalization sequence: standalone methods, findings, reports, presentations
- 18 built-in statistical and ML tools
- Knowledge pipeline with PDF, text, and URL extractors
- Interactive REPL with 25+ slash commands
- CLI with 20+ commands
- Notification system (Email, Slack, Telegram) with remote control
- Pause/stop/resume for experiments and multi-experiment runs
- Reveal.js presentation generation
- Project builder with data profiling and multi-format support
- Versioned criteria system with advisor-driven evolution
- Method registry tracking all approaches across experiments
- Auto-generated labbooks, reports, and README files
- Privacy-aware hybrid endpoint model (public/private)
- 1072 tests

