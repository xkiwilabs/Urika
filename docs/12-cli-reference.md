# CLI Reference

Complete reference for all Urika CLI commands. Run `urika --help` for a summary, or `urika <command> --help` for any individual command.

Running `urika` with no subcommand launches the interactive REPL (see [Interactive REPL](13-interactive-repl.md)).


## Project Management

### `urika new`

Create a new project. Launches an interactive flow: scan data, profile columns, ask clarifying questions via the project builder agent, generate initial experiment suggestions via the advisor agent, and write the project structure.

```
urika new [NAME] [OPTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `NAME` | Project name (prompted if omitted) |

**Options:**

| Option | Description |
|--------|-------------|
| `-q`, `--question TEXT` | Research question |
| `-m`, `--mode [exploratory\|confirmatory\|pipeline]` | Investigation mode |
| `--data PATH` | Path to data file or directory |
| `--description TEXT` | Project description |

All options are prompted interactively if not provided on the command line.

**Example:**

```bash
urika new dht-targeting \
  --data ~/data/dht_scores.csv \
  --question "Which factors predict DHT target selection?" \
  --mode exploratory
```

After project creation, Urika offers to run the first suggested experiment immediately.

---

### `urika list`

List all registered projects.

```
urika list
```

```
  my-project    /home/user/urika-projects/my-project
  dht-analysis  /home/user/urika-projects/dht-analysis
```

Projects marked with `?` have a missing directory on disk.

---

### `urika status`

Show project status including research question, mode, experiment count, and per-experiment status.

```
urika status [NAME]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `NAME` | Project name (prompted if multiple projects exist) |

**Example output:**

```
Project: dht-targeting
Question: Which factors predict DHT target selection?
Mode: exploratory
Path: /home/user/urika-projects/dht-targeting
Experiments: 3

  exp-001: baseline-models [completed, 5 runs]
  exp-002: feature-engineering [completed, 4 runs]
  exp-003: ensemble-methods [running, 2 runs]
```

---

### `urika inspect`

Inspect project data: column schema, data types, missing values, and a preview of the first 5 rows.

```
urika inspect [PROJECT] [--data FILE]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--data FILE` | Specific data file to inspect (defaults to first CSV in `data/`) |

**Example output:**

```
Dataset: scores.csv
Rows: 1247
Columns: 18

Schema:
  target_id                      int64
  fov_distance                   float64
  brightness                     float64         (2.1% missing)
  ...

Preview (first 5 rows):
 target_id  fov_distance  brightness  ...
```


## Experiments

### `urika experiment create`

Create a new experiment within a project.

```
urika experiment create [PROJECT] NAME [--hypothesis TEXT]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `NAME` | Experiment name (required) |

**Options:**

| Option | Description |
|--------|-------------|
| `--hypothesis TEXT` | Experiment hypothesis |

**Example:**

```bash
urika experiment create dht-targeting baseline-models \
  --hypothesis "Linear models provide a reasonable baseline"
```

Returns the generated experiment ID (e.g., `exp-001`).

---

### `urika experiment list`

List all experiments in a project with their status and run count.

```
urika experiment list [PROJECT]
```

**Example output:**

```
  exp-001  baseline-models  [completed, 5 runs]
  exp-002  feature-engineering  [completed, 4 runs]
```

---

### `urika run`

Run an experiment using the orchestrator. This is the main command that drives the agent loop: planning, task execution, evaluation, and advisor suggestions.

```
urika run [PROJECT] [OPTIONS]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--experiment ID` | Specific experiment ID to run (auto-selected if omitted) |
| `--max-turns N` | Maximum orchestrator turns (default: from `urika.toml`, or 5) |
| `--continue` | Resume a paused or failed experiment |
| `-q`, `--quiet` | Suppress verbose tool-use streaming output |
| `--auto` | Fully autonomous mode -- no confirmation prompts |
| `--instructions TEXT` | Guide the next experiment (e.g., "focus on tree-based models") |

**Experiment selection logic** (when `--experiment` is not provided):
1. If there are pending (non-completed) experiments, resumes the most recent one
2. If all experiments are completed, calls the advisor agent to propose and create the next experiment
3. If no experiments exist and no initial plan is found, raises an error

**Examples:**

```bash
# Run with defaults (auto-selects experiment)
urika run my-project

# Run specific experiment with more turns
urika run my-project --experiment exp-002 --max-turns 10

# Fully autonomous with guidance
urika run my-project --auto --instructions "try ensemble methods"

