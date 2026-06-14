# Finalizing Projects

After experiments are complete, finalization consolidates the best results into polished, standalone deliverables: production-ready method scripts, structured findings, reproducibility artifacts, a final report, and a final presentation.


## What finalization does

Finalization takes everything learned across all experiments and produces outputs that can be shared, published, or handed off to other researchers -- without requiring Urika to be installed. The finalization sequence runs four steps in order:

1. **Finalizer Agent** -- reads all experiments, selects the best methods, writes standalone Python scripts, generates structured findings and reproducibility artifacts
2. **Report Agent** -- reads the findings and writes a comprehensive final report
3. **Presentation Agent** -- reads the findings and creates a final reveal.js presentation
4. **README update** -- updates the project README with the final findings summary

Between steps 1 and 2, a **deterministic artifacts** step (pure code, no agent call, no API cost) generates per-method model cards, the `projectbook/METRICS.md` metrics glossary, and the `projectbook/reproduce.ipynb` Jupyter notebook from the findings the Finalizer just wrote. These generators only render data that exists on disk -- they never invent content -- and a failure in any of them never blocks the rest of the sequence.


## When to finalize

Finalize when you are satisfied with the experimental results and want to produce deliverables. Common scenarios:

- All success criteria have been met and you want polished outputs
- You have explored enough methods and want to consolidate the best ones
- You need to share results with colleagues or include them in a publication
- You want standalone, reproducible scripts that work without Urika

Autonomous mode can also trigger finalization automatically when all experiments complete and criteria are fully satisfied.


## How to trigger finalization

### From the CLI

```bash
urika finalize my-project
```

### From the TUI

```
urika:my-project> /finalize
```

Both commands run the full finalization sequence.

### Exporting the final report to LaTeX or PDF

```bash
urika finalize my-project --format latex
urika finalize my-project --format pdf
```

`--format latex|pdf` runs the normal markdown flow first, then converts the written `projectbook/final-report.md` (or `projectbook/draft/report.md` under `--draft`) with pandoc -- the agents stay format-agnostic and the markdown is always written and kept. Requires the `export` extra (`pip install 'urika[export]'`) plus a `pandoc` binary; PDF additionally needs a LaTeX engine. The same flag exists on `urika report` and the `/report` and `/finalize` slash commands. See [CLI: Agents](16d-cli-agents.md#urika-finalize) for the exact requirements and error messages.


## What finalization produces

### Final methods (`methods/`)

The Finalizer Agent selects the best methods from across all experiments and writes each as a standalone Python script. Research often needs multiple complementary methods that together tell the complete story:

- **Best predictor** -- highest accuracy, R-squared, or AUC for the primary metric
- **Best interpreter** -- most interpretable model (e.g., logistic regression with clear coefficients)
- **Robustness check** -- non-parametric or cross-validated approach
- **Subgroup analysis** -- if relevant to the research question

The agent selects 1--4 final methods depending on what the data and research question warrant.

Each script is:

- **Standalone** -- runnable with `python methods/final_<name>.py --data <path>` without Urika installed
- **Self-contained** -- all imports, preprocessing, model fitting, and evaluation in one file
- **Documented** -- module docstring explaining what it does, what it expects, and what it outputs
- **Reproducible** -- includes random seeds and package version comments
- **Parameterized** -- uses `argparse` for the `--data` argument

### Methods README (`methods/README.md`)

Describes each final method: its role (prediction, interpretation, robustness), when to use it, expected inputs and outputs, and key metrics achieved.

### Model cards (`methods/<name>_model_card.md`)

One model card per final method, generated deterministically from artifacts the agents already wrote (findings.json, run records, the data profile, the project config). Each card documents:

- **Intended use** -- the research question and project mode
- **Training data** -- data paths plus rows/columns from the data profile
- **Metrics** -- key metrics from the run record matched by `run_id`, including confidence intervals where the run recorded them
- **Assumptions and caveats** -- from the evaluator's `assumptions_detail` in the experiment's persisted evaluation (`experiments/<id>/labbook/evaluation.json`, written by the orchestrator loop each time an evaluation parses), falling back to the `limitations` in findings.json
- **Known limitations** -- from findings.json

Sections without recorded data render "Not recorded for this run." -- the generator never invents content. When the project audience is `novice`, each card also includes the plain-language method explainer.

### Metrics glossary (`projectbook/METRICS.md`)

A plain-language glossary covering every metric name observed across the project's runs: what the metric means, its range, how to read it, the ranking direction, and the observed range and best value across runs (with confidence intervals where recorded). Built-in entries cover ~15 common metrics (R², RMSE, MAE, accuracy, precision, recall, F1, AUC, p-value, Cohen's d, ...) with alias and suffix matching; unknown metrics are listed as project-specific with their observed values.

