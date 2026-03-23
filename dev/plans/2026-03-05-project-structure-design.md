# Urika Project Structure Design

**Date**: 2026-03-05
**Status**: Approved
**Context**: Restructuring Urika from a single-investigation model to a multi-project research lab model.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Hierarchy | Urika (lab) → Project → Experiment → Run | Maps to MLflow's proven Project>Experiment>Run model and real research lab structure |
| Project scope | One dataset + one research question per project | Keeps projects focused. Broad research programs use multiple projects. |
| Experiment creation | Agents propose, orchestrator creates | Suggestion agent writes experiment proposals; orchestrator creates directories and dispatches task agents |
| Labbook | Agent-written .md files, auto-generated | All labbook content produced by agents. Per-experiment notes/summaries + project-level key findings/results summary. |
| Sub-agents | Project-specific skills instead | Simpler than building agents that create agents. Tool Builder creates project-specific tools + skills. Universal agents use them. |
| Project location | Central registry at `~/.urika/` | `urika list` shows all projects. Projects can live anywhere on disk but are registered centrally. |
| Orchestrator | Hybrid: deterministic loop + LLM at decision points | Deterministic for predictability (task→evaluate→suggest→repeat). LLM consulted at strategic inflection points (pivot? continue? validate?). |
| State tracking | Append-only `progress.json` + generated .md | Machine-readable event log (JSON) paired with human-readable summaries (.md). Append-only for reproducibility. |

---

## 2. The Hierarchy

Three levels: **Urika** (the lab) → **Project** (one dataset + question) → **Experiment** (one analytical campaign) → **Run** (one method execution)

```
Urika (the lab)
  ├── Universal tools, skills, agents — ship with the package
  ├── Global config + project registry
  ├── Cross-project knowledge base
  │
  ├── Project: "sleep-quality-prediction"
  │     ├── One dataset (sleep_survey.csv)
  │     ├── One question ("What predicts sleep quality?")
  │     ├── Success criteria (R² > 0.3, interpretable model)
  │     ├── Project-specific tools + skills (agent-created)
  │     │
  │     ├── Experiment 001: "Baseline linear models"
  │     │     └── Runs: linear_reg, ridge, lasso → metrics, observations
  │     ├── Experiment 002: "Tree-based methods"
  │     │     └── Runs: random_forest, xgboost, lightgbm → metrics, observations
  │     ├── Experiment 003: "Feature engineering + best model"
  │     │     └── Runs: xgboost_v2 with engineered features
  │     │
  │     ├── Labbook (auto-generated .md summaries)
  │     └── Leaderboard (cross-experiment rankings)
  │
  └── Project: "stroop-effect-age"
        ├── One dataset (stroop_rt.csv)
        ├── One question ("Does Stroop effect interact with age?")
        └── ...
```

### Terminology mapping from current PRD

| Current PRD | New term | Notes |
|---|---|---|
| Investigation | Project | Multi-project support via central registry |
| Session | Experiment | Distinct analytical campaigns with hypotheses |
| Run | Run (unchanged) | Single method execution with parameters |
| System Builder | Project Builder | Scopes a project interactively |

---

## 3. Project Workspace on Disk

### Per-project directory

```
~/urika-projects/sleep-quality-prediction/
    urika.toml                         # Project config: question, criteria, mode

    data/                              # Dataset(s) — one or many files
        sleep_survey.csv               # The actual data
        data_dictionary.md             # Column descriptions, units, etc.
        metadata.json                  # Auto-generated schema, profiling results

    tools/                             # Project-specific tools (agent-created)
        sleep_feature_extractor.py
        tools_registry.json            # Registry of project tools

    skills/                            # Project-specific skills (agent-created)
        sleep_scoring.md               # Prompt template for domain-specific work

    methods/                           # Project-specific methods (agent-created)
        custom_sleep_model.py

    knowledge/                         # Project-specific knowledge
        papers/                        # Ingested PDFs, extracted text
        literature_index.json          # Index of papers + summaries
        notes/                         # Agent research notes

    experiments/
        exp-001-baseline/
            experiment.json            # Config: intent, hypothesis, agent config
            methods/                   # Methods specific to this experiment
            progress.json              # Append-only run log
            labbook/
                notes.md               # Agent observations during experiment
                summary.md             # Auto-generated experiment summary
            artifacts/                 # Plots, tables, models from this experiment

        exp-002-tree-models/
            experiment.json
            methods/
            progress.json
            labbook/
                notes.md
                summary.md
            artifacts/

    labbook/                           # Project-level labbook (aggregates experiments)
        key-findings.md                # Best results, key insights
        results-summary.md             # All experiments summarized in table form
        progress-overview.md           # High-level project trajectory narrative

    leaderboard.json                   # Cross-experiment method rankings

    config/
        success_criteria.json          # What "done" means
        agents.json                    # Agent team configuration
```

