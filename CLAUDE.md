# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Urika is a multi-agent scientific analysis and modelling platform for behavioral and health sciences. Users create projects (one dataset + one research question each), and Urika's agents autonomously explore analytical approaches, build tools, evaluate methods, and document everything in a structured labbook.

## Hierarchy

- **Project**: One dataset + one research question. Created via `urika new`.
- **Experiment**: A distinct analytical campaign within a project (e.g., "baseline linear models").
- **Run**: A single method execution with specific parameters within an experiment.

## Agent Roles (Research Team Model)

- **Project Builder**: Scopes projects with users (interactive setup)
- **Task Agent**: Writes Python code, runs experiments, records observations
- **Evaluator**: Read-only scoring, validates against success criteria
- **Suggestion Agent**: Analyzes results, proposes next experiments
- **Tool Builder**: Creates project-specific tools and skills
- **Literature Agent**: Searches papers, builds knowledge base
- **Orchestrator**: Hybrid deterministic loop + LLM at strategic decision points

## Key Design Documents

- `docs/plans/2026-03-05-project-structure-design.md` — Approved design for project structure
- `docs/plans/2026-03-05-project-foundation.md` — Implementation plan (Phase 1: foundation)
- `docs/.archive/option-a-claude-agent-sdk.md` — Claude Agent SDK runtime option
- `docs/.archive/option-b-build-on-pi.md` — Pi SDK runtime option
- `docs/.archive/option-c-custom-runtime.md` — Custom runtime option

## Runtime Strategy

Build on Claude Agent SDK first (v0.x), later build custom Python runtime (v1.x) for model-agnostic support.

## Target Domains

Statistical modelling, machine learning, time series, neuroscience, cognitive neuroscience, linguistics, psychology, motor control, and behavioral data.

## Core Modules

- `src/urika/cli.py` — Click CLI: `new`, `list`, `status`, `experiment`, `results`, `methods`, `tools`, `run`, `knowledge`
- `src/urika/core/models.py` — Data models: `ProjectConfig`, `ExperimentConfig`, `RunRecord`, `SessionState`
- `src/urika/core/registry.py` — Central project registry at `~/.urika/projects.json`
- `src/urika/core/workspace.py` — Project workspace creation and loading
- `src/urika/core/experiment.py` — Experiment lifecycle: create, list, load
- `src/urika/core/progress.py` — Append-only progress tracking with best-run queries
- `src/urika/core/labbook.py` — Auto-generated .md summaries from progress data
- `src/urika/agents/` — Agent roles (task_agent, evaluator, suggestion_agent, tool_builder, literature_agent), registry, config, Claude SDK adapter
- `src/urika/orchestrator/` — Deterministic loop (task→evaluator→suggestion), output parsing, knowledge integration
- `src/urika/evaluation/` — Leaderboard ranking, metric computation
- `src/urika/methods/` — Built-in methods (linear_regression, random_forest, paired_t_test), method registry
- `src/urika/tools/` — Built-in tools (data_profiler, correlation_analysis), tool registry
- `src/urika/knowledge/` — Knowledge pipeline: extractors (PDF, text, URL), KnowledgeStore, keyword search

## Project Status

528 tests. Foundation, agents, orchestrator, evaluation, methods, tools, knowledge pipeline, and CLI all implemented. Next: session management (run --continue), report generation, end-to-end testing.

## Development

```bash
pip install -e ".[dev]"   # Install with dev dependencies
pytest -v                  # Run tests
ruff check src/ tests/     # Lint
ruff format src/ tests/    # Format
```
