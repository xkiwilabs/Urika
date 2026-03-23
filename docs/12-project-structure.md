# Project Structure

Every Urika project follows a standard directory layout. This page documents every file and directory, from the project root down to individual experiment artifacts.


## Complete File Tree

```
my-project/
  urika.toml                    # Project configuration
  criteria.json                 # Versioned success criteria
  methods.json                  # Registry of agent-created methods
  usage.json                    # Session usage tracking (tokens, cost, duration)
  README.md                     # Auto-generated project README
  data/                         # Dataset files
  experiments/                  # All experiments
    exp-001-baseline-models/    # One experiment
      experiment.json           # Experiment config (name, hypothesis, status)
      progress.json             # Append-only run log
      session.json              # Orchestration state (turns, status, checkpoints)
      methods/                  # Method scripts created during this experiment
      labbook/                  # Auto-generated documentation
        notes.md                # Experiment notes and observations
        narrative.md            # Agent-written narrative summary
      artifacts/                # Plots, saved models, intermediate outputs
      suggestions/              # Advisor suggestions for next steps
      presentation/             # Experiment-level slide deck (if generated)
  knowledge/                    # Ingested domain knowledge
    index.json                  # Knowledge entry metadata and content
    papers/                     # Convention for PDF sources
    notes/                      # Convention for text notes
  methods/                      # Project-level method scripts
  tools/                        # Project-specific tools (created by tool_builder)
  suggestions/                  # Project-level suggestions
    initial.json                # Initial analytical approach suggestions from project builder
  projectbook/                  # Project-level documentation
    results-summary.md          # Aggregated results across all experiments
    key-findings.md             # Important discoveries and conclusions
    progress-overview.md        # High-level progress narrative
    narrative.md                # Agent-written project narrative
    presentation/               # Project-level reveal.js slide deck
      index.html                # Rendered presentation
```


## Project Root Files

### urika.toml

The project configuration file. Contains the project name, research question, mode, data paths, and optional preferences. Created by `urika new` and not modified during experiments. See [Configuration](11-configuration.md) for full details.

### criteria.json

