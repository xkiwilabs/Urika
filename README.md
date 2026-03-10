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
# 1. Create a project
urika new sleep-study \
  --question "What predicts sleep quality?" \
  --mode exploratory

# 2. Add your data
cp my_data.csv ~/urika-projects/sleep-study/data/

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
| `urika new <name>` | Create a new project |
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
| `urika methods` | List available analysis methods |
| `urika tools` | List available analysis tools |
| `urika knowledge ingest <project> <source>` | Ingest a document |
| `urika knowledge search <project> <query>` | Search knowledge base |
| `urika knowledge list <project>` | List knowledge entries |

## Built-in Methods

| Name | Category | Description |
|------|----------|-------------|
| `descriptive_stats` | statistics | Descriptive statistics (mean, std, skew, kurtosis) using pandas and scipy |
| `linear_regression` | regression | Ordinary least-squares linear regression using scikit-learn |
| `logistic_regression` | classification | Logistic regression for classification using scikit-learn |
| `mann_whitney_u` | statistical_test | Mann-Whitney U test for comparing two independent samples |
| `one_way_anova` | statistical_test | One-way ANOVA for comparing means across groups |
| `paired_t_test` | statistical_test | Paired t-test for comparing two related samples |
| `random_forest` | regression | Random forest regression using scikit-learn |
| `xgboost_regression` | regression | Gradient boosting regression using scikit-learn |

## Built-in Tools

| Name | Category | Description |
|------|----------|-------------|
| `correlation_analysis` | exploration | Compute pairwise correlations and rank strongest relationships |
| `data_profiler` | exploration | Profile a dataset: counts, dtypes, missing data, and numeric statistics |
| `hypothesis_tests` | statistics | Run statistical hypothesis tests: t-test, chi-squared, and normality |
| `outlier_detection` | exploration | Detect outliers using IQR or z-score methods |
| `visualization` | exploration | Create histogram, scatter, and boxplot visualizations from data |

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

1. **Task Agent** explores data, writes Python code, runs methods
2. **Evaluator** scores results against success criteria (read-only)
3. **Suggestion Agent** analyzes results, proposes next experiments
4. **Tool Builder** creates new tools on demand
5. **Literature Agent** searches papers and builds knowledge base

The orchestrator loops through this cycle until success criteria are met or max turns reached.

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
