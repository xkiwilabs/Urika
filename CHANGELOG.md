# Changelog

All notable changes to Urika will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