### Global Urika installation

```
~/.urika/
    config.toml                        # Global settings (default model, API keys, paths)
    projects.json                      # Registry: name → path for all projects

    tools/                             # Universal tools (ship with urika package)
        data_profiler.py
        hypothesis_tests.py
        correlation.py
        visualization.py

    skills/                            # Universal skills (ship with urika package)
        exploratory_analysis.md
        assumption_checking.md
        report_writing.md

    knowledge/                         # Cross-project knowledge (grows over time)
        methods_tried.json             # What methods worked for which data types
```

---

## 4. Agent Roles (Research Team Model)

| Agent | Research Team Equivalent | Role | Trust Level |
|---|---|---|---|
| **Project Builder** | PI (scoping) | Interactive setup: defines question, ingests data, sets criteria, configures team | Highest |
| **Orchestrator** | Lab Manager + PI advisor | Deterministic loop with LLM at strategic decision points | High (mostly deterministic) |
| **Task Agent** | PhD Student | Writes Python code, runs experiments, records observations | Medium |
| **Evaluator** | Independent Statistician | Read-only scoring, validates criteria, updates leaderboard | High (read-only, trustworthy) |
| **Suggestion Agent** | Senior Postdoc | Analyzes results, searches literature, proposes next experiments | Medium-High |
| **Tool Builder** | Lab Technician / Engineer | Creates tools + skills, tests before registering | Medium |
| **Literature Agent** | Research Assistant | Searches papers, builds knowledge base | Low-Medium |

### Hybrid Orchestrator

The orchestrator runs a deterministic loop: **task → evaluate → criteria check → suggest → (tool build if requested) → next task**

At strategic decision points, it consults an LLM:

1. **After each experiment completes**: "Is this line of investigation productive, or should we pivot?"
2. **After N experiments**: "Have we explored enough, or are there untried approaches?"
3. **When criteria are met**: "Is this result robust enough, or should we run validation?"
4. **When criteria seem unreachable**: "Should we suggest revised criteria to the user?"

### Experiment Lifecycle

The suggestion agent can propose new experiments (not just next runs):

```json
{
  "type": "new_experiment",
  "name": "Feature engineering with domain knowledge",
  "hypothesis": "Sleep architecture features will improve prediction over raw summary stats",
  "approach": "Create feature extraction tools, re-run best model with engineered features",
  "priority": "high",
  "builds_on": ["exp-001", "exp-002"]
}
```

The orchestrator creates the experiment directory and dispatches the task agent with this context.

### Trust Model (unchanged from current PRD)

1. `evaluation/` and `success_criteria.json` are read-only for task agents
2. Evaluator agent cannot write to `methods/` or `tools/`
3. Orchestrator validates criteria independently after agent claims success
4. If agent lies about `criteria_met`, orchestrator corrects the flag on disk

---

## 5. The Labbook System

The labbook is a set of auto-generated markdown files serving as the project's "institutional memory." All content is produced by agents.

### Per-experiment labbook (`experiments/exp-001/labbook/`)

**`notes.md`** — Written by the task agent during runs. Stream-of-consciousness observations:

