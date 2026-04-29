# Changelog

All notable changes to Urika will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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


## [Unreleased]

### Compliance

- **Urika now requires an `ANTHROPIC_API_KEY`** for all usage. Per Anthropic's
  Consumer Terms (§3.7) and the April 2026 Agent SDK clarification, a Claude
  Pro/Max subscription cannot be used to authenticate the Claude Agent SDK,
  which Urika depends on. New documentation in
  [docs/20-security.md#provider-compliance](docs/20-security.md#provider-compliance)
  covers the full rationale.
- A one-time warning prints at CLI startup when `ANTHROPIC_API_KEY` is unset.
  Dismiss by setting `URIKA_ACK_API_KEY_REQUIRED=1`.
- Dashboard Settings page shows a banner when no API key is configured.
- New `urika config api-key` interactive command for saving the key into
  `~/.urika/secrets.env`.

### Changed

**Notifications polish**

- Canonical event-type vocabulary in `notifications/events.py` (`EVENT_METADATA` keyed by frozen `EventMetadata` dataclass with emoji, priority, label). All channels (Slack, Telegram) read from this single source of truth instead of maintaining their own per-event maps. Previously dropped events (`experiment_paused`, `experiment_stopped`, `meta_paused`, `meta_completed` on Slack) now render with their proper emoji and route through the right priority builder.
- Bus mapper (`_map_progress_event`) now translates orchestrator phase strings for `experiment_completed`, `experiment_failed`, `experiment_paused`, `experiment_stopped`. The orchestrator emits canonical phase events at every termination point so non-CLI surfaces (TUI direct-orchestrator-call, future programmatic callers) get notifications without going through the CLI direct-`notify()` path.
- Per-channel `health_check()` probes auth/config (Slack `auth_test`, Telegram `Bot.get_me`, Email SMTP `NOOP`). Failing channels are excluded from dispatch at `bus.start()` with a clear WARNING log instead of dying silently mid-run.
- New dashboard endpoint `POST /api/settings/notifications/test-send` plus a Send-test button on Settings → Notifications. Tests un-saved form data so users can validate creds before clicking Save. Reports per-channel success / specific auth-error message inline.
- Slack settings tab now exposes the previously-missing inbound config fields (App token env var, Allowed channels, Allowed users) so Socket Mode commands can be enabled without hand-editing TOML.
- Shared formatter helpers in `notifications/formatting.py` (`format_event_emoji`, `format_event_label`, `format_event_summary_line`) eliminate duplication across Slack and Telegram channels.

### Documentation

- `docs/17-notifications.md` adds Troubleshooting and Caveats sections at the end. Per-channel troubleshooting tables (Email / Slack / Telegram) cover the most common auth and configuration failures with symptom → cause → fix. Caveats document the inline-keyboard scope, email batching, per-process health-check filtering, and other behaviours users should know up front.

### Tests

- 2288 → 2321 tests (+33). New coverage for canonical event metadata, channel emoji/priority routing, bus mapper run-status branches, send-test helper, dashboard test-send endpoint, Slack inbound-field round-trip, per-channel health checks, and bus startup filtering.


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

