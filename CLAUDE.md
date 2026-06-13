# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Urika is a multi-agent scientific analysis and modelling platform. Users create projects (one dataset + one research question each), and Urika's agents autonomously explore analytical approaches, build tools, evaluate methods, and document everything in a structured projectbook.

## Hierarchy

- **Project**: One dataset + one research question. Created via `urika new`.
- **Experiment**: A distinct analytical campaign within a project (e.g., "baseline linear models").
- **Run**: A single method execution with specific parameters within an experiment.

## Agent Roles (Research Team Model)

- **Project Builder**: Scopes projects with users (interactive setup)
- **Planning Agent**: Reviews context and decides the next analytical step
- **Task Agent**: Writes Python code, runs experiments, records observations
- **Evaluator**: Read-only scoring, validates against success criteria
- **Advisor Agent**: Analyzes results, proposes next experiments
- **Tool Builder**: Creates project-specific tools and skills
- **Literature Agent**: Searches papers, builds knowledge base
- **Data Agent**: Extracts and prepares features in hybrid privacy mode (local data access)
- **Report Agent**: Writes experiment narratives, project summaries, README content
- **Presentation Agent**: Creates reveal.js slide decks from experiment results
- **Finalizer**: Selects best methods, writes standalone code, produces findings.json, requirements.txt, reproduce scripts
- **Orchestrator**: Hybrid deterministic loop (planning→task→evaluator→advisor) + LLM at strategic decision points; finalize sequence (finalizer→report→presentation→README)

## Runtime

Built on Claude Agent SDK. Agents run as Claude Code subprocesses with configured tools, permission boundaries, and security policies.

## Target Domains

Statistical modelling, machine learning, time series, neuroscience, cognitive neuroscience, linguistics, psychology, motor control, and behavioral data.

## Core Modules

