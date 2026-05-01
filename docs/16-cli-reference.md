# CLI Reference

Complete reference for all Urika CLI commands. Run `urika --help` for a summary, or `urika <command> --help` for any individual command.

Running `urika` with no subcommand launches the interactive TUI (see [Interactive TUI](17-interactive-tui.md)). Use `urika --classic` for the classic prompt-toolkit REPL.


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

Show project status including research question, mode, experiment count, per-experiment status, and **data drift** — a SHA-256 hash of every registered data file is captured at `urika new` time and re-checked here. Files whose hash has changed are flagged so you don't accidentally compare runs against drifted data.

```
urika status [NAME] [--json]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `NAME` | Project name (prompted if multiple projects exist) |

**Options:**

| Option | Description |
|--------|-------------|
| `--json` | Emit a JSON envelope with `experiments`, `data_drift`, and `path` fields for scripted callers. Used by the dashboard's project-home page. |

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

Data drift:
  ⚠ data/training.csv  hash changed since 2026-04-12 (registered: a3f1…  current: c40b…)
```

The original hashes live in `urika.toml` under `[project.data_hashes]` and are re-computed on every `urika status` and `urika new`. To silence a drift warning after intentionally updating a dataset, run `urika update <project>` and accept the new hashes.

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

### `urika experiment delete`

Move a single experiment to the project's local trash at `<project>/trash/`. The experiment directory is moved (not deleted) so artifacts are preserved. A manifest entry is written to `<project>/trash/.urika-trash-manifest.json` so you can identify it later.

This mirrors `urika delete` (which trashes a whole project to `~/.urika/trash/`) but operates on one experiment within a project.

