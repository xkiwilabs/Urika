# Urika

Agentic scientific analysis platform for behavioral and health sciences.

Urika uses multiple AI agents (powered by Claude) to autonomously explore analytical approaches for your dataset and research question. It creates experiments, tries different methods, evaluates results, and documents everything in a structured labbook.

## Installation

```bash
pip install -e .

# With agent support (requires Claude API key):
pip install -e ".[agents]"

# With PDF knowledge ingestion:
pip install -e ".[knowledge]"

# Development:
pip install -e ".[dev]"
```

## Quickstart

```bash
# 1. Create a project (with data source)
urika new sleep-study \
  --question "What predicts sleep quality?" \
  --mode exploratory \
  --data ./my_data.csv

# The builder scans data sources, profiles datasets, and can
# ingest papers/docs into the knowledge base automatically.

# 3. Inspect the data
urika inspect sleep-study

# 4. Create an experiment
urika experiment create sleep-study "baseline models" \
  --hypothesis "Linear models establish a baseline"

# 5. Run the experiment (requires Claude API key)
urika run sleep-study --max-turns 20

# 6. View results
urika results sleep-study
urika report sleep-study

# 7. Resume if needed
urika run sleep-study --continue
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `urika new <name> -q <question> -m <mode> --data <path> --description <desc>` | Create a new project (scans data sources, profiles data, ingests docs into knowledge base) |
| `urika list` | List all projects |
| `urika status <project>` | Show project status |
| `urika inspect <project>` | Inspect project data |
| `urika experiment create <project> <name>` | Create an experiment |
| `urika experiment list <project>` | List experiments |
| `urika run <project>` | Run an experiment |
| `urika run <project> --continue` | Resume a paused experiment |
| `urika results <project>` | Show results and leaderboard |
| `urika report <project>` | Generate labbook reports |
| `urika logs <project>` | Show experiment run log |
| `urika methods <project>` | List agent-created methods in a project |
| `urika tools` | List available analysis tools |
| `urika knowledge ingest <project> <source>` | Ingest a document |
| `urika knowledge search <project> <query>` | Search knowledge base |
| `urika knowledge list <project>` | List knowledge entries |
| `urika advisor <project> <text>` | Ask the advisor agent a question |
| `urika evaluate <project> [experiment]` | Run evaluator on an experiment |
| `urika present <project>` | Generate a presentation |
| `urika criteria <project>` | Show current project criteria |
| `urika usage [project]` | Show usage stats |

## Built-in Tools

| Tool | Category | Description |
|------|----------|-------------|
| `correlation_analysis` | exploration | Correlation matrix and top correlations |
| `cross_validation` | evaluation | Cross-validation scoring |
| `data_profiler` | exploration | Dataset profiling with summary statistics |
| `descriptive_stats` | statistics | Descriptive statistics with skew and kurtosis |
| `group_split` | preprocessing | Group-aware train/test splitting |
| `hypothesis_tests` | statistics | T-test, chi-squared, and normality tests |
| `linear_regression` | regression | OLS linear regression |
| `logistic_regression` | classification | Logistic regression classifier |
| `mann_whitney_u` | statistical_test | Mann-Whitney U non-parametric test |
| `one_way_anova` | statistical_test | One-way ANOVA test |
| `outlier_detection` | exploration | IQR and z-score outlier detection |
| `paired_t_test` | statistical_test | Paired t-test for related samples |
| `random_forest` | regression | Random forest regression |
| `train_val_test_split` | preprocessing | Train/validation/test splitting |
| `visualization` | exploration | Histogram, scatter, and box plots |
| `xgboost_regression` | regression | Gradient boosting regression |

## Methods

Methods are agent-created analytical pipelines, not shipped as built-ins. During an experiment, agents combine tools into complete analysis workflows and register them as methods. Use `urika methods <project>` to see what methods agents have created for a project.

## Project Structure

`urika new` creates the following layout:

```
my-project/
├── urika.toml           # Project config
├── data/                 # Your dataset(s)
├── experiments/          # Experiment directories
│   └── exp-001-name/
│       ├── experiment.json
│       ├── progress.json
│       ├── session.json
│       ├── methods/
│       ├── labbook/
│       └── artifacts/
├── knowledge/            # Ingested papers/notes
├── methods/              # Project-specific methods
├── tools/                # Project-specific tools
├── labbook/              # Project-level reports
└── leaderboard.json      # Method rankings
```

## How It Works

Urika runs an autonomous agent loop for each experiment:

1. **Planning Agent** reviews context and decides the next analytical step
2. **Task Agent** explores data, writes Python code, runs tools
3. **Evaluator** scores results against success criteria (read-only)
4. **Advisor Agent** analyzes results, proposes next experiments
5. **Tool Builder** creates new tools on demand
6. **Literature Agent** searches papers and builds knowledge base

The orchestrator loops through `planning -> task -> evaluator -> suggestion` until success criteria are met or max turns reached.

## Development

```bash
pip install -e ".[dev]"
pytest -v              # Run tests
ruff check src/ tests/ # Lint
ruff format src/ tests/ # Format
```

## Requirements

- Python >= 3.11
- Claude API key (for agent execution)

## License

MIT
