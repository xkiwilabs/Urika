# Finalizer Agent — Design Plan

> **Goal:** When research is complete, produce polished, standalone deliverables: production-ready methods, comprehensive final report, and presentation — suitable for sharing, publication, or handoff.

## Why

Experiments produce working notes and interim results. But researchers need:
- Clean, documented, standalone code they can share or publish
- A comprehensive report covering the full research progression
- A presentation they can give to colleagues
- Reproducibility instructions so others can replicate the analysis

Currently these exist as interim artifacts scattered across experiments. The Finalizer consolidates everything into polished final outputs.

## Architecture: Option C (Hybrid)

A new **Finalizer Agent** handles analysis and method selection. Existing **Report** and **Presentation** agents handle their specialties. The Finalizer orchestrates the sequence.

```
urika finalize my-project
    │
    ├── 1. Finalizer Agent (NEW)
    │      - Reads ALL experiments, progress, methods, criteria
    │      - Selects best method(s) — may be multiple for comprehensive analysis
    │      - Writes production-ready, standalone Python scripts to methods/
    │      - Outputs structured findings summary (JSON)
    │
    ├── 2. Report Agent (EXISTING)
    │      - Receives Finalizer's summary
    │      - Writes projectbook/final-report.md
    │      - Includes: question, all methods tried, progression, final findings,
    │        reproducibility section
    │
    ├── 3. Presentation Agent (EXISTING)
    │      - Receives Finalizer's summary
    │      - Writes projectbook/final-presentation/
    │      - Polished slides suitable for sharing
    │
    └── 4. README update
           - Definitive project summary with final findings

```

## Finalizer Agent Details

### What it reads
- `urika.toml` — project question, description, mode
- `criteria.json` — what success looks like
- `methods.json` — all methods tried with metrics
- `experiments/*/progress.json` — all runs across all experiments
- `experiments/*/labbook/` — observations, narratives
- `experiments/*/methods/*.py` — actual method code
- `experiments/*/artifacts/` — figures, outputs

### What it produces

#### 1. Final methods (multiple allowed)

Research often requires multiple complementary methods. The Finalizer selects methods that together tell the complete story:

- **Best predictor** — highest accuracy/R²/AUC for the primary metric
- **Best interpreter** — most interpretable model (e.g., logistic regression with clear coefficients)
- **Robustness check** — non-parametric or cross-validated approach
- **Subgroup analysis** — if relevant (e.g., effects by demographic group)

Each final method is written as a standalone Python script:

```
methods/
├── final_prediction_model.py        # best performing model
├── final_interpretive_analysis.py   # interpretable model with effect sizes
├── final_robustness_check.py        # sensitivity/robustness analysis
└── README.md                        # describes each method and when to use it
```

Each script is:
- **Standalone** — runnable without Urika (`python methods/final_prediction_model.py --data path/to/data.csv`)
- **Documented** — docstrings explain what it does, what it expects, what it outputs
- **Reproducible** — includes random seeds, package versions, data paths
- **Self-contained** — all imports, preprocessing, model fitting, evaluation in one file

#### 2. Structured findings summary (JSON)

The Finalizer outputs a `projectbook/findings.json` that the Report and Presentation agents consume:

```json
{
  "question": "Which factors predict depression severity?",
  "answer": "Sleep duration and social support are the strongest predictors...",
  "final_methods": [
    {
      "name": "gradient_boosted_classifier",
      "role": "primary_prediction",
      "script": "methods/final_prediction_model.py",
      "key_metrics": {"auc": 0.89, "accuracy": 0.84},
      "summary": "LightGBM with 15 features, LOSO cross-validation"
    },
    {
      "name": "logistic_regression_interpretive",
      "role": "interpretation",
      "script": "methods/final_interpretive_analysis.py",
      "key_metrics": {"auc": 0.82, "accuracy": 0.79},
      "summary": "Logistic regression revealing sleep (OR=2.3) and social support (OR=1.8) as top factors"
    }
  ],
  "experiments_summary": [
    {"id": "exp-001", "focus": "baseline models", "key_finding": "..."},
    {"id": "exp-002", "focus": "feature engineering", "key_finding": "..."}
  ],
  "criteria_status": {"met": true, "details": "AUC >= 0.85 achieved (0.89)"},
  "progression": "Started with baselines (exp-001), added feature engineering (exp-002)...",
  "limitations": ["Small sample size (n=500)", "Cross-sectional design"],
  "future_work": ["Longitudinal follow-up", "External validation dataset"]
}
```

