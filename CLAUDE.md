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
- **Finalizer**: Selects best methods, writes standalone code, produces findings.json, requirements.txt, reproduce scripts
- **Orchestrator**: Hybrid deterministic loop (planning→task→evaluator→advisor) + LLM at strategic decision points; finalize sequence (finalizer→report→presentation→README)

## Runtime

Built on Claude Agent SDK. Agents run as Claude Code subprocesses with configured tools, permission boundaries, and security policies.

## Target Domains

Statistical modelling, machine learning, time series, neuroscience, cognitive neuroscience, linguistics, psychology, motor control, and behavioral data.

## Core Modules

- `src/urika/cli.py` — Click CLI: `new`, `list`, `status`, `experiment`, `results`, `methods`, `tools`, `run`, `report`, `inspect`, `logs`, `knowledge`, `advisor`, `evaluate`, `present`, `plan`, `finalize`, `build-tool`, `criteria`, `usage`
- `src/urika/cli_display.py` — Terminal display: colors, spinners, ThinkingPanel, agent labels, ASCII header
- `src/urika/repl.py` — Interactive REPL shell with prompt_toolkit, tab completion, slash commands
- `src/urika/repl_commands.py` — REPL slash command handlers (/run, /project, /report, /present, /advisor, /evaluate, /plan, /finalize, /build-tool, /results, /tools, /resume, etc.)
- `src/urika/repl_session.py` — REPL session state: project context, advisor conversation history
- `src/urika/core/models.py` — Data models: `ProjectConfig`, `ExperimentConfig`, `RunRecord`, `SessionState`
- `src/urika/core/registry.py` — Central project registry at `~/.urika/projects.json`
- `src/urika/core/workspace.py` — Project workspace creation and loading
- `src/urika/core/project_builder.py` — Project builder: source scanning, data profiling, multi-file dataset support, knowledge ingestion
- `src/urika/core/source_scanner.py` — Scans data sources (CSV, Excel, Parquet, JSON, etc.) and detects file types, sizes, and structure
- `src/urika/core/builder_prompts.py` — Prompt templates for the interactive project builder agent
- `src/urika/core/experiment.py` — Experiment lifecycle: create, list, load
- `src/urika/core/progress.py` — Append-only progress tracking with best-run queries
- `src/urika/core/labbook.py` — Auto-generated .md summaries from progress data, inline figures
- `src/urika/core/criteria.py` — Versioned project criteria: load, append, history
- `src/urika/core/method_registry.py` — Project method registry: tracks methods, metrics, status
- `src/urika/core/readme_generator.py` — Auto-generated README.md with agent-written summary
- `src/urika/core/report_writer.py` — Versioned file writer (timestamped backups)
- `src/urika/core/presentation.py` — Render slide JSON into reveal.js HTML presentations
- `src/urika/agents/` — Agent roles (planning_agent, task_agent, evaluator, advisor_agent, tool_builder, literature_agent, presentation_agent, report_agent, project_builder, data_agent, finalizer), registry, config, Claude SDK adapter
- `src/urika/orchestrator/` — Experiment loop (planning→task→evaluator→advisor), meta-orchestrator (experiment-to-experiment), finalize sequence (finalizer→report→presentation→README), output parsing, knowledge integration
- `src/urika/evaluation/` — Leaderboard ranking, metric computation
- `src/urika/methods/` — Agent-created analytical pipelines (IMethod ABC, MethodRegistry), zero built-ins — agents create methods at runtime
- `src/urika/tools/` — Built-in tools (16: correlation_analysis, cross_validation, data_profiler, descriptive_stats, group_split, hypothesis_tests, linear_regression, logistic_regression, mann_whitney_u, one_way_anova, outlier_detection, paired_t_test, random_forest, train_val_test_split, visualization, xgboost_regression), tool registry
- `src/urika/knowledge/` — Knowledge pipeline: extractors (PDF, text, URL), KnowledgeStore, keyword search
- `src/urika/templates/presentation/` — Bundled reveal.js + CSS for slide decks

## Project Status

882+ tests. Foundation, agents (11 roles), orchestrator (experiment + meta + finalize), evaluation, methods (agent-created), tools (16 built-in), knowledge pipeline, CLI (20+ commands), REPL (interactive shell with 15+ slash commands), project builder, session management, report generation (template + agent narratives), presentation agent (reveal.js slides), finalizer agent (standalone methods, findings.json, reproducibility artifacts), criteria system (versioned, evolving), method registry, usage tracking, and end-to-end integration tests all implemented. Successfully tested on real DHT target selection data (5 experiments, 25 runs, 20+ methods).

## Development

```bash
pip install -e ".[dev]"   # Install with dev dependencies
pytest -v                  # Run tests
ruff check src/ tests/     # Lint
ruff format src/ tests/    # Format
```