```
urika experiment delete [PROJECT] EXP_ID [OPTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (defaults to the most recent project if omitted) |
| `EXP_ID` | Experiment ID to trash (e.g., `exp-003`) — required |

**Options:**

| Option | Description |
|--------|-------------|
| `-f`, `--force` | Skip the confirmation prompt. |
| `--json` | Emit the trash result as JSON (`project_name`, `experiment_id`, `original_path`, `trash_path`). |

**Behavior:**

- Refuses to trash an active experiment (one with a `.lock` file) — stop the run first.
- Empty the project's `trash/` folder manually when you're sure (e.g., `rm -rf <project>/trash/<exp_id>-*`).

**Examples:**

```bash
urika experiment delete my-study exp-003
urika experiment delete my-study exp-003 --force
urika experiment delete my-study exp-003 --json
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
| `--max-turns N` | Maximum orchestrator turns (default: from `urika.toml`, or 10) |
| `--max-experiments N` | Run multiple experiments (autonomous mode — meta-orchestrator) |
| `--resume` | Resume a paused or failed experiment |
| `-q`, `--quiet` | Suppress verbose tool-use streaming output |
| `--auto` | Fully autonomous mode — no confirmation prompts |
| `--dry-run` | Print the planned pipeline (agents, tools, writable directories) without invoking any agent. Includes a cost estimate row using prior session costs as a basis. |
| `--instructions TEXT` | Guide the next experiment (e.g., "focus on tree-based models") |
| `--review-criteria` | Re-run the criteria-review subroutine so the advisor can evolve project criteria based on accumulated experiment results (may raise the bar). |
| `--budget FLOAT` | Pause the run when accumulated cost crosses this USD amount. Pause is at the next turn boundary; resumable via `--resume`. Default: no cap. |
| `--advisor-first` | Run the advisor first to propose a name + hypothesis + direction, then proceed. Meaningful when paired with `--experiment` (the dashboard's handoff). |
| `--legacy` | Use the deterministic Python orchestrator (default behaviour for now). |
| `--audience [novice\|standard\|expert]` | Control explanation depth in reports and presentations (default: from `urika.toml`'s `[preferences].audience`) |
| `--json` | Emit a JSON result envelope instead of the streaming-prose output. |

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

### `urika dashboard [PROJECT] [OPTIONS]`

Open a browser-based read-only dashboard for a project. Displays experiments, reports, figures, methods, and criteria in an interactive web interface.

**Options:**

| Option | Description |
|--------|-------------|
| `--port PORT` | Server port (default: a random free port) |
| `--auth-token TOKEN` | Require this bearer token on all requests (`Authorization: Bearer <token>`). `/healthz` and `/static` are exempt. See [Dashboard](18-dashboard.md) for the full auth flow. |

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
| `--audience [novice\|standard\|expert]` | Control explanation depth (default: standard) |

When no experiment is specified, you are prompted to choose: a specific experiment, all experiments, or project-level reports.

See [Viewing Results](08-viewing-results.md) for details on report types.

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
| `--audience [novice\|standard\|expert]` | Control explanation depth (default: standard) |

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

After the advisor responds with experiment suggestions, you are offered the option to run them immediately. See [Advisor Chat and Instructions](07-advisor-and-instructions.md) for the full guide on advisor conversations, the suggestion-to-run flow, and how to steer agents with instructions.

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
| `--audience [novice\|standard\|expert]` | Control explanation depth in reports and presentations (default: standard) |
| `--draft` | Interim summary -- outputs to `projectbook/draft/`, does not overwrite final outputs or write standalone scripts |

**Examples:**

```bash
urika finalize my-project
urika finalize my-project --instructions "emphasize the ensemble methods"
urika finalize my-project --draft
urika finalize my-project --draft --audience novice
```

See [Finalizing Projects](09-finalizing-projects.md) for details on what is produced, including draft mode.

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

### `urika summarize`

Run the **Project Summarizer** agent on a project. Reads project files (config, criteria, methods, leaderboard) and the experiment history, then writes a high-level summary to `projectbook/summary.md`.

```
urika summarize [PROJECT] [OPTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |

**Options:**

| Option | Description |
|--------|-------------|
| `--instructions TEXT` | Optional guidance to steer the summarizer (e.g., "focus on open questions"). |
| `--json` | Output the summarizer result as JSON. |

**Examples:**

```bash
urika summarize my-project
urika summarize my-project --instructions "focus on what's still unknown"
urika summarize my-project --json
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

For per-agent model overrides beyond what the interactive setup provides, edit `urika.toml` directly — see [Configuration](14-configuration.md).

#### `urika config api-key`

Interactive setup for the Anthropic API key. Saves to `~/.urika/secrets.env` (mode `0600`); the key is loaded into `os.environ["ANTHROPIC_API_KEY"]` on every subsequent CLI invocation.

```
urika config api-key [--test]
```

| Option | Description |
|--------|-------------|
| `--test` | After saving, verify the key by making a real call to `api.anthropic.com`. Reports success/failure with the response body excerpt on error. |

**Examples:**

```bash
urika config api-key             # interactive prompt, saves to vault
urika config api-key --test      # save + verify
```

The same vault is used by every Urika surface (CLI, TUI, dashboard). To set a key per shell instead, export `ANTHROPIC_API_KEY` directly — process-env always wins over the vault.

#### `urika config secret`

Interactive setup for an arbitrary named secret (e.g., a private vLLM API token, a HuggingFace key, a third-party API credential). Saves to the same global secrets vault as `urika config api-key`. Agents and tools read the secret via `os.environ.get(NAME)`.

```
urika config secret
```

The wizard prompts for the secret name (defaults to a curated allowlist of well-known names from `urika.core.known_secrets` if you don't type one), value, and description. Mask preview shown on save.

**Examples:**

```bash
urika config secret              # interactive — pick from known names
urika config secret              # interactive — enter a custom name
```

Names referenced by `[privacy.endpoints.<n>].api_key_env` are auto-discovered and offered as suggestions.


### `urika notifications`

Configure notification channels (Email, Slack, Telegram). Credentials are saved to `~/.urika/secrets.env`. Channel settings live in `~/.urika/settings.toml` (global) or `<project>/urika.toml` (per-project). With no options, launches an interactive setup wizard.

```
urika notifications [OPTIONS]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--show` | Print the current notification configuration (channels, masked credentials, status). |
| `--test` | Send a test notification through every enabled channel. With `--project`, uses the merged project + global config. |
| `--disable` | Disable notifications for the project (project-level only — pair with `--project`). |
| `--project NAME` | Switch to per-project setup: pick channels (allow-list), add extra recipients, override the Telegram chat ID. |

**Behavior:**

- **Global setup** (no `--project`): configure channel-level credentials and `auto_enable` flags for new projects.
- **Project setup** (`--project NAME`): enable/disable individual channels for that project and add per-project overrides on top of the global config.

**Examples:**

```bash
urika notifications                          # interactive global setup
urika notifications --show                   # show current global config
urika notifications --test                   # send a test on every enabled channel
urika notifications --project my-study       # per-project channel allow-list
urika notifications --project my-study --disable
```

See [Notifications](19-notifications.md) for the full feature guide, including event types, priority levels, and Slack interactive buttons.


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

---

### `urika tui`

Explicitly launch the interactive Urika TUI. Equivalent to running bare `urika` with no subcommand, but discoverable via `urika --help` and easy to invoke from scripts.

```
urika tui [PROJECT]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Optional project name to auto-load on launch. If omitted, the TUI starts without a project loaded. |

**Examples:**

```bash
urika tui                 # launch the TUI (no project loaded)
urika tui my-study        # launch and auto-load my-study
```

The TUI binary is searched in the following order: the `URIKA_TUI_BIN` environment variable, the system `PATH` (`urika-tui`), the local dev build (`packages/urika-tui/dist/urika-tui`), or run via `bun` from `packages/urika-tui/src/index.ts` if available. See [Interactive TUI](17-interactive-tui.md) for usage.

---

### `urika memory`

Read or edit the project memory directory at `<project>/memory/`. Project memory is structured markdown — a curated `MEMORY.md` index plus per-topic entry files (`feedback_*.md`, `instruction_*.md`, `decision_*.md`, …) — that gets injected into the planner's and advisor's system prompts on every run, so the agents stay aware of past decisions, user preferences, and constraints across experiments. Auto-capture from `<memory type="...">...</memory>` markers in agent output is on by default; manual edits live under this command group.

```
urika memory list   [PROJECT] [--json]
urika memory show   [PROJECT] TOPIC
urika memory add    [PROJECT] TOPIC [--type TYPE] [--from-file PATH | --stdin] [--description TEXT]
urika memory delete [PROJECT] FILENAME [--force]
```

**Subcommands:**

| Subcommand | Purpose |
|---|---|
| `list` | List every memory entry. `--json` emits structured output for scripts. |
| `show TOPIC` | Print one entry by filename or slug. Partial matches resolve via prefix glob (`feedback_methods` finds `feedback_methods.md` or `feedback_methods_v2.md`). |
| `add TOPIC` | Write a new entry. `--type` picks one of `user`, `feedback`, `instruction`, `decision`, `reference` (default: `instruction`). Body comes from `--from-file PATH`, `--stdin`, or an interactive editor. |
| `delete FILENAME` | Move the entry to `memory/.trash/` (preserved on disk). Pass `--force` to skip the confirmation prompt. |

**Examples:**

```bash
# Inspect what the agents are seeing
urika memory list my-project

# Capture a methodological constraint from a piped command
echo "Always cross-validate by subject" | urika memory add my-project cv_strategy --stdin

# Read one entry
urika memory show my-project feedback_methods

# Trash an outdated entry
urika memory delete my-project instruction_old_baseline.md --force
```

Soft cap 5 KB per entry (warning), hard cap 20 KB (truncated with marker). Per-project disable via `[memory] auto_capture = false` in `urika.toml`.

---

### `urika sessions`

List or export persisted orchestrator chat sessions. The TUI's orchestrator chat persists each conversation to `<project>/.urika/sessions/<id>.json` (auto-pruned at 20 sessions). This command surfaces them outside the TUI for sharing or scripted review.

```
urika sessions list   [PROJECT] [--json]
urika sessions export [PROJECT] SESSION_ID [--format md|json] [-o FILE]
```

**Subcommands:**

| Subcommand | Purpose |
|---|---|
| `list` | One row per session: ID, started timestamp, message count, preview of first user message. `--json` emits the full structure. |
| `export SESSION_ID` | Render a session to Markdown (`--format md`, default — sharing) or JSON (`--format json`, full fidelity). Output goes to stdout unless `-o FILE` is provided. |

**Examples:**

```bash
# What conversations does this project have?
urika sessions list my-project

# Share a session as a Markdown gist
urika sessions export my-project 20260501-143022-a4b -o session.md

# Full-fidelity dump for a downstream tool
urika sessions export my-project 20260501-143022-a4b --format json
```

---

### `urika completion`

Manage shell completion for the `urika` CLI. Built on Click 8's native completion machinery — works in bash, zsh, and fish.

```
urika completion install    [SHELL] [--force]
urika completion script     [SHELL]
urika completion uninstall  [SHELL]
```

**Subcommands:**

| Subcommand | Purpose |
|---|---|
| `install` | Generate the completion script and append a sourcing line to your shell's rc file. `--force` overwrites an existing entry. Auto-detects bash / zsh / fish from `$SHELL` if `SHELL` argument is omitted. |
| `script` | Print the completion script to stdout — useful when you want to manage sourcing yourself or place the script in a non-default location. |
| `uninstall` | Remove the sourcing line from your shell's rc file. The completion script file itself is left in place. |

**Examples:**

```bash
# One-liner: install + source on next shell
urika completion install
exec $SHELL -l

# Manual: stash the script wherever you keep your completions
urika completion script bash > ~/.bash_completions/urika.bash
echo 'source ~/.bash_completions/urika.bash' >> ~/.bashrc
```

After installing, `urika <TAB><TAB>` shows the command list, project names complete on `urika status <TAB>`, and so on.

---

### `urika --version`

Show the installed Urika version.

```
urika --version
```


## Environment Variables

| Variable | Description |
|----------|-------------|
| `URIKA_PROJECTS_DIR` | Override the default projects directory (default: `~/urika-projects`) |
| `URIKA_HOME` | Override the global config directory (default: `~/.urika`). Also relocates `~/.urika/secrets.env` and the project registry. |
| `URIKA_TUI_BIN` | Explicit path to the TypeScript TUI binary launched by `urika tui` (overrides PATH search). |
| `URIKA_NO_BUILDER_AGENT` | Set to `1` to skip the project-builder agent loop in `urika new` (for scripted use). The agent loop is also auto-skipped under non-TTY stdin. |
| `URIKA_DASHBOARD_AUTH_TOKEN` | Bearer-token gate for `urika dashboard` (matches the `--auth-token` flag). |
| `ANTHROPIC_API_KEY` | API key for Anthropic-routed agent calls. Required for any cloud-bound run; see [Security → Provider compliance](20-security.md#provider-compliance). |
| `ANTHROPIC_BASE_URL` | Custom OpenAI-compatible endpoint URL (set per-agent via `urika config secret`, not exported manually for global config). |
| `INFERENCE_HUB_KEY` (or whichever name is referenced by your endpoint's `api_key_env`) | Auth token for a configured private endpoint. Loaded from `~/.urika/secrets.env` automatically; only needed manually when shelling out. |
| `NO_COLOR` | Set to disable coloured terminal output (colours are on by default for TTYs). |


## Global Behaviors

- **Project argument**: Most commands accept an optional `PROJECT` argument. If omitted and only one project exists, it is used automatically. If multiple projects exist, you are prompted to select one.
- **Versioned files**: Reports, presentations, and other generated files use versioned writing -- previous versions are backed up with timestamps before overwriting.
- **Ctrl+C handling**: During `urika run`, pressing Ctrl+C cleanly pauses the experiment and removes the lock file. Resume with `urika run --resume`.

---

**Next:** [Interactive TUI](17-interactive-tui.md)