#### 3. Final report (via Report Agent)

`projectbook/final-report.md` — comprehensive, structured for publication:

- **Abstract** — one paragraph summary
- **Introduction** — research question and context
- **Methods** — all approaches tried, why each was selected
- **Results** — key findings, metrics, figures
- **Discussion** — interpretation, limitations, comparison with prior work
- **Reproducibility** — exact steps to reproduce from scratch:
  ```
  1. Install Urika: pip install urika
  2. Clone this project
  3. Run: python methods/final_prediction_model.py --data data/dataset.csv
  4. Expected output: AUC = 0.89 ± 0.02
  ```
- **References** — papers from knowledge base that informed the analysis

#### 4. Final presentation (via Presentation Agent)

`projectbook/final-presentation/index.html` — polished reveal.js slides:

- Title slide with project name and question
- Methods overview (what was tried)
- Key results with figures
- Comparison across methods
- Conclusions and implications
- Next steps / future work

## Triggering the Finalizer

### Automatic (meta-orchestrator)
When the advisor says "no more experiments needed", the meta-orchestrator calls the Finalizer before returning:

```python
# In meta.py run_project()
if advisor_says_done:
    await finalize_project(project_dir, runner, on_progress, on_message)
    break
```

### Manual (CLI / REPL)

```bash
# CLI
urika finalize my-project

# REPL
/finalize
```

The command can be run multiple times — each run produces versioned outputs (using the existing `write_versioned()` pattern).

## Implementation Plan

### Step 1: Finalizer Agent role
- `src/urika/agents/roles/finalizer.py` — new agent role
- `src/urika/agents/roles/prompts/finalizer_system.md` — prompt
- Security: read access to entire project, write to `methods/` and `projectbook/`
- Max turns: 20 (needs to read many files and write substantial code)

### Step 2: Finalize orchestrator function
- `src/urika/orchestrator/finalize.py` — new module
- `finalize_project()` — calls Finalizer → Report → Presentation → README
- Passes Finalizer's findings.json to Report and Presentation agents

### Step 3: CLI + REPL commands
- `urika finalize [project]` — CLI command with Spinner
- `/finalize` — REPL command via `_run_single_agent` pattern

### Step 4: Meta-orchestrator integration
- In `meta.py`, call `finalize_project()` when advisor says done

### Step 5: Documentation
- Add to agent system doc (doc 06) — 11th agent role
- Add to CLI reference (doc 12) and REPL guide (doc 13)
- Add to running experiments doc (doc 04) — finalization step
- Update README agent count

## Decisions Made

1. **Report format:** Markdown with inline figures (`![caption](../artifacts/figure.png)`). No LaTeX for v0.1.

2. **Requirements:** Single `requirements.txt` at project root covering all final methods. Generated by scanning imports across all `methods/final_*.py` scripts.

3. **Reproduce scripts:** Both platforms:
   - `reproduce.sh` — Mac/Linux
   - `reproduce.bat` — Windows

   Each creates a venv, installs requirements, runs all final methods, and outputs results.

4. **Figures:** Both final report and final presentation must include figures from experiment artifacts. The Finalizer selects the most relevant figures across all experiments and copies them to `projectbook/figures/` for the report, and `projectbook/final-presentation/figures/` for slides.