Versioned success criteria. The project builder sets initial criteria; the advisor agent evolves them as experiments progress. Each version is appended, preserving the full history. See [Configuration](11-configuration.md#criteriajson).

### methods.json

Registry of all analytical methods created by agents. Each entry tracks the method name, description, script path, originating experiment, metrics, and status (active or superseded). See [Configuration](11-configuration.md#methodsjson).

### usage.json

Cumulative session usage data: tokens consumed, estimated cost, duration, agent calls, and experiments run. Updated after each session. See [Configuration](11-configuration.md#usagejson).

### README.md

Auto-generated project README with the project name, research question, mode, and an agent-written summary. Updated by the report agent after experiments complete.


## Directories

### data/

Contains the project's dataset files. Files are copied or linked here during `urika new`. Agents read from this directory but do not modify its contents. Supports CSV, Excel, Parquet, JSON, and other tabular formats.

### experiments/

Contains all experiments for the project. Each experiment gets its own subdirectory with a structured name like `exp-001-baseline-models` (sequential ID + slugified name).

### knowledge/

Stores ingested domain knowledge. The `index.json` file holds all entry metadata and extracted content. The `papers/` and `notes/` subdirectories are organizational conventions for source files. See [Knowledge Pipeline](10-knowledge-pipeline.md).

### methods/

Project-level directory for method scripts. Methods created by the task agent during experiments are referenced here (or in the experiment's own `methods/` directory). Each method is a Python script implementing an analytical pipeline.

### tools/

Project-specific tools created by the tool_builder agent. Each `.py` file must implement the `ITool` interface and export a `get_tool()` factory function. The tool registry discovers these automatically via `discover_project()`. See [Built-in Tools](09-built-in-tools.md#project-specific-tools).

### suggestions/

Project-level suggestions directory. Contains `initial.json` with the initial analytical approach suggestions generated by the project builder agent during project creation.

### projectbook/

Project-level documentation that aggregates results across all experiments.

| File | Description |
|------|-------------|
| `results-summary.md` | Aggregated results: best methods, key metrics, leaderboard |
| `key-findings.md` | Important discoveries, significant results, unexpected patterns |
| `progress-overview.md` | High-level narrative of project progress (question, mode, status) |
| `narrative.md` | Agent-written narrative summarizing the analytical journey |
| `presentation/index.html` | Reveal.js slide deck generated by the presentation agent |

The first three files are initialized when the project is created and updated as experiments complete. The narrative and presentation are generated on demand via `urika report` and `urika present`.


## Experiment Directory Structure

Each experiment directory under `experiments/` contains:

### experiment.json

Experiment configuration and metadata:

```json
{
  "experiment_id": "exp-001-baseline-models",
  "name": "Baseline Models",
  "hypothesis": "Linear models will establish a baseline R2 of at least 0.3",
  "status": "completed",
  "builds_on": [],
  "created_at": "2026-03-15T10:00:00+00:00"
}
```

The `builds_on` field lists experiment IDs that this experiment extends (e.g., `["exp-001-baseline-models"]` for a follow-up experiment).

### progress.json

Append-only log of all runs within the experiment:

```json
{
  "experiment_id": "exp-001-baseline-models",
  "status": "completed",
  "runs": [
    {
      "run_id": "run-001",
      "method": "baseline_linear",
      "params": {"target": "accuracy", "features": null},
      "metrics": {"r2": 0.42, "rmse": 1.23, "mae": 0.98},
      "hypothesis": "Linear regression as baseline",
      "observation": "R2=0.42, moderate fit with 3 significant predictors",
      "next_step": "Try random forest to capture non-linear effects",
      "artifacts": ["artifacts/linear_coefficients.png"],
      "timestamp": "2026-03-15T10:05:00+00:00"
    }
  ]
}
```

Each run records the method used, parameters, metrics achieved, the agent's observation, and the suggested next step.

### session.json

Orchestration state for active or completed experiment sessions:

```json
{
  "experiment_id": "exp-001-baseline-models",
  "status": "completed",
  "started_at": "2026-03-15T10:00:00+00:00",
  "paused_at": null,
  "completed_at": "2026-03-15T10:12:30+00:00",
  "current_turn": 5,
  "max_turns": 5,
  "agent_sessions": {},
  "checkpoint": {}
}
```

Valid statuses: `running`, `paused`, `completed`, `failed`.

### methods/

Method scripts created by the task agent during this experiment. Each is a standalone Python file implementing one analytical approach.

### labbook/

Auto-generated documentation for the experiment:

- **notes.md** -- initialized with the experiment name and hypothesis; agents append observations
- **narrative.md** -- agent-written narrative summarizing the experiment's methods, results, and conclusions (generated by the report agent)

### artifacts/

Output files from tool and method execution: plots (PNG), saved models, intermediate data files, and other artifacts referenced by run records.

### suggestions/

Advisor agent suggestions for what to try next within this experiment.

### presentation/

Experiment-level reveal.js slide deck, if generated via `urika present`.


## Global Registry

Urika maintains a central project registry at:

```
~/.urika/projects.json
```

This is a simple name-to-path mapping:

```json
{
  "dht-target-selection": "/home/user/urika-projects/dht-target-selection",
  "reaction-times": "/home/user/urika-projects/reaction-times"
}
```

The registry is managed by `ProjectRegistry` and is how CLI commands like `urika status my-project` resolve project names to directory paths. The registry location can be changed via the `URIKA_HOME` environment variable (defaults to `~/.urika`).

Commands that interact with the registry:

| Command | Effect |
|---------|--------|
| `urika new` | Adds an entry |
| `urika list` | Lists all entries |
| `urika status <project>` | Looks up path by name |
