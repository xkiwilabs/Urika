# Documentation

| Guide | Description |
|-------|-------------|
| [01 Getting Started](01-getting-started.md) | Installation, requirements, API key setup, quickstart |
| [02 Interfaces Overview](02-interfaces-overview.md) | CLI, TUI, and dashboard as three peer interfaces — when to use which |
| [03 Core Concepts](03-core-concepts.md) | Projects, experiments, runs, methods, tools, agents |
| [04 Creating Projects](04-creating-projects.md) | `urika new`, data scanning, profiling, knowledge ingestion |
| [05 Prompts and Context](05-prompts-and-context.md) | Writing effective descriptions, instructions, knowledge ingestion |
| [06 Running Experiments](06-running-experiments.md) | Orchestrator loop, turn limits, auto mode, resume |
| [07 Advisor Chat and Instructions](07-advisor-and-instructions.md) | Standalone advisor conversations, steering agents, the suggestion-to-run flow |
| [08 Viewing Results](08-viewing-results.md) | Reports, presentations, leaderboard, usage stats |
| [09 Finalizing Projects](09-finalizing-projects.md) | Finalization sequence, standalone methods, reproducibility |
| [10 Knowledge Pipeline](10-knowledge-pipeline.md) | Ingesting papers and PDFs, searching |
| [11 Agent System](11-agent-system.md) | All 12 agent roles, orchestrator, security boundaries |
| [12a Tools Overview](12a-tools-overview.md) | Philosophy, ITool / ToolResult API, registry, project-specific tools |
| [12b Tools Catalogue](12b-tools-catalogue.md) | Per-category reference for all 24 built-in tools |
| [13a Models and Privacy](13a-models-and-privacy.md) | Privacy modes, hybrid architecture, per-agent endpoint assignment |
| [13b Local Models](13b-local-models.md) | Ollama, LM Studio, vLLM/LiteLLM proxy setup, tested-models table |
| [14a Project Configuration](14a-project-config.md) | Per-project `urika.toml`, criteria, methods, usage |
| [14b Global Configuration](14b-global-config.md) | `~/.urika/settings.toml`, secrets vault, environment variables |
| [15 Project Structure](15-project-structure.md) | File layout and what each file does |
| [16a CLI Reference — Projects](16a-cli-projects.md) | `urika new`, `list`, `delete`, `status`, `inspect`, `update` |
| [16b CLI Reference — Experiments](16b-cli-experiments.md) | `urika experiment` group and `urika run` |
| [16c CLI Reference — Results and Reports](16c-cli-results.md) | `dashboard`, `results`, `methods`, `logs`, `report`, `present`, `criteria`, `usage` |
| [16d CLI Reference — Agents](16d-cli-agents.md) | `advisor`, `evaluate`, `plan`, `finalize`, `build-tool`, `summarize` |
| [16e CLI Reference — System](16e-cli-system.md) | `knowledge`, `venv`, `config`, `notifications`, `setup`, `tools`, env vars |
| [17 Interactive TUI](17-interactive-tui.md) | TUI interface, slash commands, tab completion, orchestrator chat |
| [18a Dashboard — Pages](18a-dashboard-pages.md) | Pages, modals, live log, advisor chat, sessions, sidebar, theme |
| [18b Dashboard — Operations](18b-dashboard-operations.md) | Lockfiles, idempotent spawn endpoints, completion CTAs, project deletion |
| [18c Dashboard — Settings](18c-dashboard-settings.md) | Project + global settings, notification test-send, `--auth-token` |
| [18d Dashboard — API](18d-dashboard-api.md) | Cross-surface coordination, HTMX/fetch endpoint reference, tech stack |
| [19a Notifications — Channels](19a-notifications-channels.md) | Email, Slack, Telegram setup walkthroughs |
| [19b Notifications — Remote](19b-notifications-remote.md) | Remote `/commands`, what gets notified, troubleshooting, caveats |
| [20 Security Model](20-security.md) | Agent-generated code, permission boundaries, secrets, dashboard/notifications security |
| [Contributing an Adapter](contributing-an-adapter.md) | Plugging a different agent backend into Urika via the `urika.runners` entry-point group |
