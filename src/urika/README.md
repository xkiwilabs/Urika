# urika

Source code for the Urika platform.

| Module | Purpose |
|--------|---------|
| `cli.py` | CLI entry point — all `urika` commands |
| `cli_display.py` | Terminal display — colors, spinners, ThinkingPanel, header |
| `repl.py` | Interactive REPL shell |
| `repl_commands.py` | REPL slash command handlers |
| `repl_session.py` | REPL session state and usage tracking |
| `core/` | Project lifecycle, experiments, progress, criteria, labbook, config |
| `agents/` | Agent roles (11), registry, config, Claude SDK adapter |
| `orchestrator/` | Experiment loop, autonomous mode, output parsing |
| `evaluation/` | Leaderboard ranking, metrics (R2, RMSE, F1, etc.) |
| `tools/` | 18 built-in analysis tools (regression, classification, stats, preprocessing) |
| `methods/` | IMethod ABC for agent-created analytical pipelines |
| `data/` | Dataset loading, profiling, CSV/Excel/Parquet readers |
| `knowledge/` | PDF/text/URL extractors, KnowledgeStore, search |
| `templates/` | Bundled reveal.js for presentation rendering |