### Requirements (`requirements.txt`)

Lists all Python packages needed to run the final method scripts, scanned from the actual imports in the code.

### Reproduce scripts (`reproduce.sh` and `reproduce.bat`)

Shell scripts that set up a fresh virtual environment, install dependencies, and run all final methods. These let anyone reproduce the analysis from scratch on Linux/macOS (`reproduce.sh`) or Windows (`reproduce.bat`):

```bash
# On Linux/macOS
chmod +x reproduce.sh
./reproduce.sh

# On Windows
reproduce.bat
```

### Findings (`projectbook/findings.json`)

A structured JSON summary that the Report and Presentation agents consume. Contains:

- The research question and a plain-text answer
- Final methods with roles, scripts, key metrics, and summaries
- Per-experiment summaries with focus and key findings
- Criteria status (met or not, with details)
- Research progression narrative
- Limitations and future work suggestions
- References to selected figures

### Figures (`projectbook/figures/`)

The best figures from across all experiments, copied into a single directory for use in the final report and presentation.

### Final report (`projectbook/final-report.md`)

A comprehensive markdown report written by the Report Agent from findings.json. Structured as: Abstract, Introduction, Methods, Results, Discussion, Reproducibility, and References. Includes inline figures from `projectbook/figures/`.

### Final presentation (`projectbook/final-presentation/`)

A reveal.js slide deck created by the Presentation Agent from findings.json. This is the definitive project presentation for sharing with colleagues. Rendered as `index.html` that can be opened directly in a browser.


## Standalone scripts and reproducibility

A key design goal of finalization is that the outputs work without Urika. The final method scripts are plain Python with standard library and common scientific packages. The reproduce scripts create an isolated virtual environment and install only what is needed:

```bash
#!/bin/bash
set -e
python -m venv .reproduce-env
source .reproduce-env/bin/activate
pip install -r requirements.txt
echo "Running final methods..."
python methods/final_prediction_model.py --data data/scores.csv
python methods/final_interpretive_analysis.py --data data/scores.csv
```

This means anyone with Python installed can reproduce the analysis, regardless of whether they have Urika or access to the same AI models.

### Reproduce notebook (`projectbook/reproduce.ipynb`)

A Jupyter notebook assembled by pure code from the finalization artifacts: a title cell with the research question and answer, a setup cell, and one markdown-plus-code section per final method embedding the **literal contents** of its standalone script (if a script is missing on disk, the notebook notes it instead of inventing code). Each method section quotes the key metrics, including confidence intervals where the run recorded them, and a closing cell points at `METRICS.md` and the model cards. The notebook is validated with `nbformat.validate` before writing. Run it from the project root so the relative data paths inside the method scripts resolve.


## Output file summary

| File | Description |
|------|-------------|
| `methods/final_*.py` | Standalone Python scripts for each final method |
| `methods/README.md` | Description of each method, usage, and metrics |
| `methods/<name>_model_card.md` | Model card per final method (deterministic, v0.9.0+) |
| `requirements.txt` | Python package dependencies |
| `reproduce.sh` | Reproduction script for Linux/macOS |
| `reproduce.bat` | Reproduction script for Windows |
| `projectbook/findings.json` | Structured findings summary (JSON) |
| `projectbook/figures/` | Best figures from experiments |
| `projectbook/final-report.md` | Comprehensive final report (markdown) |
| `projectbook/final-report.tex` / `.pdf` | LaTeX/PDF export of the final report (only with `--format latex|pdf`) |
| `projectbook/METRICS.md` | Plain-language metrics glossary (deterministic, v0.9.0+) |
| `projectbook/reproduce.ipynb` | Jupyter reproduce notebook (deterministic, v0.9.0+) |
| `projectbook/final-presentation/` | Final reveal.js presentation |
| `README.md` | Updated project README with findings |

## Where each artifact is viewable

Every artifact lands as a file on disk under the project directory, so the CLI surface is always "open the file." The dashboard additionally renders most of them as browsable cards in the **Final outputs** section of the project home page (the cards appear once the corresponding file exists):

