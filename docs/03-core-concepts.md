# Core Concepts

This document explains the key abstractions in Urika: how projects, experiments, and runs relate to each other; what agents, tools, and methods are; and how the orchestrator drives the research loop.

## The hierarchy: Project, Experiment, Run

Urika organizes work into three levels:

### Project

A project pairs **one dataset** with **one research question**. It is the top-level container. Creating a project (`urika new`) produces a directory with configuration (`urika.toml`), data, knowledge, methods, experiments, and a projectbook.

The dataset can be in any format — tabular (CSV, Excel, Parquet, SPSS, Stata), images, audio, time series (HDF5, EDF, MAT), spatial/3D (PLY, PCD, C3D), or domain-specific formats. Urika detects and profiles the data automatically, and agents install whatever libraries they need to work with it.

A project has an **investigation mode** that shapes how agents approach the work:

- **exploratory** -- open-ended analysis, establishing baselines, surveying what works
- **confirmatory** -- testing specific hypotheses with rigorous evaluation
- **pipeline** -- building a production-ready analytical pipeline

### Experiment

An experiment is a distinct analytical campaign within a project. Each experiment has a name, a hypothesis, and its own directory under `experiments/`. Experiments are numbered sequentially (`exp-001-baseline-models`, `exp-002-feature-engineering`, etc.).

A single project typically contains multiple experiments, each building on findings from the previous ones. The advisor agent proposes new experiments based on what has been learned.

### Run

A run is a single method execution with specific parameters inside an experiment. Each run records:

- **method** -- the name of the analytical approach used
- **params** -- the parameters/configuration for this execution
- **metrics** -- numerical results (accuracy, RMSE, R-squared, etc.)
- **hypothesis** -- what the run was testing
- **observation** -- what was learned
- **next_step** -- what should be tried next
- **artifacts** -- paths to generated files (plots, models, etc.)

Runs are recorded in `progress.json` and are append-only.

## Methods

A method is an agent-created analytical pipeline. Urika ships with **zero built-in methods**. Instead, the task agent writes Python code at runtime to implement each analytical approach. Methods are registered in `methods.json` with their name, description, associated experiment, metrics, and status.

This means every method is tailored to your specific dataset and research question. The planning agent designs the approach, the task agent implements it, and the evaluator scores it.

## Tools

Tools are reusable analysis building blocks that agents call when constructing methods. **The tool catalogue is open-ended** — Urika does not assume the shipped library covers your project. The system is designed around two complementary mechanisms:

1. **A starting library of 24 built-in tools** — common-case primitives for tabular data analysis (regression, classification, statistical tests, exploration, preprocessing). These exist so common projects can start producing results without a separate tool-building round.
2. **Agent-created project tools** — whenever an agent needs a capability the built-in library doesn't cover, the **tool builder** agent writes a new Python tool, registers it in the project's `tools/` directory, and from that point on it's available alongside the built-ins for the rest of the project.

This is a core part of how Urika works. **Don't think of the 24 built-ins as the full set of capabilities.** Think of them as the seed library; the tool builder grows it as the project demands. A project working with EEG epochs, image patches, time-warped trajectories, or any domain-specific feature extraction will end up with project-specific tools that the agent created on demand.

There are two ways tool building gets triggered:

- **Automatic.** The planning agent identifies a need that built-in tools don't cover (e.g. "ICC reliability analysis", "compute spectral power per channel"), flags `needs_tool: true`, and the tool builder is invoked before the next experiment.
- **Explicit, via `urika build-tool`.** When you know up front what tool you'll need, ask for it directly: `urika build-tool create an ICC tool using pingouin` or `urika build-tool install mne and add an EEG epoch extractor`. This is also exposed as `/build-tool` in the TUI and the **Build tool** modal in the dashboard.

Project-specific tools live alongside the built-ins in the registry — agents see one unified tool list when picking what to use.

The 24 built-in tools, grouped by category:

| Tool | Category | Description |
|------|----------|-------------|
| `cluster_analysis` | exploration | KMeans / DBSCAN / HDBSCAN clustering |
| `correlation_analysis` | exploration | Correlation matrices and pairwise analysis |
| `cross_validation` | preprocessing | K-fold cross-validation |
| `data_profiler` | exploration | Dataset profiling and summary statistics |
| `descriptive_stats` | statistics | Descriptive statistics (mean, median, std, etc.) |
| `feature_scaler` | preprocessing | Scale numeric features (standard, minmax, robust) |
| `gradient_boosting` | regression | Gradient boosting regression |
| `group_split` | preprocessing | Split data by group membership |
| `hypothesis_tests` | statistical_test | Statistical hypothesis testing |
| `linear_mixed_model` | regression | Mixed-effects regression via statsmodels |
| `linear_regression` | regression | Linear regression fitting and diagnostics |
| `logistic_regression` | classification | Logistic regression for classification |
| `mann_whitney_u` | statistical_test | Mann-Whitney U non-parametric test |
| `one_way_anova` | statistical_test | One-way ANOVA |
| `outlier_detection` | exploration | Detect and flag outliers |
| `paired_t_test` | statistical_test | Paired t-test |
| `pca` | dimensionality_reduction | Principal Component Analysis |
| `polynomial_regression` | regression | Polynomial features + linear regression |
| `random_forest` | regression | Random forest regression |
| `random_forest_classifier` | classification | Random forest classification |
| `regularized_regression` | regression | Ridge / Lasso / ElasticNet regression |
| `time_series_decomposition` | time_series | STL / additive / multiplicative decomposition |
| `train_val_test_split` | preprocessing | Train/validation/test data splitting |
| `visualization` | exploration | Chart and plot generation |

