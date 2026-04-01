# Changelog

All notable changes to Urika will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Project dashboard (`urika dashboard`) — browser-based read-only project viewer with curated tree, markdown/image/JSON rendering, light/dark mode
- Audience modes (`--audience novice/expert`) — control explanation depth in reports and presentations
- Persistent advisor memory — conversation history and rolling context summary across sessions
- Pending experiment suggestions — advisor plans survive REPL restarts and work with remote commands
- Viewport-locked presentation CSS — slides scale to any screen size, no content overflow
- Zoomable figures in presentations — click to enlarge in lightbox overlay
- Presentation layout guidelines — full-width figures by default, hard content limits per slide

### Changed
- Remote commands (Telegram/Slack) now execute through REPL with full terminal output instead of subprocess
- Meta-orchestrator checks pending experiments and saved suggestions before calling advisor
- `_LOWER_IS_BETTER` metric set expanded and synchronized across modules

### Fixed
- Telegram chat_id verification for inbound commands
- Stale lock file detection using PID tracking
- Final report writing in finalization sequence
- Signal handler crash when running from background thread
- Event loop conflict in Telegram advisor calls
- Duplicate notification bus preventing Telegram polling
- JSON blocks stripped from remote command responses


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
