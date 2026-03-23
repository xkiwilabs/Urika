# Creating Projects

This document covers everything about creating a new Urika project with `urika new`, including all options, the interactive setup flow, and what gets generated.

## The `urika new` command

```
urika new [NAME] [OPTIONS]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `NAME` | No | Project name. Prompted interactively if omitted. |

### Options

| Option | Description |
|--------|-------------|
| `--data PATH` | Path to a data file or directory. Can be a single CSV, a directory of CSVs, Excel files, Parquet, JSON, etc. |
| `-q, --question TEXT` | The research question for this project. |
| `-m, --mode MODE` | Investigation mode: `exploratory`, `confirmatory`, or `pipeline`. |
| `--description TEXT` | Free-text description of what you are trying to analyse or predict. |

### Examples

Fully non-interactive (all required fields supplied):

```bash
urika new sleep-study \
  --data /path/to/sleep_data.csv \
  --question "Does sleep duration predict reaction time?" \
  --mode exploratory \
  --description "Analysing sleep-reaction time relationship in shift workers"
```

Partially interactive (prompts for missing fields):

```bash
urika new sleep-study --data /path/to/sleep_data.csv
# Urika will prompt for: description, question, mode
```

Fully interactive:

```bash
urika new
# Urika will prompt for: name, data path, description, question, mode
```

## Interactive vs non-interactive creation

When you run `urika new`, any fields not supplied via command-line options are prompted interactively:

1. **Project name** -- a short identifier (used as the directory name)
2. **Data path** -- path to a file or directory containing your data (can be skipped by pressing Enter)
3. **Description** -- what you are trying to analyse or predict
4. **Research question** -- the specific question to investigate
5. **Investigation mode** -- select from a numbered list

If a project with the same name already exists, Urika offers three choices:
- Overwrite the existing project
- Choose a different name
- Abort

## Data scanning and profiling

When a data path is provided, Urika performs two automated steps:

### Source scanning

The source scanner recursively examines the provided path and classifies files by type:

- **Data files**: `.csv`, `.tsv`, `.parquet`, `.xlsx`, `.xls`, `.json`, `.jsonl`
- **Documentation**: `.md`, `.txt`, `.rst`, `.html`
- **Research papers**: `.pdf`
- **Code files**: `.py`, `.r`, `.jl`, `.ipynb`

The scanner reports what it found -- number of data files, documentation files, papers, and code files, along with their locations.

### Data profiling

For data files (CSVs are profiled first), Urika loads a sample (up to 5 files) and generates a profile:

- Number of rows and columns
- Column names and data types
- Missing value counts
- Basic summary statistics

This profile informs the project builder agent about your data structure.

## Investigation modes

The mode shapes how agents approach the research:

### Exploratory (default)

Open-ended analysis. The agents survey multiple approaches, establish baselines, and try diverse methods without a predetermined target metric. Initial criteria require trying at least 2 approaches and establishing baselines.

Best for: "I don't know what method will work best" or "I want to understand this dataset."

### Confirmatory

Hypothesis-driven with rigorous evaluation. Agents focus on testing specific hypotheses with statistical rigour, cross-validation, and careful metric selection.

Best for: "I have a specific hypothesis to test" or "I need robust statistical evidence."

### Pipeline

Goal is to build a production-ready analytical pipeline. Agents focus on model performance, reproducibility, and code quality.

Best for: "I need a working prediction pipeline" or "I want to deploy this model."

## The project builder agent flow

After collecting basic project information, the project builder agent runs an interactive question-and-answer session with three phases:

### Phase 1: Clarifying questions (Project Builder agent)

The project builder agent examines your data profile and project description, then asks up to 5 clarifying questions. Each question helps scope the project. Examples:

- "What is the target variable you want to predict?"
- "Are there known confounding variables to control for?"
- "Do you have a specific performance threshold in mind?"

Answer each question, or type `done` to skip ahead.

### Phase 2: Experiment suggestions (Advisor agent)

Based on your answers, the advisor agent proposes a set of initial experiments -- typically 3-5 approaches ordered by complexity (e.g., "start with baseline linear models, then try ensemble methods").

### Phase 3: Research plan (Planning agent)

The planning agent takes the suggested experiments and produces a structured research plan, outlining the sequence of experiments and the rationale.

### Refinement

After seeing the plan, you have three options:
- **Looks good** -- proceed to create the project
- **Refine** -- provide additional suggestions, and the agents will revise the plan
- **Abort** -- cancel project creation

The refinement loop continues until you are satisfied.

## Knowledge ingestion during setup

If the source scanner finds documentation files (`.md`, `.txt`, `.rst`, `.html`) or research papers (`.pdf`) alongside your data, Urika offers to ingest them into the project's knowledge base. This makes domain knowledge available to agents during experiments.

You will be prompted:

```
Ingest documentation and papers into the knowledge base? [Y/n]
```

## What gets created

After the interactive setup, Urika creates the following directory structure:

```
~/urika-projects/my-project/
  urika.toml              # Project configuration (name, question, mode, data paths)
  criteria.json            # Initial criteria (exploratory, v1)
  README.md                # Auto-generated project README
  data/                    # (data is referenced by path, not copied)
  tools/                   # Project-specific tools (created by tool builder at runtime)
  methods/                 # Agent-created analytical methods
  knowledge/               # Knowledge base
    papers/                # Ingested research papers
    notes/                 # Ingested notes and documentation
  experiments/             # Experiment directories (created when experiments run)
  projectbook/             # Project-level reports
    key-findings.md        # Key findings (updated as experiments complete)
    results-summary.md     # Cross-experiment results
    progress-overview.md   # Progress tracking
  suggestions/             # Initial experiment suggestions from the planning loop
    initial.json           # The proposed experiments
```

The project is registered in the global registry at `~/.urika/projects.json`, which maps project names to their paths.

## Running the first experiment

After project creation, if the planning loop produced experiment suggestions, Urika offers to run the first one immediately:

```
The plan proposes starting with: baseline-linear-models
  Fit OLS and regularised linear models to establish baseline performance...

Run the first experiment?
  1. Yes -- create and run it (default, press enter)
  2. Different -- I'll describe what to run instead
  3. Skip -- I'll run it later
```

Choosing option 1 creates the experiment and launches the orchestrator. Option 2 lets you describe a custom experiment. Option 3 exits, and you can run it later with `urika run`.
