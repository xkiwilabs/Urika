# Urika — Current Status

**Date:** 2026-04-20
**Version:** v0.2-dev
**Tests:** 1389 passing

## What's Built

### Core Infrastructure
- **Project lifecycle**: create, register, list, load, inspect
- **Project Builder**: source scanning, data profiling, multi-file dataset support, builder prompts for interactive agent setup
- **Multi-file dataset support**: projects can reference multiple data files (CSV, Excel, Parquet, JSON, etc.)
- **Experiment lifecycle**: create, list, load, progress tracking
- **Session management**: start, pause, resume, complete, fail, lockfiles
- **Labbook**: auto-generated notes, summaries, key findings from progress data
- **Criteria system**: versioned criteria.json, evolving during experiments, seeded by project builder, updated by advisor agent
- **Evaluation**: leaderboard ranking, 9 built-in metrics (R², RMSE, MAE, accuracy, F1, precision, recall, AUC, Cohen's d)
- **Knowledge pipeline**: PDF/text/URL extractors, KnowledgeStore with keyword search
- **Usage tracking**: per-session token/cost tracking, persisted per project
- **Persistent advisor memory**: rolling context summaries across sessions

### 24 Built-in Tools
| Tool | Category | Purpose |
|------|----------|---------|
| data_profiler | exploration | Dataset profiling with summary statistics |
| correlation_analysis | exploration | Correlation matrix and top correlations |
| outlier_detection | exploration | IQR and z-score outlier detection |
| visualization | exploration | Histogram, scatter, and box plots |
| cluster_analysis | exploration | KMeans + Agglomerative with auto-k selection |
| descriptive_stats | statistics | Summary stats with skew and kurtosis |
| hypothesis_tests | statistics | T-test, chi-squared, normality (Shapiro-Wilk) |
| paired_t_test | statistical_test | Paired t-test for related samples |
| one_way_anova | statistical_test | One-way ANOVA |
| mann_whitney_u | statistical_test | Mann-Whitney U non-parametric test |
| train_val_test_split | preprocessing | Train/val/test split with stratification |
| cross_validation | preprocessing | K-fold CV with optional stratification |
| group_split | preprocessing | LOGO CV and group-based splitting |
| feature_scaler | preprocessing | StandardScaler / MinMaxScaler |
| pca | dimensionality_reduction | PCA with variance threshold or fixed components |
| linear_regression | regression | OLS linear regression |
| polynomial_regression | regression | Polynomial + interaction terms |
| regularized_regression | regression | Lasso / Ridge / ElasticNet with CV alpha |
| linear_mixed_model | regression | Linear mixed models (random effects) |
| logistic_regression | classification | Logistic regression classifier |
| random_forest | regression | Random forest regression |
| random_forest_classifier | classification | Random forest classifier |
| gradient_boosting | regression | XGBoost gradient boosting |
| time_series_decomposition | time_series | Trend/seasonal/residual decomposition |

### Agent System (11 Roles + Orchestrator)
- **Project Builder**: interactive project setup (via `urika new`)
- **Planning Agent**: designs analytical method pipelines (read-only)
- **Task Agent**: implements methods as Python scripts using tools
- **Evaluator**: scores results against success criteria (read-only)
- **Advisor Agent**: proposes next experiments, persistent memory
- **Tool Builder**: creates new tools, can pip install packages
- **Literature Agent**: searches knowledge base for relevant papers/techniques
- **Data Agent**: local data extraction in hybrid privacy mode
- **Report Agent**: writes experiment narratives and project summaries
- **Presentation Agent**: creates reveal.js slide decks
- **Finalizer**: selects best methods, writes standalone reproduce scripts

### Orchestrator
- **Experiment loop**: planning → task → evaluator → advisor → (repeat)
- **Meta-orchestrator**: autonomous experiment-to-experiment sequencing
- **Finalize sequence**: finalizer → report → presentation → README
- **Conversational chat**: OrchestratorChat with subagent invocation
- **Graceful error handling**: rate limits pause (not fail), auth errors give actionable messages

### CLI (20+ Commands)
`new`, `list`, `status`, `experiment`, `results`, `methods`, `tools`, `run`, `report`, `inspect`, `logs`, `knowledge`, `advisor`, `evaluate`, `present`, `plan`, `finalize`, `build-tool`, `criteria`, `usage`, `dashboard`

### Textual TUI (Default Interface)
- Three-zone layout: OutputPanel + InputBar + StatusBar
- Background workers for agent commands with interactive stdin bridge
- ActivityBar with subagent tracking and randomized verb cycling
- Tab completion with contextual suggester
- /stop and Ctrl+C cancel active workers immediately
- Absolute path input works during interactive prompts

### Classic REPL (Fallback)
Available via `urika --classic`, prompt_toolkit based

### Dashboard
Browser-based read-only project viewer with curated tree, markdown/image rendering, light/dark mode

### Notifications
Pause/stop control + notification bus, Telegram/Slack integration

## Real-World Testing

Successfully tested on DHT target selection data: 35 experiments, 288 methods.