- `src/urika/cli/` — Click CLI: `new`, `list`, `status`, `inspect`, `delete`, `update`, `experiment` (create/list/delete), `run`, `results`, `methods`, `tools`, `report`, `logs`, `knowledge`, `advisor`, `evaluate`, `present`, `plan`, `finalize`, `build-tool`, `criteria`, `usage`, `summarize`, `dashboard`, `setup`, `config` (api-key/secret/notifications/endpoints), `notifications`, `venv` (create/status), `tui`
- `src/urika/cli_display.py` — Terminal display: colors, spinners, ThinkingPanel, agent labels, ASCII header
- `src/urika/tui/` — **Textual TUI (default)**: three-zone layout (OutputPanel + InputBar + StatusBar), background Workers for agent commands, OutputCapture routing print/click.echo to the panel, stdin bridge for interactive prompts (click.prompt/input), animated ActivityBar spinner, tab completion with contextual suggester, CSS theme
- `src/urika/repl/` — Classic prompt_toolkit REPL (fallback via `urika --classic`), tab completion, slash commands, async main loop with background threads
- `src/urika/repl/commands.py` — Slash command handlers shared by both TUI and REPL (/run, /project, /report, /present, /advisor, /evaluate, /plan, /finalize, /build-tool, /results, /tools, /resume, /config, /notifications, etc.)
- `src/urika/repl/session.py` — Session state: project context, usage tracking, agent activity, processing time accumulator
- `src/urika/core/models.py` — Data models: `ProjectConfig` (incl. research-intent fields: hypotheses, analysis approach, interpretability, constraints), `ExperimentConfig`, `RunRecord` (incl. `metric_interpretation`), `SessionState`
- `src/urika/core/registry.py` — Central project registry at `~/.urika/projects.json`
- `src/urika/core/workspace.py` — Project workspace creation and loading
- `src/urika/core/project_builder.py` — Project builder: source scanning, data profiling, multi-file dataset support, knowledge ingestion, research-goal pipeline (research-question feasibility check with refinement offer, preferences/hypotheses/constraints elicitation, success-criteria co-drafting)
- `src/urika/core/source_scanner.py` — Scans data sources (CSV, Excel, Parquet, JSON, etc.) and detects file types, sizes, and structure
- `src/urika/core/builder_prompts.py` — Prompt templates for the interactive project builder agent
- `src/urika/core/experiment.py` — Experiment lifecycle: create, list, load
- `src/urika/core/progress.py` — Append-only progress tracking with best-run queries
- `src/urika/core/labbook.py` — Auto-generated .md summaries from progress data, inline figures
- `src/urika/core/criteria.py` — Versioned project criteria: load, append, history
- `src/urika/core/method_registry.py` — Project method registry: tracks methods, metrics, status
- `src/urika/core/readme_generator.py` — Auto-generated README.md with agent-written summary
- `src/urika/core/method_glossary.py` — Plain-language one-line method explainers for novice-audience labbook/README (alias + fuzzy lookup over built-in tool names)
- `src/urika/core/report_writer.py` — Versioned file writer (timestamped backups)
- `src/urika/core/export.py` — Pandoc-based markdown→LaTeX/PDF export (`--format` on `report`/`finalize`; `urika[export]` extra; three distinct actionable ExportErrors: pypandoc missing / pandoc binary missing / TeX engine missing)
- `src/urika/core/model_cards.py` — Deterministic `methods/<name>_model_card.md` per finalized method from findings.json + run records + persisted evaluation.json (finalize hook, pure code, never invents content)
- `src/urika/core/metrics_glossary.py` — `projectbook/METRICS.md` glossary of observed metrics (~15-entry static `METRIC_GLOSSARY` + alias/suffix lookup, direction, observed range/best, CIs; finalize hook)
- `src/urika/core/notebook_export.py` — `projectbook/reproduce.ipynb` from findings.json: literal final-method scripts as code cells, key metrics incl. CIs, nbformat-validated (finalize hook, pure code)
- `src/urika/core/presentation.py` — Render slide JSON into reveal.js HTML presentations
- `src/urika/core/advisor_memory.py` — Persistent advisor conversation history and rolling context summaries
- `src/urika/core/orchestrator_sessions.py` — Cross-session orchestrator chat persistence at `<project>/.urika/sessions/`, auto-prune at 20, dashboard Sessions tab feed
- `src/urika/core/vault.py` — Tiered secrets vault (process env → project `.env` → global keyring/file), sidecar metadata, dashboard CRUD
- `src/urika/core/secrets.py` — v0.3 backward-compat shim over `SecretsVault`
- `src/urika/core/known_secrets.py` — Registry of well-known secret names + `LLM_PROVIDERS` (locked-row metadata for not-yet-supported providers)
- `src/urika/core/compliance.py` — Anthropic auth hygiene: two-mode auth (api_key default / opt-in subscription per the June-15-2026 Agent SDK credit-pool policy); pre-spawn API-key refusal in api_key mode; OAuth-token scrubbing as billing hygiene (mode-conditional); nested-session markers always scrubbed (pre-June-2026 §3.7 rationale retained as historical provenance)
- `src/urika/core/privacy.py` — Privacy preflight (bearer-token-aware GET to `/v1/models` for auth-protected private endpoints)
- `src/urika/core/updates.py` — GitHub Releases update banner (suppressed in non-TTY)
- `src/urika/core/usage.py` — Per-project cost / token tracking, aggregated totals + per-session list
- `src/urika/core/session.py` — Experiment session lifecycle (running / paused / stopped / completed / failed), PID-aware lockfile probes
- `src/urika/core/json_io.py` — Corrupt-tolerant JSON loading: `load_json_or_preserve` returns a fallback instead of raising and preserves corrupt bytes as timestamped `.corrupt-<ts>` siblings
- `src/urika/agents/` — Agent roles (planning_agent, task_agent, evaluator, advisor_agent, tool_builder, literature_agent, presentation_agent, report_agent, project_builder, data_agent, finalizer, project_summarizer), registry, config, SDK adapters (Claude SDK / OpenAI Agents SDK / Google ADK in `adapters/`), audience.py
- `src/urika/agents/error_classify.py` — Shared error classification (rate-limit / auth / transient / fatal) used identically by all three SDK adapters
- `src/urika/agents/adapters/_common.py` — Shared adapter tunables: env-tunable stream-silence timeout (`URIKA_AGENT_STREAM_TIMEOUT`) + bash-timeout cap honoring `max_method_seconds`
- `src/urika/orchestrator/` — Experiment loop (planning→task→evaluator→advisor), autonomous mode (experiment-to-experiment), finalize sequence (finalizer→report→presentation→README), output parsing, knowledge integration, conversational OrchestratorChat (maintains conversation state, calls subagents via Bash, recommends slash commands for long-running operations)
- `src/urika/evaluation/` — Leaderboard ranking, metric computation; `metrics/base.py` `IMetric.compute_with_ci` adds bootstrap-percentile confidence intervals to every metric (v0.9.0)
- `src/urika/evaluation/ranking.py` — Canonical best-run selection (`select_best_run`, `LOWER_IS_BETTER`, `metric_direction`); labbook, progress, leaderboard, readme_generator, and orchestrator loop_criteria all delegate here
- `src/urika/methods/` — Agent-created analytical pipelines (IMethod ABC, MethodRegistry), zero built-ins — agents create methods at runtime
- `src/urika/tools/` — Built-in tools (24: cluster_analysis, correlation_analysis, cross_validation, data_profiler, descriptive_stats, feature_scaler, gradient_boosting, group_split, hypothesis_tests, linear_mixed_model, linear_regression, logistic_regression, mann_whitney_u, one_way_anova, outlier_detection, paired_t_test, pca, polynomial_regression, random_forest, random_forest_classifier, regularized_regression, time_series_decomposition, train_val_test_split, visualization), tool registry
- `src/urika/data/` — Data loading and profiling: multi-format loader, data models, profiler, pluggable readers (CSV, with registry for extensions)
- `src/urika/knowledge/` — Knowledge pipeline: extractors (PDF, text, URL), KnowledgeStore, keyword search
- `src/urika/templates/presentation/` — Bundled reveal.js + CSS for slide decks
- `src/urika/dashboard/` — Browser-based dashboard (FastAPI + Jinja + HTMX + Alpine), peer to CLI and TUI: multi-page project views (home, experiments, methods, knowledge, advisor, sessions, data, usage, settings), New Project modal with full interactive builder wizard (Q&A loop incl. web_search/use_venv fields), New Experiment modal, planning agent, live SSE log streaming, settings forms with auth, light/dark theme. Includes Secrets tab (global + per-project) with vault CRUD and override-from-global flow, and Git tab (init/push/pull).
- `src/urika/notifications/` — Notifications bus (email / Slack / Telegram), remote command surface, dashboard test-send, canonical event vocabulary
- `src/urika/rpc/` — JSON-RPC server for external tooling

