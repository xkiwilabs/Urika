# Viewing Results and Reports

This guide covers how to view experiment results, generate reports, create presentations, and inspect project state.


## Project Dashboard

```
urika dashboard [PROJECT] [--port PORT]
```

The quickest way to browse all project outputs. Opens a browser-based dashboard with:

- **Sidebar** — curated project tree: experiments (labbook, artifacts, presentations), projectbook, methods, criteria
- **Content area** — rendered markdown, syntax-highlighted JSON/Python, zoomable images (click any figure to enlarge)
- **Footer** — project stats at a glance (experiment count, methods, best metric)

Experiments are listed newest-first and collapsed by default. Presentations open in a new tab. Light/dark mode toggle in the header.

In the REPL: `/dashboard` to start, `/dashboard stop` to shut down.


## Results and Leaderboard

```
urika results [PROJECT] [--experiment EXPERIMENT_ID]
```

Without `--experiment`, this shows the **project leaderboard** -- a ranked list of the best-performing method from each experiment, sorted by the primary metric:

```
  #1  xgboost_with_fov_constraints  top1_accuracy=0.847, rmse=0.312
  #2  random_forest_baseline        top1_accuracy=0.791, rmse=0.358
  #3  linear_regression             top1_accuracy=0.623, rmse=0.501
```

The leaderboard uses a **best-per-method** strategy: only the best run for each method is shown. Ranking respects the configured direction (`higher_is_better` or `lower_is_better`).

With `--experiment`, it shows all individual runs for that experiment:

```
urika results my-project --experiment exp-001
```

```
  run-001  linear_regression  r2=0.45, rmse=0.72
  run-002  ridge_regression   r2=0.51, rmse=0.68
```


## Methods

```
urika methods [PROJECT]
```

Lists all agent-created methods across all experiments, with their status and top metrics:

```
  linear_regression      [completed]  top1_accuracy=0.623, rmse=0.501
  random_forest_baseline [completed]  top1_accuracy=0.791, rmse=0.358
  xgboost_with_fov       [completed]  top1_accuracy=0.847, rmse=0.312
```

Methods are registered automatically by the task agent during experiment runs. Each method has an associated Python script stored in the experiment's `methods/` directory.


## Experiment Logs

```
urika logs [PROJECT] [--experiment EXPERIMENT_ID]
```

Shows detailed run-by-run logs for an experiment, including each run's hypothesis, observation, and suggested next step. If multiple experiments exist and none is specified, you are prompted to select one.

```
  run-001  linear_regression  r2=0.45, rmse=0.72
    Hypothesis: Simple linear model as baseline
    Observation: Moderate fit, residuals show non-linearity
    Next step: Try non-linear models or feature interactions

  run-002  ridge_regression  r2=0.51, rmse=0.68
    Hypothesis: Regularization may help with collinear features
    Observation: Slight improvement, alpha=0.1 optimal
    Next step: Try tree-based methods for non-linear relationships
```


## Reports

```
urika report [PROJECT] [--experiment EXPERIMENT_ID]
```

Generates labbook reports. When no experiment is specified, you are prompted to choose from:

1. **A specific experiment** -- generates notes, summary, and narrative for that experiment
2. **All experiments** -- generates reports for every experiment in the project
3. **Project level** -- generates project-wide reports across all experiments

### Report types

Reports are written as versioned markdown files (previous versions are backed up with timestamps).

**Experiment-level reports** (stored in `experiments/<id>/labbook/`):

| File | Contents |
|------|----------|
| `notes.md` | Auto-generated from `progress.json`. Lists every run with metrics, parameters, hypothesis, observation, next step, and inline figures matched by method name. |
| `summary.md` | Experiment summary with a metrics comparison table, best run highlight, key observations, and embedded artifact figures. |
| `narrative.md` | Agent-written narrative report. The report agent reads the experiment data and writes a coherent research narrative. |

**Project-level reports** (stored in `projectbook/`):

| File | Contents |
|------|----------|
| `results-summary.md` | Table of all experiments with their best method, run count, and key metrics. |
| `key-findings.md` | Comprehensive project overview: project details, experiment table, methods tried, current criteria, key findings with best result, and embedded figures from all experiments. |
| `narrative.md` | Agent-written project-level narrative covering the full research progression. |
| `README.md` | Auto-generated project README at the project root, with an agent-written status summary. |

**Finalization outputs** (produced by `urika finalize`, stored in `projectbook/`):

| File | Contents |
|------|----------|
| `final-report.md` | Comprehensive final report written by the Report Agent from the Finalizer's findings. Structured as Abstract, Introduction, Methods, Results, Discussion, Reproducibility, References. |
| `final-presentation/` | Definitive reveal.js presentation created by the Presentation Agent from the Finalizer's findings. |

See [Finalizing Projects](08-finalizing-projects.md) for the complete list of finalization outputs.


## Presentations

```
urika present [PROJECT]
```

Generates interactive reveal.js slide decks from experiment results. You are prompted to choose:

1. **A specific experiment** -- creates a presentation for that experiment
2. **All experiments** -- creates a separate presentation for each experiment
3. **Project level** -- creates one overarching presentation covering all experiments

The presentation agent reads experiment data and outputs structured slide JSON, which is rendered into HTML using bundled reveal.js templates.

Output is saved to:
- `experiments/<id>/presentation/index.html` for experiment-level
- `projectbook/presentation/index.html` for project-level

### Slide types

The presentation system supports four slide types:

| Type | Description |
|------|-------------|
| `bullets` | Standard slide with a title and bullet points |
| `stat` | Big-number display with a stat value, label, and optional bullets |
| `figure` | Full-width figure with caption and optional bullets |
| `figure-text` | Two-column layout with figure on the left and text on the right |

The presentation theme (`light` or `dark`) is read from `urika.toml`:

```toml
[preferences]
presentation_theme = "dark"
```


## Criteria

```
urika criteria [PROJECT]
```

Shows the current success criteria for the project. Criteria are versioned and can be updated by the advisor agent during experiment runs.

```
  Criteria v2 (set by advisor_agent)
  Type: regression
  Primary: top1_accuracy > 0.85
```

Criteria include:
- **Version number** -- incremented each time criteria are updated
- **Set by** -- which agent or user set the criteria
- **Type** -- the analysis type (e.g., regression, classification)
- **Primary threshold** -- the target metric, direction, and target value


## Usage

```
urika usage [PROJECT]
```

Shows usage statistics and estimated costs. Without a project argument, shows totals across all projects:

```
  Usage across all projects:
  my-project: 3 sessions · 245K tokens · ~$1.23
  other-project: 1 session · 52K tokens · ~$0.31
```

With a project argument, shows detailed session-level usage:

```
  Usage: my-project
  Last session: 12m 34s · 82K tokens · ~$0.41 · 8 agent calls
  All time:     3 sessions · 45m · 245K tokens · ~$1.23 · 24 agent calls · 5 experiments
```

Usage tracking records tokens (input and output), estimated cost (at API rates), agent calls, session duration, and experiments run. For subscription users, costs are estimates that do not apply to your plan.

---

**Next:** [Finalizing Projects](08-finalizing-projects.md)