| Artifact | On disk (CLI) | Dashboard view |
|----------|---------------|----------------|
| Findings | `projectbook/findings.json` | **Findings** card → `/projects/<n>/findings` |
| Final report | `projectbook/final-report.md` | **Report** card → `/projects/<n>/projectbook/report` |
| Final presentation | `projectbook/final-presentation/index.html` | **Presentation** card → `/projects/<n>/projectbook/presentation` |
| Metrics glossary | `projectbook/METRICS.md` | **Metrics glossary** card → `/projects/<n>/projectbook/metrics` |
| Model cards | `methods/<name>_model_card.md` | **Model cards** card → `/projects/<n>/model-cards` |
| Reproduce notebook | `projectbook/reproduce.ipynb` | **Reproduce notebook** card → `/projects/<n>/projectbook/reproduce.ipynb` (downloads the `.ipynb`) |
| Methods + README | `methods/`, `methods/README.md` | (open the files on disk) |
| Reproduce scripts | `reproduce.sh`, `reproduce.bat`, `requirements.txt` | (open the files on disk) |

Per-experiment evaluation detail (the evaluator's assumption checks that feed the model cards) is viewable at `/projects/<n>/experiments/<exp_id>/evaluation` from each experiment page, reading `experiments/<exp_id>/labbook/evaluation.json`.

LaTeX/PDF report exports (`projectbook/final-report.tex` / `.pdf`) are produced only with `--format latex|pdf` and are not surfaced as dashboard cards — open them on disk.


## Interim Summaries (Draft Mode)

Draft mode runs the same finalization pipeline but frames everything as an interim progress summary rather than final deliverables. Outputs go to `projectbook/draft/` so they never overwrite the real final outputs.

### What it does

The `--draft` flag modifies each step of the pipeline:

1. **Finalizer Agent** -- reads all completed experiments and writes a draft findings summary to `projectbook/draft/findings.json` with summary figures in `projectbook/draft/figures/`. Does **not** write standalone method scripts, `requirements.txt`, or reproduce scripts.
2. **Report Agent** -- reads the draft findings and writes an interim progress report to `projectbook/draft/report.md`. Structured as: Summary of Progress, Methods Explored, Current Best Results, Open Questions, Next Steps.
3. **Presentation Agent** -- reads the draft findings and creates a progress presentation in `projectbook/draft/presentation/`.
4. **README update** -- skipped entirely in draft mode.

### When to use it

- Mid-project review: see where things stand without waiting for all experiments to finish
- Sharing progress with colleagues or supervisors before the work is complete
- Checking whether the project is heading in the right direction
- Generating figures and summaries for interim meetings or reports

Draft mode can run at any time, including while experiments are still in progress. Running a draft does not prevent you from running more experiments afterward.

### How to run

From the CLI:

```bash
urika finalize my-project --draft
urika finalize my-project --draft --audience novice
urika finalize my-project --draft --instructions "focus on the baseline results"
```

From the TUI:

```
urika:my-project> /finalize --draft
urika:my-project> /finalize --draft focus on preliminary findings
```

### What it skips

| Skipped in draft mode | Why |
|----------------------|-----|
| Standalone method scripts (`methods/final_*.py`) | Not meaningful until methods are finalized |
| `requirements.txt` | Tied to standalone scripts |
| `reproduce.sh` / `reproduce.bat` | Tied to standalone scripts |
| Model cards, `METRICS.md`, `reproduce.ipynb` | Tied to final methods, which don't exist yet |
| `README.md` update | The project is not finished yet |

### Draft output summary

| File | Description |
|------|-------------|
| `projectbook/draft/findings.json` | Interim findings summary (JSON) |
| `projectbook/draft/figures/` | Summary figures |
| `projectbook/draft/report.md` | Progress report (markdown) |
| `projectbook/draft/presentation/` | Progress presentation (reveal.js) |

## From the dashboard

The project home page has a **Finalize project** button that runs the same sequence as `urika finalize`. It opens a small modal with the same flags exposed by the CLI — additional instructions, an **Audience** picker, a **Report format** picker (`markdown` / `latex` / `pdf`, matching `--format`), and the `--draft` toggle — then posts to the finalize endpoint and HTMX-redirects you to `/projects/<n>/finalize/log`. Choosing `latex` or `pdf` requires the `urika[export]` extra plus pandoc in the dashboard server's environment (pdf also needs a TeX engine); if it's missing, the export error surfaces in the streamed finalize log.

The log page streams the running finalize subprocess via Server-Sent Events, with each agent's output appearing as it's produced (Finalizer → Report → Presentation → README updater). When the subprocess completes, the page emits a `status: completed` SSE event and links you straight to the rendered final report and presentation viewers.

See [Dashboard](18a-dashboard-pages.md) for the modal options and SSE log walkthrough.

---

**Next:** [Knowledge Pipeline](10-knowledge-pipeline.md)
