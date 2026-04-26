# CLI Reference

Complete reference for all Urika CLI commands. Run `urika --help` for a summary, or `urika <command> --help` for any individual command.

Running `urika` with no subcommand launches the interactive TUI (see [Interactive TUI](16-interactive-tui.md)). Use `urika --classic` for the classic prompt-toolkit REPL.


## Scriptable by Design

Every command is fully scriptable. When you provide arguments and flags, no interactive prompts are shown -- commands run non-interactively and exit. Add `--json` to any read command for structured output that can be piped to `jq`, parsed in Python, or fed into other tools.

```bash
# Non-interactive: all args on the command line
urika run my-study --max-turns 5 --instructions "try ensemble methods" --auto

# JSON output for custom tooling
urika status my-study --json | jq '.experiments'
urika results my-study --json | python3 process_results.py

# Batch script example
for project in study-a study-b study-c; do
  urika run "$project" --max-experiments 3 --auto
  urika finalize "$project"
done
```

This makes Urika suitable for automated pipelines, batch processing, CI/CD integration, and building custom research tools on top of the platform.


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
urika list [--prune]
```

```
  my-project    /home/user/urika-projects/my-project
  dht-analysis  /home/user/urika-projects/dht-analysis
```

Projects marked with `?` have a missing directory on disk.

**Options:**

| Option | Description |
|--------|-------------|
| `--prune` | Silently unregister any entries whose folder no longer exists, then print the cleaned list. Useful after manually deleting project directories outside Urika. |

---

### `urika delete`

Move a project to `~/.urika/trash/<name>-<YYYYMMDD-HHMMSS>/` and remove it from the registry. The folder is moved, not deleted, so artifacts are preserved. Empty the trash manually when you're sure (`rm -rf ~/.urika/trash/...`).

```
urika delete NAME [--force] [--json]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--force` / `-f` | Skip the confirmation prompt. |
| `--json` | Emit the trash result as JSON (`name`, `original_path`, `trash_path`, `registry_only`). |

**Behavior:**

- Refuses to trash if a `.lock` file exists anywhere under the project (active run / finalize / evaluate). Stop the run first.
- If the project's folder is already missing on disk, only the registry entry is removed (no second prompt) and the message reflects that.
- A manifest (`.urika-trash-manifest.json`) is written into the trash directory so you can identify it later.
- Each operation appends one JSON line to `~/.urika/deletion-log.jsonl`.

**Example:**

```
$ urika delete my-old-project
Move project 'my-old-project' to ~/.urika/trash/? (files preserved, registry entry removed) [y/N]: y
Moved 'my-old-project' to /home/user/.urika/trash/my-old-project-20260426-153012
```

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


### `urika update`

Update a project's description, research question, or mode. Changes are versioned -- previous values are preserved with timestamps in `revisions.json`.

```
urika update [PROJECT] [OPTIONS]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--field [description\|question\|mode]` | Field to update (prompted interactively if omitted) |
| `--value TEXT` | New value (prompted if omitted) |
| `--reason TEXT` | Why this change was made (prompted if omitted) |
| `--history` | Show revision history instead of updating |

When called with no `--field`, shows the current config and prompts you to choose which field to update, enter a new value, and optionally record a reason.

**Examples:**

```bash
# Interactive update (prompts for field, value, reason)
urika update my-study

# Direct update with all options
urika update my-study --field question --value "Does X predict Y?"

# Update with a reason
urika update my-study --field description --reason "Added new variables"

# View revision history
urika update my-study --history
```

**Example history output:**

```
  Revision history for my-study:

  #1  2026-03-20 14:32  [question]
    Old: Which factors predict target selection?
    New: Does X predict Y?
    Why: Refined after initial exploration
```

---

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
| `--max-experiments N` | Run multiple experiments (autonomous mode) |
| `--resume` | Resume a paused or failed experiment |
| `-q`, `--quiet` | Suppress verbose tool-use streaming output |
| `--auto` | Fully autonomous mode -- no confirmation prompts |
| `--instructions TEXT` | Guide the next experiment (e.g., "focus on tree-based models") |
| `--review-criteria` | Ask advisor to review criteria when met (may raise the bar) |
| `--audience [expert\|novice]` | Control explanation depth in reports and presentations (default: expert) |

**Interactive settings:** When called with no flags, shows a settings dialog:

```
Proceed?
  1. Run with defaults
  2. Run multiple experiments (autonomous)
  3. Custom max turns
  4. Skip
```

This dialog is skipped when any flag is provided or when called from the TUI.

**Experiment selection logic** (when `--experiment` is not provided):
1. If there are pending (non-completed) experiments, resumes the most recent one
2. If all experiments are completed, calls the advisor agent to propose and create the next experiment
3. If no experiments exist and no initial plan is found, raises an error

**Examples:**

```bash
# Run with defaults (shows settings dialog)
urika run my-project

# Run multiple experiments
urika run my-project --max-experiments 5

# Run specific experiment with more turns
urika run my-project --experiment exp-002 --max-turns 10

# Fully autonomous with guidance
urika run my-project --auto --instructions "try ensemble methods"