```markdown
## Run 001: Linear Regression (baseline)
- R² = 0.72, RMSE = 0.15
- Residual plot shows clear nonlinearity — linear model is insufficient
- Strong multicollinearity between sleep_duration and time_in_bed (r=0.94)
- Dropping time_in_bed improved stability without hurting R²

## Run 002: Ridge Regression (alpha=0.1)
- Marginal improvement: R² = 0.73
- Regularization didn't help much — issue is model form, not overfitting
```

**`summary.md`** — Written by the suggestion agent after the experiment concludes:

```markdown
# Experiment 001: Baseline Linear Models
**Hypothesis**: Linear models can establish a reasonable baseline.
**Result**: Partial success. R²=0.73 (best), but residual analysis reveals nonlinear relationships.
**Key finding**: Multicollinearity between sleep_duration and time_in_bed.
**Implication**: Tree-based methods likely needed.
```

### Project-level labbook (`labbook/`)

**`results-summary.md`** — Updated after each experiment:

```markdown
# Results Summary
| Experiment | Best Method | Best R² | Key Insight |
|---|---|---|---|
| exp-001: Baseline linear | Ridge regression | 0.73 | Nonlinearity in residuals |
| exp-002: Tree models | XGBoost | 0.85 | Top features: exercise, caffeine, screen_time |
| exp-003: Feature engineering | XGBoost + engineered | 0.89 | Sleep architecture features +4% |
```

**`key-findings.md`** — The executive summary, updated when significant findings emerge:

```markdown
# Key Findings
1. **Best model**: XGBoost with engineered features (R²=0.89, RMSE=0.042)
2. **Top predictors**: Exercise frequency, evening caffeine, screen time before bed
3. **Surprise**: Sleep duration alone is a poor predictor (r=0.31)
4. **Methodological**: Linear models plateau at R²≈0.73 due to nonlinear interactions
```

**`progress-overview.md`** — High-level narrative of the project trajectory:

```markdown
# Progress Overview
Started with baseline linear models (exp-001). Established R²=0.73 floor.
Residual analysis revealed nonlinearity → tree-based methods (exp-002).
XGBoost reached R²=0.85. Feature importance suggested sleep architecture
features → created extraction tools → exp-003 pushed to R²=0.89.
```

### Machine-readable state

**`progress.json`** (per-experiment, append-only) remains the comprehensive machine-readable log:

```json
{
  "experiment_id": "exp-001-baseline",
  "hypothesis": "Linear models can establish a reasonable baseline",
  "status": "completed",
  "runs": [
    {
      "run_id": "run-001",
      "method": "linear_regression",
      "params": {"fit_intercept": true},
      "metrics": {"rmse": 0.15, "r2": 0.72},
      "hypothesis": "Baseline linear model to establish floor",
      "observation": "R2=0.72, significant nonlinearity in residuals",
      "next_step": "Try regularized models",
      "agent_role": "task_agent",
      "timestamp": "2026-03-05T10:23:00Z",
      "artifacts": ["artifacts/run-001-residuals.png"]
    }
  ]
}
```

---

## 6. Universal vs Project-Specific Resources

### Universal (ship with `urika` package)

| Type | Location | Examples |
|---|---|---|
| Agents | `src/urika/agents/` | Task Agent, Evaluator, Suggestion Agent, Tool Builder, Literature Agent |
| Tools | `~/.urika/tools/` | data_profiler, hypothesis_tests, correlation, visualization |
| Skills | `~/.urika/skills/` | exploratory_analysis, assumption_checking, report_writing |
| Methods | `src/urika/methods/` | linear_regression, logistic_regression, random_forest, etc. |
| Metrics | `src/urika/evaluation/` | RMSE, R², F1, Cohen's d, etc. |

### Project-specific (agent-created during project execution)

| Type | Location | Created By | Example |
|---|---|---|---|
| Tools | `<project>/tools/` | Tool Builder | `sleep_feature_extractor.py` |
| Skills | `<project>/skills/` | Tool Builder / Suggestion Agent | `sleep_scoring.md` |
| Methods | `<project>/methods/` | Task Agent | `custom_sleep_model.py` |
| Knowledge | `<project>/knowledge/` | Literature Agent | Papers, summaries, notes |