## Project Status

**v0.7.0 released 2026-06-08** — multi-provider adapters: OpenAI Agents SDK + Google ADK adapters alongside Claude SDK, model-prefix routing per agent role (`claude-*`/`gpt-*`/`gemini-*`), Anthropic subscription auth mode, dashboard Provider filter + auth-mode UI, REPL `/github` slash group, `urika config auto-capture`, Gemini-3.5-flash execution default. Prior: v0.6.0.1 Windows hotfix 2026-06-01; v0.6.0 GitHub auto-backup 2026-05-31 (thin design — zero auth surface, pure `git` shell-out + optional `gh` for `--create`; pre-commit secret scanner; researcher-safe `.gitignore`; opt-in auto_push after `run`/`finalize`/`build-tool`; dashboard Git tab); v0.5.0.2, v0.5.0.1, v0.5.0 (memory deepening) all 2026-05-31. ~4129 tests collected (4064 pass in the unit suite via `URIKA_SKIP_SMOKE=1 pytest -q -m "not integration"`; 93 in `tests/test_tui/`). Foundation, agents (13 roles incl. memory_curator + orchestrator), orchestrator (experiment + meta + finalize + conversational chat with subagent invocation), evaluation, methods (agent-created), tools (24-tool seed library + agent-built project-specific tools via tool_builder), knowledge pipeline, CLI (25+ commands), Textual TUI (default, three-zone layout with interactive stdin bridge), classic REPL (fallback via `--classic`), project builder, session management, report generation (template + agent narratives), presentation agent (reveal.js slides), finalizer agent (standalone methods, findings.json, reproducibility artifacts), criteria system (versioned, evolving), method registry, usage tracking, four-interface dashboard (run launching, SSE log streaming, advisor chat, vault CRUD, memory CRUD + curator UI, settings forms, notifications test-send), audience modes, persistent advisor memory, cross-session orchestrator session persistence, three-tier secrets vault (file + OS keyring backends), two-mode Anthropic auth (api_key / subscription) with OAuth billing-hygiene scrubbing, stop-button SIGTERM hardening, and end-to-end integration tests all implemented. Successfully tested on real DHT target selection data (35 experiments, 288 methods). **v0.5.0 memory deepening shipped**: advisor + report agents now READ project memory (closing the v1 read-side loop); memory_curator agent + dispatch with merge/archive/flag actions; soft-cap auto-trigger (once per session, DRY-RUN by default — Decision 4); token budget enforcement (bytes/3.5 conservative heuristic, soft 5K / hard 10K, oldest-first truncation); dashboard memory page (list/add/edit/delete + Curate/Apply UI); archive viewer + mtime-based diff (`urika memory archive`, `urika memory diff`); per-project `auto_capture` toggle; cross-surface parity tests pin curator invocation, CRUD path, and archive path. **Shipped since v0.3.2**: SecurityPolicy genuinely enforced (runtime `can_use_tool` callback in `src/urika/agents/permission.py`, fail-closed on unresolvable paths), prompt-cache (v0.4.3, ~90% real-API hit ratio) + cross-platform CI, surface parity across CLI/TUI/REPL/dashboard (v0.4.5), default-secure dashboard (auto-generated auth token + Origin/CSRF guard + SSRF blocklist, v0.4.5.1 hardening), and v0.5.0 memory deepening.

