# Getting Started

Urika is a multi-agent scientific analysis platform. You give it a dataset and a research question; its agents autonomously explore analytical approaches, build tools, evaluate methods, and document everything in a structured projectbook.

## Requirements

- **Python 3.11 or later** (3.12 also supported)
- **Claude access** via Anthropic API key or Claude Max/Pro account

## Installation

### Basic install

```bash
pip install urika
```

This installs the core platform with statistical tools (numpy, pandas, scipy, scikit-learn).

### With agent support (required for running experiments)

```bash
pip install "urika[agents]"
```

Adds the Claude Agent SDK, which powers all nine agent roles.

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

## Quickstart

### 1. Create a project

```bash
urika new my-study --data /path/to/data.csv
```

Urika will prompt you for a research question, investigation mode, and project description. The project builder agent then asks clarifying questions, proposes initial experiments, and writes the project files.

### 2. Run the first experiment

```bash
urika run my-study
```

The orchestrator picks up the planned experiment and cycles through agents (planning, task execution, evaluation, advising) for up to the configured number of turns.

### 3. Check status

```bash
urika status my-study
```

Shows the project question, mode, number of experiments, and per-experiment run counts.

### 4. View results

```bash
urika results my-study
```

Displays the leaderboard ranking methods by their metrics.

### 5. Generate a report

```bash
urika report my-study
```

Produces labbook notes, narrative summaries, and a project README.

### 6. Launch the interactive REPL

```bash
urika
```

Running `urika` with no subcommand opens the interactive shell, where you can use slash commands like `/run`, `/report`, `/advisor`, and more.

## Project location

By default, projects are created under `~/urika-projects/`. Override this with the `URIKA_PROJECTS_DIR` environment variable:

```bash
export URIKA_PROJECTS_DIR="/path/to/my/projects"
```

## Further reading

- [Core Concepts](02-core-concepts.md) -- hierarchy, agents, tools, orchestrator loop
- [Creating Projects](03-creating-projects.md) -- detailed guide to `urika new`
- [Running Experiments](04-running-experiments.md) -- orchestrator, turns, auto mode