### Discovery mechanism

1. Agent starts → loads universal tools/skills/methods from package
2. Agent loads project-specific tools/skills/methods from project directory
3. Both merged into agent's available capabilities
4. New tools/skills created during execution become immediately available via registry refresh

### Cross-project knowledge

`~/.urika/knowledge/methods_tried.json` tracks which methods worked for which data types across all projects. The suggestion agent can consult this when starting a new project to leverage past experience.

---

## 7. CLI

```
# Project management
urika new <name>                    # Create project (Project Builder agent)
urika list                          # List all registered projects
urika open <name>                   # Set active project
urika status                        # Show active project status

# Running experiments
urika run                           # Start new experiment in active project
urika run --continue                # Continue last experiment
urika run --max-turns <n>           # Limit agent turns
urika run --experiment <name>       # Continue specific experiment

# Results & reporting
urika results                       # Show leaderboard + experiment summaries
urika compare <exp1> <exp2>         # Compare two experiments
urika report                        # Generate final project report
urika labbook                       # View the project labbook

# Knowledge
urika knowledge ingest <path>       # Ingest PDF/paper/notes into project
urika knowledge search <query>      # Search project knowledge base

# Tools & skills
urika tools --list                  # List available tools (universal + project)
urika skills --list                 # List available skills
```

### Typical workflow

1. `urika new sleep-quality` → Project Builder asks about dataset, question, criteria
2. `urika run` → Orchestrator creates exp-001, dispatches task agent
3. Agents work autonomously: explore → try methods → evaluate → suggest
4. Orchestrator creates new experiments as suggestion agent proposes them
5. `urika status` — check progress anytime
6. `urika labbook` — read auto-generated findings
7. `urika report` — final summary after criteria met or user decides to stop

---

## 8. Key Changes from Current PRD

| Aspect | Current PRD | This Design |
|---|---|---|
| Top-level unit | Investigation (single) | Project (multi-project via registry) |
| Sub-unit | Session (continuation) | Experiment (distinct campaign with hypothesis) |
| Documentation | `progress.json` only | Labbook system: .md notes + summaries + key findings + progress.json |
| Tool scope | All tools at investigation level | Universal (ship with Urika) + project-specific (agent-created) |
| Skill concept | Not in PRD | Universal + project-specific skills (prompt templates) |
| Orchestrator | Deterministic loop | Hybrid: deterministic + LLM at decision points |
| Experiment creation | User creates sessions | Suggestion agent proposes experiments, orchestrator creates them |
| State tracking | Mutable progress.json | Append-only progress.json for reproducibility |
| Cross-project | Not supported | Central registry, cross-project knowledge base |

---

## 9. Investigation Modes (retained from current PRD)

The three investigation modes still apply, now scoped to experiments within a project:

- **Exploratory** (default): Try methods → evaluate → rank → suggest → repeat
- **Confirmatory**: Pre-specified analysis → run → diagnostics → report. No leaderboard.
- **Pipeline**: Ordered preprocessing → analysis. For multi-step domains (EEG, motor control).

The mode is set per-project in `urika.toml`:

```toml
[project]
name = "sleep-quality-prediction"
mode = "exploratory"
```

---

## 10. Open Questions for Implementation

1. **Experiment naming**: Auto-generated (`exp-001`) or agent-named (`baseline-linear-models`)? Recommend: both — auto-increment ID + descriptive suffix from hypothesis.
2. **Labbook update frequency**: After every run, or only at experiment boundaries? Recommend: notes.md after every run, summary.md at experiment end, key-findings.md when significant.
3. **Cross-project knowledge format**: Simple JSON index vs vector store for semantic search? Recommend: JSON for v0.x, vector store optional in v1.x.
4. **Project templates**: Pre-configured projects for common scenarios (e.g., "compare two groups on continuous outcome")? Recommend: yes, as a v1 feature.
5. **`urika.toml` schema**: Needs full specification. Key fields: project name, mode, dataset paths, research question, success criteria references.
