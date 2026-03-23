# Getting Started

Urika is a multi-agent scientific analysis platform. You give it a dataset and a research question; its agents autonomously explore analytical approaches, build tools, evaluate methods, and document everything in a structured projectbook.

Urika works with data from any scientific discipline — tabular data (CSV, Excel, SPSS), images, audio, time series (EEG, HDF5), spatial/3D data, and more. Agents automatically detect your data format, install the libraries they need, and build custom tools when required.

## Requirements

- **Python 3.11 or later** (3.12 also supported)
- **Claude access** via Anthropic API key or Claude Max/Pro account

## Installation

### Basic install

```bash
pip install urika
```

This installs the core platform with the Claude Agent SDK, statistical tools (numpy, pandas, scipy, scikit-learn), and all ten agent roles. Everything you need to get started.

### With visualization

```bash
pip install "urika[viz]"
```

Adds matplotlib and seaborn for chart generation.

### With ML libraries

```bash
pip install "urika[ml]"
```

Adds xgboost and lightgbm for gradient boosting methods.

### With knowledge/PDF support

```bash
pip install "urika[knowledge]"
```

Adds pypdf for ingesting PDF research papers into the knowledge base.

### Full dev install (everything)

```bash
pip install -e ".[dev]"
```

Includes pytest, pytest-asyncio, ruff, and pypdf.

### Install everything at once

```bash
pip install "urika[agents,viz,ml,knowledge]"
```

## Authentication

Urika's agents need access to Claude. Two options:

### Option 1: API key

Set your Anthropic API key as an environment variable:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Add this to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.) to persist it across sessions.

### Option 2: Claude Max/Pro account

If you have a Claude Max or Pro subscription, the Claude Agent SDK can authenticate through your account login. No API key needed — just ensure you're logged in via Claude Code.

## Two ways to use Urika

Urika has two interfaces that share the same commands and produce identical results:

- **Interactive REPL** — Run `urika` with no arguments. Gives you a prompt with tab completion, `/help`, conversation history, and a bottom status bar. Best for learning the system and exploratory work.
- **CLI commands** — Run `urika <command>` directly from your shell. Best for scripting, automation, and when you know exactly what you want to run.

If you're new to Urika, **start with the REPL** — you can discover all commands with tab completion and `/help`, and ask the advisor agent questions in plain text without needing to know any commands at all.

See [CLI Reference](12-cli-reference.md) and [Interactive REPL](13-interactive-repl.md) for full details on each interface.

## Quickstart

### 1. Create a project

```bash
urika new my-study --data /path/to/data.csv
```

Urika prompts for a research question, investigation mode, and description. The project builder agent asks clarifying questions, proposes initial experiments, and writes the project files.

### 2. Launch the REPL (recommended for first-time users)

```bash
urika
```

This opens the interactive shell. Load your project and explore:

```
urika> /project my-study
urika:my-study> /status
urika:my-study> /run
```

Or type a question in plain text — it goes straight to the advisor agent:

```
urika:my-study> what approaches should I try for this dataset?
```

### 3. Or use CLI commands directly

```bash
urika run my-study              # run the next experiment
urika status my-study           # check progress
urika results my-study          # view leaderboard
urika report my-study           # generate reports
urika present my-study          # generate presentation
```

Every REPL slash command has a matching CLI command and vice versa.

## Project location

By default, projects are created under `~/urika-projects/`. Override this with the `URIKA_PROJECTS_DIR` environment variable:

```bash
export URIKA_PROJECTS_DIR="/path/to/my/projects"
```

## Further reading

- [Core Concepts](02-core-concepts.md) -- hierarchy, agents, tools, orchestrator loop
- [Creating Projects](03-creating-projects.md) -- detailed guide to `urika new`
- [Running Experiments](04-running-experiments.md) -- orchestrator, turns, auto mode
