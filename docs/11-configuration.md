# Configuration

Urika projects are configured through a combination of files in the project directory and environment variables. This page covers all configuration surfaces.


## urika.toml

The primary project configuration file, created during `urika new`. Lives at the root of every project directory.

### [project] section

```toml
[project]
name = "dht-target-selection"
question = "Which features best predict DHT target selection accuracy?"
mode = "exploratory"
description = "Modelling target selection performance from participant and task features"
data_paths = ["/home/user/data/participants.csv"]
```

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `name` | string | yes | Project identifier, used in the registry and CLI |
| `question` | string | yes | The research question agents are trying to answer |
| `mode` | string | yes | One of `"exploratory"`, `"confirmatory"`, or `"pipeline"` |
| `description` | string | no | Longer description of the project goals |
| `data_paths` | list of strings | no | Paths to the dataset files |
| `success_criteria` | table | no | Initial success criteria (typically set by project_builder) |

**Modes:**

- **exploratory** -- agents freely explore methods and features to understand the data
- **confirmatory** -- agents test specific pre-registered hypotheses
- **pipeline** -- agents build a production-ready analytical pipeline

### [preferences] section

Optional section for controlling experiment behavior:

```toml
[preferences]
max_turns_per_experiment = 5
auto_mode = "checkpoint"
presentation_theme = "light"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_turns_per_experiment` | integer | `5` | Maximum orchestrator turns per experiment run |
| `auto_mode` | string | `"checkpoint"` | How the REPL runs experiments: `"checkpoint"` (pause for confirmation), `"full"` (run all turns), or `"capped"` (run up to max turns) |
| `presentation_theme` | string | `"light"` | Reveal.js theme for generated presentations |

These preferences can be overridden at runtime via CLI flags or REPL prompts.


## criteria.json

Versioned criteria that define what "good enough" looks like for the project. Criteria evolve over the course of experimentation as agents learn more about the data and problem.

### Structure

```json
{
  "versions": [
    {
      "version": 1,
      "set_by": "project_builder",
      "turn": 0,
      "rationale": "Initial criteria based on exploratory analysis goals",
      "criteria": {
        "method_validity": "Method must be appropriate for the data type",
        "parameter_adequacy": "Hyperparameters must be justified",
        "quality": "R2 > 0.3 for regression tasks",
        "completeness": "Must report train and test metrics"
      }
    },
    {
      "version": 2,
      "set_by": "advisor_agent",
      "turn": 8,
      "rationale": "Raising bar after baseline models exceeded initial threshold",
      "criteria": {
        "method_validity": "Method must be appropriate for the data type",
        "parameter_adequacy": "Hyperparameters must be tuned via cross-validation",
        "quality": "R2 > 0.5 with cross-validated estimate",
        "completeness": "Must report train, validation, and test metrics",
        "threshold": "Improvement over best baseline by at least 5%",
        "comparative": "Must compare against at least 2 previous methods"
      }
    }
  ]
}
```

### CriteriaVersion fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | integer | Sequential version number (1, 2, 3, ...) |
| `set_by` | string | Agent that set this version (`"project_builder"`, `"advisor_agent"`) |
| `turn` | integer | Orchestrator turn when criteria were updated |
| `rationale` | string | Why the criteria changed |
| `criteria` | dict | Named criteria with descriptions or thresholds |

### Criteria types

Criteria are freeform key-value pairs, but commonly include:

| Key | Purpose |
|-----|---------|
| `method_validity` | Is the analytical method appropriate for this data and question? |
| `parameter_adequacy` | Are hyperparameters and settings properly justified or tuned? |
| `quality` | Numeric performance thresholds (e.g., R2, accuracy, RMSE) |
| `completeness` | What must be reported (metrics, splits, confidence intervals) |
| `threshold` | Minimum improvement over previous best |
| `comparative` | Requirements for comparing against baselines |

### How criteria evolve

1. The **project_builder** sets initial criteria during `urika new`, based on the research question and data profile
2. The **evaluator** scores each run against the current criteria
3. The **advisor_agent** can update criteria between experiments -- typically raising the bar after initial baselines are established
4. All versions are preserved, creating an audit trail of how standards evolved

### Viewing criteria

```bash
urika criteria <project>
```

Shows the current criteria version and its history.

### API

```python
from urika.core.criteria import load_criteria, load_criteria_history, append_criteria

# Get current (latest) criteria
current = load_criteria(project_dir)  # Returns CriteriaVersion or None

# Get full history
history = load_criteria_history(project_dir)  # Returns list[CriteriaVersion]

# Add a new version
append_criteria(
    project_dir,
    criteria={"quality": "R2 > 0.6"},
    set_by="advisor_agent",
    turn=12,
    rationale="Previous threshold exceeded consistently",
)
```


## methods.json

Tracks all analytical methods created by agents during experiments. Located at the project root.

```json
{
  "methods": [
    {
      "name": "baseline_linear",
      "description": "OLS linear regression with all numeric features",
      "script": "methods/baseline_linear.py",
      "created_by": "task_agent",
      "experiment": "exp-001-baseline-models",
      "turn": 2,
      "metrics": {"r2": 0.42, "rmse": 1.23},
      "status": "active",
      "superseded_by": null
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `name` | Unique method identifier |
| `description` | What the method does |
| `script` | Path to the Python script (relative to project root) |
| `created_by` | Always `"task_agent"` |
| `experiment` | Experiment ID where this method was created |
| `turn` | Orchestrator turn number |
| `metrics` | Best metrics achieved by this method |
| `status` | `"active"` or `"superseded"` |
| `superseded_by` | Name of the method that replaced this one (if superseded) |

View registered methods with:

```bash
urika methods <project>
```


## usage.json

Tracks session-level resource usage per project. Updated automatically after each experiment run.

```json
{
  "sessions": [
    {
      "started": "2026-03-15T10:00:00+00:00",
      "ended": "2026-03-15T10:12:30+00:00",
      "duration_ms": 750000,
      "tokens_in": 45000,
      "tokens_out": 12000,
      "cost_usd": 0.315,
      "agent_calls": 18,
      "experiments_run": 1
    }
  ],
  "totals": {
    "sessions": 1,
    "total_duration_ms": 750000,
    "total_tokens_in": 45000,
    "total_tokens_out": 12000,
    "total_cost_usd": 0.315,
    "total_agent_calls": 18,
    "total_experiments": 1
  }
}
```

View usage with:

```bash
urika usage <project>
```

Cost estimates use Claude API pricing (Sonnet by default; adjusts for Opus and Haiku).


## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (none) | Claude API key. Required for running experiments and agent-powered commands. |
| `URIKA_PROJECTS_DIR` | `~/urika-projects` | Default directory where `urika new` creates project directories. |
| `URIKA_HOME` | `~/.urika` | Location of the global Urika config directory (contains `projects.json` registry). |
| `NO_COLOR` | (unset) | When set to any value, disables all terminal colors and formatting. Follows the [no-color.org](https://no-color.org) convention. |
| `URIKA_REPL` | (unset) | Set internally when running inside the REPL. Used to prevent nested REPL sessions and adjust CLI behavior. |

Colors are enabled by default when stdout is a TTY. Setting `NO_COLOR=1` disables them. When stdout is not a TTY (e.g., piped output), colors are automatically disabled.
