# Urika — Current Status

**Date:** 2026-03-20
**Version:** v0.1 (pre-release)
**Tests:** 794 passing

## What's Built

### Core Infrastructure
- **Project lifecycle**: create, register, list, load, inspect
- **Project Builder**: source scanning, data profiling, multi-file dataset support, builder prompts for interactive agent setup
- **Multi-file dataset support**: projects can reference multiple data files (CSV, Excel, Parquet, JSON, etc.)
- **Experiment lifecycle**: create, list, load, progress tracking
- **Session management**: start, pause, resume, complete, fail, lockfiles
- **Labbook**: auto-generated notes, summaries, key findings from progress data
- **Evaluation**: leaderboard ranking, 9 built-in metrics (R², RMSE, MAE, accuracy, F1, precision, recall, AUC, Cohen's d)
- **Knowledge pipeline**: PDF/text/URL extractors, KnowledgeStore with keyword search

### 16 Built-in Tools
| Tool | Category | Purpose |
|------|----------|---------|
| data_profiler | exploration | Dataset profiling with summary statistics |
| correlation | exploration | Correlation matrix and top correlations |
| outlier_detection | exploration | IQR and z-score outlier detection |
| visualization | exploration | Histogram, scatter, and box plots |
| hypothesis_tests | statistics | T-test, chi-squared, normality (Shapiro-Wilk) |
| descriptive_stats | statistics | Summary stats with skew and kurtosis |
| train_val_test_split | preprocessing | Train/val/test split with stratification |
| cross_validation | preprocessing | K-fold CV with optional stratification |
| group_split | preprocessing | LOGO CV and group-based splitting (participant-level) |
| linear_regression | regression | OLS linear regression |
| logistic_regression | classification | Logistic regression classifier |
| random_forest | regression | Random forest regression |
| xgboost_regression | regression | Gradient boosting regression |
| paired_t_test | statistical_test | Paired t-test for related samples |
| one_way_anova | statistical_test | One-way ANOVA |
| mann_whitney_u | statistical_test | Mann-Whitney U non-parametric test |

### Agent System
- **Project Builder**: interactive project setup (via `urika new`)
- **Planning Agent**: designs analytical method pipelines (read-only)
- **Task Agent**: implements methods as Python scripts using tools
- **Evaluator**: scores results against success criteria (read-only)
- **Suggestion Agent**: proposes next experiments based on evaluation
- **Tool Builder**: creates new tools, can pip install packages
- **Literature Agent**: searches knowledge base for relevant papers/techniques

### Orchestrator
Loop: `planning → task → evaluator → suggestion → (repeat)`
Support agents (on-demand): tool_builder, literature_agent

### CLI (15 commands)
`new`, `list`, `status`, `experiment create/list`, `results`, `methods`, `tools`, `run`, `run --continue`, `report`, `inspect`, `logs`, `knowledge ingest/search/list`

### Methods (Agent-Created Pipelines)
The `methods/` package provides the `IMethod` ABC for agent-created analytical pipelines. Methods are complete workflows combining multiple tools (preprocessing, modelling, evaluation). Zero built-in methods — the agent system creates these at runtime.

## What's NOT Yet Tested with Real Data

The entire agent execution path has only been tested with mocks:

1. **Claude SDK integration** — `ClaudeSDKRunner` calls to real Claude have never been tested end-to-end
2. **Agent prompt effectiveness** — prompts may need tuning after first real run
3. **Output parsing robustness** — `parse_run_records`, `parse_evaluation`, `parse_suggestions`, `parse_method_plan` depend on Claude returning well-formed JSON
4. **Planning agent → task agent flow** — the planning agent produces a method plan, task agent implements it. This chain is untested with real LLM output.
5. **Tool builder creating new tools** — the tool builder can write Python and pip install, but hasn't been exercised
6. ~~**Known issue**: evaluator prompt references `urika.json` but projects use `urika.toml`~~ **FIXED**

## Recommended Next Steps

### Immediate (Real-World Validation)
1. ~~**Fix evaluator prompt**~~ **DONE**
2. **Run a real experiment** — pick a simple dataset (e.g., Iris, Boston housing), create a project, run 2-3 turns with real Claude, observe agent behavior
3. **Tune prompts** — based on real output, adjust agent prompts for better JSON output, tool usage, and pipeline design
4. **Harden output parsing** — add fallback/retry logic if Claude doesn't produce valid JSON blocks

### Short-Term (Robustness)
5. ~~**Project builder agent**~~ **FOUNDATION DONE** — source scanning, data profiling, multi-file dataset support, and builder prompts implemented. Next: interactive agent loop and first real test with a dataset.
6. **Method persistence** — the task agent creates method scripts but there's no standard location or auto-registration yet. Wire up `project_dir/methods/` for agent-written method modules
7. **Tool builder integration test** — test the full tool_builder flow: identify need → create tool → register → use in next run
8. **Error recovery** — improve graceful handling when agents fail mid-loop (partial results, retry logic)

### Medium-Term (Usability)
9. **Dataset auto-loading** — project builder now profiles datasets at creation; next step is injecting profiles into agent context automatically
10. **Progress dashboard** — richer `urika status` with per-experiment metrics, trends, and method comparison
11. **Export/share** — export best method as standalone Python script
12. ~~**Multi-dataset support**~~ **DONE** — project builder supports multi-file datasets with source scanning