The **tool builder** agent can also create project-specific tools at runtime when the planning agent identifies a capability gap (see above). See [Built-in Tools](12-built-in-tools.md) for a full catalogue and the project-tool building workflow.

List available tools with:

```bash
urika tools
urika tools --category statistics
urika tools --project my-study    # includes project-specific tools created by the tool builder
```

## Agents

Urika uses twelve specialized agent roles, each with a distinct responsibility. All agents run on the Claude Agent SDK.

### Project Builder

Scopes new projects interactively. Asks clarifying questions about your data and research goals, then proposes initial experiments and writes the project configuration. Used during `urika new`.

### Planning Agent

Reviews the current project state -- previous results, methods tried, criteria -- and designs the next analytical approach. Outputs a method plan that the task agent implements. Can request that the tool builder create new tools or that the literature agent search for relevant papers.

### Task Agent

The workhorse. Receives a method plan, writes Python code, executes experiments, and records observations. Produces run records with metrics, hypotheses, and artifacts.

### Evaluator

Read-only scoring agent. Validates results against the project's success criteria. Determines whether criteria have been met (triggering experiment completion) or whether more work is needed.

### Advisor Agent

Analyzes results across runs and experiments. Proposes what to try next, suggests new experiments, and can update the project's success criteria as understanding deepens.

### Tool Builder

Creates project-specific tools when the planning agent identifies a gap in available capabilities. Tools are saved to the project's `tools/` directory.

### Literature Agent

Searches the project's knowledge base (ingested papers, documentation, notes) and summarizes relevant findings for the planning and task agents.

### Report Agent

Writes narrative reports and summaries. Generates experiment-level narratives and project-level overviews for the projectbook.

### Presentation Agent

Creates reveal.js slide decks from experiment results. Generates HTML presentations that can be opened in a browser.

### Data Agent

The only agent that reads raw data in hybrid privacy mode. Runs on a private endpoint and outputs sanitized summaries -- aggregated statistics, feature names, distributions, and processed DataFrames -- so other agents never see raw data.

### Finalizer

Consolidates all research into polished, standalone deliverables. Selects the best methods, writes each as a standalone Python script, and produces a structured findings summary, methods README, `requirements.txt`, and cross-platform reproduce scripts.

### Project Summarizer

Read-only agent that produces a comprehensive project status summary by reading project files, the projectbook, and experiment records. Exposed via the `urika summarize` command.

## The orchestrator loop

Within a single experiment, the orchestrator cycles through four agents per turn:

```
  Planning Agent     designs the next method
       |
       v
    Task Agent       implements and runs it
       |
       v
    Evaluator        scores the results
       |
       v
  Advisor Agent      proposes what to try next
       |
       v
  (next turn or experiment complete)
```

Each cycle is called a **turn**. Experiments run for a configurable number of turns (default: 5, set via `max_turns` in `urika.toml` or `--max-turns` on the command line).

Within a turn:

1. The **planning agent** reads the current state and outputs a method plan. If the plan requires a new tool or literature search, those agents run first.
2. The **task agent** receives the plan, writes code, runs it, and produces run records.
3. The **evaluator** scores the results against the project criteria. If criteria are met, the experiment completes immediately (unless `--review-criteria` is set, in which case the advisor reviews whether the bar should be raised).
4. The **advisor agent** analyzes what happened and produces suggestions for the next turn. It can also update the project criteria.

When criteria are met or max turns are reached, the orchestrator generates reports (labbook notes, narrative, README, presentation) and marks the experiment as completed.

## Autonomous mode (multiple experiments)

Autonomous mode manages **experiment-to-experiment** flow. After one experiment completes, the advisor agent proposes the next experiment based on what has been learned across all prior experiments.

Autonomous mode supports three modes:

- **checkpoint** (default) -- pauses between experiments for user confirmation
- **capped** -- runs up to a specified number of experiments without pausing
- **unlimited** -- runs until the advisor says no more experiments are needed (hard cap: 50)

## Criteria system

Criteria define what "success" means for a project. They evolve over time:

- At project creation, the project builder sets initial **exploratory** criteria (e.g., "establish baselines, try at least 2 approaches").
- As experiments progress, the advisor agent can **update** criteria -- for example, shifting from exploratory to confirmatory with specific metric thresholds.
- Criteria are versioned. Each version records who set it, at which turn, and the rationale.

The evaluator checks criteria after each run. When criteria are met, the experiment is marked complete.

View current criteria with:

```bash
urika criteria my-study
```

## Projectbook

The projectbook is Urika's auto-generated documentation system. It lives in the `projectbook/` directory at the project root and in `labbook/` directories within each experiment. Contents include:

- **notes.md** -- auto-generated from run records (per experiment)
- **summary.md** -- experiment summary with key metrics (per experiment)
- **narrative.md** -- agent-written narrative report (per experiment and project level)
- **results-summary.md** -- cross-experiment results comparison (project level)
- **key-findings.md** -- distilled findings (project level)
- **progress-overview.md** -- project-wide progress tracking
- **README.md** -- auto-generated project README with agent-written status summary
- **presentation/** -- reveal.js slide decks (per experiment and project level)

Generate or update reports with:

```bash
urika report my-study
urika present my-study
```

## Knowledge base

Each project has a knowledge base (`knowledge/` directory) that can hold ingested papers, documentation, and notes. The literature agent searches this during experiments to inform method design.

Ingest files:

```bash
urika knowledge ingest my-study /path/to/paper.pdf
urika knowledge ingest my-study /path/to/notes.txt
```

Search the knowledge base:

```bash
urika knowledge search my-study "regression diagnostics"
```

Supported formats: PDF, plain text, Markdown, HTML.

---

**Next:** [Creating Projects](04-creating-projects.md)