# Resume after interruption
urika run my-project --continue
```

The `max_turns` default can be set in `urika.toml`:

```toml
[preferences]
max_turns_per_experiment = 10
```


## Results and Reports

### `urika results`

Show project results -- either the project leaderboard or runs for a specific experiment.

```
urika results [PROJECT] [--experiment ID]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--experiment ID` | Show runs for a specific experiment instead of the leaderboard |

---

### `urika methods`

List all agent-created methods in a project with their status and top metrics.

```
urika methods [PROJECT]
```

---

### `urika logs`

Show detailed experiment run logs with hypotheses, observations, and next steps.

```
urika logs [PROJECT] [--experiment ID]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--experiment ID` | Specific experiment (prompted if multiple exist) |

---

### `urika report`

Generate labbook reports. Produces notes, summaries, and agent-written narratives.

```
urika report [PROJECT] [--experiment ID]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--experiment ID` | Generate report for a specific experiment |

When no experiment is specified, you are prompted to choose: a specific experiment, all experiments, or project-level reports.

See [Viewing Results](05-viewing-results.md) for details on report types.

---

### `urika present`

Generate a reveal.js presentation from experiment results.

```
urika present [PROJECT]
```

Prompts you to choose: a specific experiment, all experiments, or a project-level presentation.

---

### `urika criteria`

Show current project success criteria, including version, type, and primary threshold.

```
urika criteria [PROJECT]
```

---

### `urika usage`

Show usage statistics: sessions, tokens, estimated costs, and agent calls.

```
urika usage [PROJECT]
```

Without a project argument, shows totals across all registered projects.


## Agents

### `urika advisor`

Ask the advisor agent a question about the project. Provides project context (methods tried, current state) alongside your question.

```
urika advisor [PROJECT] [TEXT]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `TEXT` | Question or instructions (prompted if omitted) |

**Example:**

```bash
urika advisor my-project "What methods should I try next?"
```

---

### `urika evaluate`

Run the evaluator agent on an experiment to score results against success criteria.

```
urika evaluate [PROJECT] [EXPERIMENT_ID]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `EXPERIMENT_ID` | Experiment to evaluate (defaults to most recent) |

---

### `urika plan`

Run the planning agent to design the next analytical method for an experiment.

```
urika plan [PROJECT] [EXPERIMENT_ID]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `EXPERIMENT_ID` | Experiment to plan for (defaults to most recent) |


### `urika build-tool`

Build a custom tool for the project. The tool builder agent creates a Python module in the project's `tools/` directory based on your instructions.

```
urika build-tool [PROJECT] [INSTRUCTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `INSTRUCTIONS` | What tool to build (prompted if omitted) |

**Examples:**

```bash
urika build-tool my-project "create an EEG epoch extractor using MNE"
urika build-tool my-project "build a tool that computes ICC using pingouin"
urika build-tool my-project "install librosa and create an audio feature extractor"
```

---

## Knowledge

### `urika knowledge ingest`

Ingest a file or URL into the project's knowledge store. Supports PDF, text, and URL sources.

```
urika knowledge ingest [PROJECT] SOURCE
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `SOURCE` | Path to file or URL to ingest |

**Example:**

```bash
urika knowledge ingest my-project ~/papers/target-selection-review.pdf
```

---

### `urika knowledge search`

Search the knowledge store by keyword query.

```
urika knowledge search [PROJECT] QUERY
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `QUERY` | Search query string |

---

### `urika knowledge list`

List all entries in the project's knowledge store.

```
urika knowledge list [PROJECT]
```


## Environment

### `urika venv create`

Create an isolated virtual environment for a project. The venv inherits shared base packages (numpy, pandas, scipy, etc.) via `--system-site-packages` so only project-specific packages are installed into it.

```
urika venv create [PROJECT]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |

**Example:**

```bash
urika venv create my-project
```

Creates `.venv/` inside the project directory. Agents will install packages into this venv instead of the global environment.

---

### `urika venv status`

Show the virtual environment status for a project: whether a venv exists, its path, and installed packages.

```
urika venv status [PROJECT]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |

**Example output:**

```
Project: my-project
Venv: /home/user/urika-projects/my-project/.venv
Status: active
Packages: 47 installed (12 project-specific)
```


## System

### `urika tools`

List all available analysis tools (built-in and project-specific).

```
urika tools [--category CATEGORY] [--project NAME]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--category TEXT` | Filter tools by category |
| `--project NAME` | Include project-specific tools |

**Example output:**

```
  correlation_analysis  [statistics]   Compute correlation matrices
  cross_validation      [validation]   K-fold cross-validation
  linear_regression     [modelling]    Fit linear regression models
  visualization         [plotting]     Generate plots and figures
  ...
```

### `urika --version`

Show the installed Urika version.

```
urika --version
```


## Environment Variables

| Variable | Description |
|----------|-------------|
| `URIKA_PROJECTS_DIR` | Override the default projects directory (default: `~/urika-projects`) |
| `URIKA_COLOR` | Set to `1` to enable colored terminal output (disabled by default) |


## Global Behaviors

- **Project argument**: Most commands accept an optional `PROJECT` argument. If omitted and only one project exists, it is used automatically. If multiple projects exist, you are prompted to select one.
- **Versioned files**: Reports, presentations, and other generated files use versioned writing -- previous versions are backed up with timestamps before overwriting.
- **Ctrl+C handling**: During `urika run`, pressing Ctrl+C cleanly pauses the experiment and removes the lock file. Resume with `urika run --continue`.