# Resume after interruption
urika run my-project --resume
```

The `max_turns` default can be set in `urika.toml`:

```toml
[preferences]
max_turns_per_experiment = 10
```


## Viewing

### `urika dashboard [PROJECT] [--port PORT]`

Open a browser-based read-only dashboard for a project. Displays experiments, reports, figures, methods, and criteria in an interactive web interface.

- **`--port PORT`** — Server port (default: 8420)

The dashboard shows:
- **Sidebar** — Curated project tree: experiments (with labbook, artifacts, presentations), projectbook, methods, criteria
- **Content area** — Rendered markdown, syntax-highlighted JSON/Python, zoomable images
- **Footer** — Project stats at a glance

Click any figure to zoom. Presentations open in a new tab. Light/dark mode toggle in the header.

The server runs on localhost only and stops when you exit.

---

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
| `--audience [expert\|novice]` | Control explanation depth (default: expert) |

When no experiment is specified, you are prompted to choose: a specific experiment, all experiments, or project-level reports.

See [Viewing Results](07-viewing-results.md) for details on report types.

---

### `urika present`

Generate a reveal.js presentation from experiment results.

```
urika present [PROJECT]
```

Prompts you to choose: a specific experiment, all experiments, or a project-level presentation.

**Options:**

| Option | Description |
|--------|-------------|
| `--audience [expert\|novice]` | Control explanation depth (default: expert) |

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

After the advisor responds with experiment suggestions, you are offered the option to run them immediately. See [Advisor Chat and Instructions](06-advisor-and-instructions.md) for the full guide on advisor conversations, the suggestion-to-run flow, and how to steer agents with instructions.

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


### `urika finalize`

Run the finalization sequence on a project: Finalizer Agent (selects best methods, writes standalone scripts, findings, and reproducibility artifacts), Report Agent (final report), Presentation Agent (final presentation), and README update.

```
urika finalize [PROJECT] [OPTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |

**Options:**

| Option | Description |
|--------|-------------|
| `--instructions TEXT` | Optional instructions for the finalizer agent (e.g., "focus on the random forest method") |
| `--audience [expert\|novice]` | Control explanation depth in reports and presentations (default: expert) |
| `--draft` | Interim summary -- outputs to `projectbook/draft/`, does not overwrite final outputs or write standalone scripts |

**Examples:**

```bash
urika finalize my-project
urika finalize my-project --instructions "emphasize the ensemble methods"
urika finalize my-project --draft
urika finalize my-project --draft --audience novice
```

See [Finalizing Projects](08-finalizing-projects.md) for details on what is produced, including draft mode.

---

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


### `urika config`

Configure privacy mode, models, and endpoints. Works globally or per-project.

```
urika config [PROJECT] [--show] [--json]
```

**Without PROJECT:** Configures global defaults in `~/.urika/settings.toml` (used for new projects).

**With PROJECT:** Configures that project's `urika.toml`.

**Interactive setup** guides you through:

- **Privacy mode** — open, private, or hybrid
- **Open:** Choose a cloud model (Sonnet, Opus, Haiku) for all agents
- **Private:** Configure endpoint (Ollama, LM Studio, or custom server) and model for all agents
- **Hybrid:** Choose cloud model for most agents + private endpoint and model for the data agent

**Warnings:** Switching from private/hybrid to a less private mode triggers a confirmation prompt.

**Privacy mode rules:**

| Mode | data_agent | Other agents |
|------|-----------|-------------|
| **open** | Cloud only | Cloud only (different models allowed per agent) |
| **private** | Private only | Private only (different endpoints/models allowed) |
| **hybrid** | Must be private | Cloud or private (user's choice per agent) |

**Examples:**

```bash
urika config                     # interactive global setup
urika config --show              # show global defaults
urika config my-project          # reconfigure a project
urika config my-project --show   # show project settings
```

For per-agent model overrides beyond what the interactive setup provides, edit `urika.toml` directly — see [Configuration](13-configuration.md).


## System

### `urika setup`

Check installation status and optionally install missing packages. Useful after first install or when upgrading.

```
urika setup
```

**What it does:**

1. **Package check** -- Shows installed vs missing packages for each category: core, visualization, ML, deep learning, and knowledge pipeline.
2. **Hardware detection** -- Reports CPU cores, available RAM, and GPU presence (NVIDIA via `nvidia-smi`).
3. **Deep learning install** -- If DL packages are missing, offers to install them. Detects whether you have an NVIDIA GPU and chooses the appropriate CPU or CUDA variant automatically.
4. **API key check** -- Verifies that `ANTHROPIC_API_KEY` is set in the environment.

**Example output:**

```
Core packages:        all installed
Visualization:        all installed
Machine learning:     all installed
Knowledge pipeline:   all installed
Deep learning:        not installed

Hardware:
  CPU: 8 cores
  RAM: 32 GB
  GPU: NVIDIA RTX 4090 (24 GB VRAM)

ANTHROPIC_API_KEY: set

Install deep learning packages? [Y/n]
  Detected NVIDIA GPU -- installing CUDA variant...
```

---

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
  correlation_analysis  [exploration]       Compute correlation matrices
  cross_validation      [preprocessing]     K-fold cross-validation
  linear_regression     [regression]        Fit linear regression models
  visualization         [exploration]       Generate plots and figures
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
| `NO_COLOR` | Set to disable colored terminal output (colors are on by default for TTYs) |


## Global Behaviors

- **Project argument**: Most commands accept an optional `PROJECT` argument. If omitted and only one project exists, it is used automatically. If multiple projects exist, you are prompted to select one.
- **Versioned files**: Reports, presentations, and other generated files use versioned writing -- previous versions are backed up with timestamps before overwriting.
- **Ctrl+C handling**: During `urika run`, pressing Ctrl+C cleanly pauses the experiment and removes the lock file. Resume with `urika run --resume`.

---

**Next:** [Interactive TUI](16-interactive-tui.md)
