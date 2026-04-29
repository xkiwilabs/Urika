# Changelog

All notable changes to Urika will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