**v0.8.0 released 2026-06-10** (tag `v0.8.0` at `b912b939` on both remotes; GitHub release: https://github.com/xkiwilabs/Urika/releases/tag/v0.8.0; validated by 3 real-API smoke iterations that caught + fixed 3 additional bugs: claude-agent-sdk 0.2.91 max-turns tolerance + SDK pin, `urika present` honest failure reporting + project-level prompt, durable run-record contract incl. `artifacts/` discovery) — hardening: corrupt-JSON tolerance across state files (shared `core/json_io.py` loader, preserves corrupt bytes as timestamped `.corrupt-<ts>` siblings), June-15-2026 subscription credit-pool messaging refresh, OpenAI/Google adapter parity with Claude (stream-hang timeouts, error categorization via shared `agents/error_classify.py`, OAuth-scrubbed bash subprocess env, `max_method_seconds` honored in bash wrappers), structural real-import tests pinning SDK surfaces (caught + fixed a live OpenAI $0-usage bug — usage read from `raw_responses`), surface parity (REPL `/config` provider auth modes, dashboard planning agent + git pull, origin-guard case-insensitive host compare), and canonical best-run selection (`evaluation/ranking.py` — fixes labbook/README/leaderboard best-method disagreement). Plus v0.8 foundations: builder research-goal pipeline (research-question feasibility check with refinement offer, preferences/hypotheses/constraints elicitation, success-criteria co-drafting, `ProjectConfig` research-intent fields, dashboard builder-wizard completion + web_search/use_venv modal fields) and output comprehensibility (`RunRecord.metric_interpretation` plain-language metric readings, evaluator `assumptions_detail` into reports, run-id traceability in findings.json + run-id-first figure matching, audience-aware labbook/README novice explainers via `core/method_glossary.py`).

**v0.9.1 (report-integrity hotfix) released 2026-06-13** (tag `v0.9.1`) — fixes a long-latent bug where the read-only report agent's narration ("I'll write a report… I successfully wrote…") clobbered `projectbook/final-report.md` instead of the report (root cause: prompt told a no-Write agent to write a file; introduced 2026-03-30, masked since v0.3 by a weak heuristic that newer models' narration slipped past). Now every report/narrative/summary write validates output via `core/report_writer.extract_report_markdown`/`looks_like_narration` and the prompts tell the agent its reply IS the report. Also: dashboard recognizes `final-report.md` (the link/route looked only for `report.md`/`narrative.md`); `reproduce.ipynb` tolerates a script's clean `sys.exit(0)`; release smoke now asserts reports are reports (heading + sections + no chatter) and presentations are rendered decks. Comprehensive audit confirmed all other agent-output→file sites are safe (JSON-parser-gated or agent-writes-directly).

**v0.9.0 (output polish) released 2026-06-13** (tag `v0.9.0` at `750da006` on both remotes; main at `bd371b78`; GitHub release: https://github.com/xkiwilabs/Urika/releases/tag/v0.9.0) — uncertainty foundations (`IMetric.compute_with_ci` bootstrap CIs, `RunRecord.metrics_with_uncertainty`, CI rendering in labbook + report-agent CI quoting), deterministic finalize artifacts (model cards per final method, `projectbook/METRICS.md`, `projectbook/reproduce.ipynb`), per-experiment `labbook/evaluation.json` persistence (assumptions_detail reaches model cards + reports), and pandoc-based PDF/LaTeX export (`urika[export]` extra; `--format markdown|latex|pdf` on `report`/`finalize` across CLI + REPL/TUI slashes). Release gate: cheap real-API smoke 45/45, which surfaced 3 contract fixes (reproduce.ipynb argv neutralization, finalizer data defaults copied verbatim from `data_paths`, tectonic PDF fallback). Plus release-prep fixes: dashboard auto-opens its tokenized URL + friendly HTML 401, and project-level presentations resolve figures across experiments (were all "Figure missing"). Implementation plan: `dev/plans/2026-06-10-v0.9.0-output-polish.md`; canonical roadmap: `dev/plans/2026-05-02-roadmap-to-v1.0.md`. **Next: v0.10.0 pre-1.0 hardening** (`urika upgrade`, builder-session persistence, agent-subprocess env isolation, accessibility; project templates CUT 2026-06-10) → v1.0.0rc cycle (~mid-July 2026).

## Development

```bash
pip install -e ".[dev]"   # Install with dev dependencies
pytest -v                  # Run tests
ruff check src/ tests/     # Lint
ruff format src/ tests/    # Format
```
