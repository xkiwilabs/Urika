# Finalizing Projects

After experiments are complete, finalization consolidates the best results into polished, standalone deliverables: production-ready method scripts, structured findings, reproducibility artifacts, a final report, and a final presentation.


## What finalization does

Finalization takes everything learned across all experiments and produces outputs that can be shared, published, or handed off to other researchers -- without requiring Urika to be installed. The finalization sequence runs four steps in order:

1. **Finalizer Agent** -- reads all experiments, selects the best methods, writes standalone Python scripts, generates structured findings and reproducibility artifacts
2. **Report Agent** -- reads the findings and writes a comprehensive final report
3. **Presentation Agent** -- reads the findings and creates a final reveal.js presentation
4. **README update** -- updates the project README with the final findings summary


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

### From the REPL

```
urika:my-project> /finalize
```

Both commands run the full finalization sequence.


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


## Output file summary

| File | Description |
|------|-------------|
| `methods/final_*.py` | Standalone Python scripts for each final method |
| `methods/README.md` | Description of each method, usage, and metrics |
| `requirements.txt` | Python package dependencies |
| `reproduce.sh` | Reproduction script for Linux/macOS |
| `reproduce.bat` | Reproduction script for Windows |
| `projectbook/findings.json` | Structured findings summary (JSON) |
| `projectbook/figures/` | Best figures from experiments |
| `projectbook/final-report.md` | Comprehensive final report (markdown) |
| `projectbook/final-presentation/` | Final reveal.js presentation |
| `README.md` | Updated project README with findings |

---

**Next:** [Agent System](09-agent-system.md)
