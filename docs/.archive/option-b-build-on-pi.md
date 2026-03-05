# Urika on Pi: PRD & Implementation Plan

## Option B — Build Urika as a Pi Package/Extension

---

## 1. Overview

### What This Option Is

Urika is built as a package on top of the Pi coding agent (`@mariozechner/pi-coding-agent`). Pi provides the agent runtime: the LLM loop, tool dispatch, session management, and extension system. Urika provides everything domain-specific: multi-agent orchestration, security boundaries, the Python analysis framework, investigation semantics, and knowledge pipeline.

The key insight that distinguishes this revision from the previous version: **Urika's agents ARE coding agents.** They write Python scripts that load datasets, fit models, compute metrics, generate plots, and write JSON result summaries. They run those scripts via bash. Pi's core tools — `read`, `write`, `edit`, `bash`, `grep`, `find` — are exactly what these agents need. The agent runtime does not need to "understand" scientific analysis. It needs to let agents write and run Python code effectively.

This means there is **no TypeScript-Python bridge** for analysis. Agents write Python files that `import urika` and execute them via `bash`. The previous version's JSON-RPC bridge was solving a problem that does not exist. The only TypeScript in Urika is: the orchestration extension, security hooks, custom Pi commands (`/investigate`, `/evaluate`, `/status`), and session metadata tracking.

### The Split-Stack Tradeoff

Option B introduces a split-stack architecture: **TypeScript for orchestration + Python for analysis**. This means two languages, two package managers (npm + pip/uv), two test frameworks (vitest + pytest), two build systems, and two sets of tooling conventions. For a project whose core domain is scientific Python, this is a meaningful friction point.

Contributors who want to modify orchestration logic, security boundaries, or CLI commands must work in TypeScript. Contributors who want to add analysis methods, metrics, or data loaders work in Python. These are different skill sets, different ecosystems, and different debugging workflows. The split also means two CI pipelines, two dependency update streams, and two places where things can break independently.

This tradeoff is justified if Pi's runtime provides enough value to offset the friction. The 10 components Pi gives for free (agent loop, 15+ LLM providers, tool dispatch, session persistence, etc.) represent significant engineering effort. But the friction is real, and it is worth acknowledging: Urika is fundamentally a scientific Python project, and Option B asks some of its development to happen in a language that is not Python.

### What Pi Provides (For Free)

| Capability | What It Is | Why Urika Needs It |
|---|---|---|
| **Agent loop** | Prompt -> response -> tool dispatch -> repeat | The fundamental loop every agent runs, regardless of domain |
| **15+ LLM providers** | Claude, GPT, Gemini, Mistral, local models, etc. | Model-agnostic from day one; use Opus for strategy, Sonnet for routine work, cheap models for profiling |
| **SDK mode** (`createAgentSession()`) | Programmatic agent creation and management | Orchestrator spawns each agent as a session with specific tools/prompts/model |
| **Built-in tools** | `read`, `write`, `edit`, `bash`, `grep`, `find` | Exactly what analysis agents need to write and run Python scripts |
| **Extension system** | `pi.registerTool()`, `pi.on()`, event hooks | Register Urika commands, enforce security via `tool_call` hooks |
| **Tree-structured JSONL sessions** | Branching conversation history with compaction | Useful for forking analysis paths; each branch = a different analytical approach |
| **Skills system** | SKILL.md distributable prompt templates | Package domain-specific analytical reasoning as reusable skills |
| **Pi packages** | npm/git installable bundles | Distribute Urika as `pi install npm:@urika/pi-urika` |
| **TUI** | Terminal interface with streaming, syntax highlighting | Interactive investigation setup and monitoring |
| **Token management** | Context compaction, token counting, cost estimation | Prevent runaway LLM costs in multi-agent loops |

### What Urika Must Build (The Real Gaps)

Pi is a general-purpose coding agent. It does not know about experiments, evaluation metrics, method registries, or scientific integrity. The five things Urika must add:

**1. Multi-agent orchestration.** Pi runs one agent at a time. Urika sequences orchestrator -> task agent -> evaluator -> suggestion agent -> tool builder in a loop, with each agent having a distinct role, system prompt, model, and security boundary. This is a TypeScript extension that uses Pi's SDK to spawn and manage sessions.

**2. Security boundaries.** The evaluator agent must not be able to write to `methods/`. Task agents must not modify evaluation criteria. Tool builders must not alter leaderboard results. Pi provides `tool_call` event hooks that Urika uses to intercept and block unauthorized filesystem operations per agent role.

**3. Investigation framework (Python package).** The big piece. A pip-installable Python package (`urika`) that agent-written scripts import. Contains: data loading, method base classes, method registry, evaluation runner, metrics library, criteria validation, leaderboard management, knowledge indexing, session tracking, built-in methods, built-in tools (as importable modules), visualization helpers. Agents write `from urika.evaluation import run_evaluation` in their scripts and run them via bash.

**4. Knowledge pipeline.** PDF text and table extraction, literature search, knowledge indexing. Agents need to ingest papers and reference domain knowledge when choosing analytical approaches.

**5. Session semantics.** Pi's sessions track conversations. Urika needs to track experiments: runs, metrics, hypotheses, method comparisons, leaderboard rankings, criteria pass/fail status. This is a thin metadata layer on top of Pi's sessions, stored in the investigation's filesystem.

### What This Is NOT

This is not a TypeScript-Python bridge architecture. The previous version of this document designed a JSON-RPC stdio bridge where TypeScript tools serialized requests to a persistent Python subprocess. That was wrong. It overstated the gap between "coding agents" and "analysis agents."

The correction: agents run Python code the same way a human developer would. They write a `.py` file, run it with `python script.py`, read the output. The `urika` Python package gives their scripts a rich library to import, but the execution model is just bash. No serialization boundaries, no subprocess management, no bridge health checks.

---

## 2. Architecture

### 2.1 System Layers

```
+-----------------------------------------------------------------------+
|                            User / CLI                                  |
|   $ pi --package @urika/pi-urika                                      |
|   /investigate    /evaluate    /status    /leaderboard                 |
+----------------------------------+------------------------------------+
                                   |
+----------------------------------v------------------------------------+
|                     Urika Orchestrator Extension                       |
|                   (TypeScript — uses Pi SDK)                           |
|                                                                        |
|   Spawns and sequences agent sessions:                                 |
|                                                                        |
|   +------------+  +------------+  +------------+  +---------------+    |
|   |   Task     |  | Evaluator  |  | Suggestion |  | Tool Builder  |    |
|   |   Agent    |  |   Agent    |  |   Agent    |  |    Agent      |    |
|   | (Pi SDK    |  | (Pi SDK    |  | (Pi SDK    |  | (Pi SDK       |    |
|   |  session)  |  |  session)  |  |  session)  |  |  session)     |    |
|   +-----+------+  +-----+------+  +-----+------+  +------+--------+    |
|         |              |               |                |               |
|         |    Each agent writes and runs Python scripts  |               |
|         |    using Pi's bash/write/read/edit tools       |               |
|         |                                                |               |
+---------|------------------------------------------------|---------------+
          |                                                |
+---------v------------------------------------------------v---------------+
|                Investigation Workspace (Filesystem)                       |
|                                                                           |
|   urika.toml                  methods/          results/                  |
|   config/                     tools/            knowledge/                |
|   data/                                                                   |
|                                                                           |
|   Agent scripts import from the urika Python package:                     |
|   from urika.data import load_dataset                                     |
|   from urika.evaluation import run_evaluation, check_criteria             |
|   from urika.methods import list_methods, get_method                      |
|   from urika.metrics import compute_metrics                               |
|   from urika.leaderboard import update_leaderboard                        |
|   from urika.knowledge import search_knowledge, ingest_pdf                |
|                                                                           |
+---------------------------------------------------------------------------+
          |
+---------v----------------------------------------------------------------+
|                  urika Python Package (pip install urika)                 |
|                                                                           |
|   numpy, scipy, pandas, scikit-learn, statsmodels, pingouin,              |
|   matplotlib, seaborn, pymupdf                                            |
+---------------------------------------------------------------------------+
```

### 2.2 How Agents Work

Each Urika agent is a `createAgentSession()` call with a specific system prompt, model, tool set, and (via hooks) security constraints. The agent enters Pi's standard loop: receive prompt, reason, call tools, repeat. The tools it calls are Pi's built-in tools: `write` to create Python scripts, `bash` to run them, `read` to inspect results.

**What a task agent actually does, concretely:**

1. Reads the investigation config (`urika.toml`) and current suggestions (`results/suggestions/*.json`)
2. Writes a Python script like:

```python
#!/usr/bin/env python3
"""Try ridge regression on the survey data."""
from urika.data import load_dataset
from urika.methods.builtin.regression import RidgeRegression
from urika.evaluation import run_evaluation
from urika.leaderboard import update_leaderboard

dataset = load_dataset("data/survey_responses.csv", target="satisfaction")
method = RidgeRegression(alpha=1.0)
result = run_evaluation(method, dataset, metrics=["r2", "rmse", "mae"])

update_leaderboard(
    investigation_root=".",
    method_name="ridge_regression",
    params={"alpha": 1.0},
    metrics=result.metrics,
    run_id=result.run_id,
    primary_metric="r2",
    direction="higher_is_better",
)

print(result.summary())
```

3. Runs the script via bash: `python3 scripts/run_ridge.py`
4. Reads the output and any generated files (plots, JSON results)
5. Updates `results/sessions/<id>/progress.json` with the run record
6. Decides what to try next based on results and available suggestions

The agent does not call a special `run_analysis` tool that bridges to Python. It writes and runs code, exactly as a human data scientist would. The `urika` package provides the library functions that make this efficient.

### 2.3 Orchestration

The orchestrator is a TypeScript extension that uses Pi's SDK. It is NOT an LLM agent — it runs a deterministic control loop:

```
ORCHESTRATOR CONTROL LOOP
=========================

1. Load investigation config (urika.toml)
2. Create or resume session
3. Read current state (progress.json, leaderboard.json)

LOOP (until criteria met OR max turns OR user stop):

    4. Spawn Task Agent session
       - System prompt includes: investigation config, available methods,
         current suggestions, current best results
       - Tools: read, write, edit, bash, grep, find
       - Model: configurable (default Sonnet for cost-efficiency)
       - Agent explores data, writes and runs analysis scripts,
         records progress
       - Terminates after N turns or self-reports done

    5. Spawn Evaluator session
       - System prompt includes: success criteria, latest progress,
         method outputs
       - Tools: read, bash (restricted — no writes via redirect/tee/mv/cp/rm)
       - Model: Sonnet
       - Agent reads method outputs, runs evaluation scripts that call
         urika.evaluation, validates claimed metrics independently,
         writes to leaderboard
       - Checks: criteria met?

    6. IF criteria met -> EXIT with success report

    7. Spawn Suggestion Agent session
       - System prompt includes: all results, leaderboard, methods tried,
         knowledge base
       - Tools: read, bash (restricted), write (results/suggestions/ only)
       - Model: Opus (needs strategic reasoning)
       - Agent analyzes what worked and what did not, searches literature,
         writes prioritized suggestions for next round

    8. IF tool_request in suggestions:
         Spawn Tool Builder session
         - Tools: read, write, bash, edit
         - Writes to: tools/, tools_registry.json
         - Reads tool requests, creates Python tools, tests them, registers

    9. Update session metadata, increment turn counter

10. Generate final report
```

### 2.4 Security Enforcement via Pi's Event Hooks

Pi emits a `tool_call` event before executing any tool. Urika's extension intercepts this event and enforces per-agent filesystem boundaries:

```typescript
// Security enforcement in the Urika extension
function createSecurityHook(agentRole: AgentRole) {
  return async (event: ToolCallEvent) => {
    // Intercept write/edit operations
    if (event.toolName === "write" || event.toolName === "edit") {
      const targetPath = event.params.filePath;
      if (!isPathAllowed(targetPath, agentRole, "write")) {
        return {
          blocked: true,
          result: `BLOCKED: ${agentRole} cannot write to ${targetPath}. ` +
                  `Writable paths: ${getWritablePaths(agentRole).join(", ")}`,
        };
      }
    }

    // Intercept bash commands for restricted agents
    if (event.toolName === "bash" && isRestrictedBash(agentRole)) {
      const command = event.params.command;
      if (containsMutatingOperation(command)) {
        return {
          blocked: true,
          result: `BLOCKED: ${agentRole} cannot run mutating bash commands. ` +
                  `Rejected: ${command}`,
        };
      }
    }
  };
}
```

**Per-agent boundaries:**

| Agent | Can Write To | Cannot Write To | Bash Restrictions |
|---|---|---|---|
| **Task Agent** | `methods/`, `results/sessions/<id>/`, `scripts/` | `evaluation/`, `config/`, `results/leaderboard.json` | None (full bash) |
| **Evaluator** | `results/leaderboard.json`, `results/sessions/<id>/evaluation/` | `methods/`, `tools/`, `config/` | No `>`, `>>`, `tee`, `mv`, `cp`, `rm`, `dd` |
| **Suggestion Agent** | `results/suggestions/` | Everything else | No mutating operations |
| **Tool Builder** | `tools/`, `tools_registry.json` | `methods/`, `results/`, `config/` | None (full bash, needs to test tools) |

### 2.5 The Python Analysis Framework

This is described fully in section 4. The critical architectural point: it is a regular pip-installable Python package. It is NOT a bridge, NOT a subprocess protocol, NOT a TypeScript wrapper. Agents write Python scripts that `import urika` and run them via bash. The package provides:

- Data loading and profiling
- Method base classes and registry
- Evaluation runner and metrics library
- Criteria validation
- Leaderboard management
- Knowledge indexing and search
- Session tracking helpers
- Built-in methods (regression, classification, hypothesis tests, etc.)
- Built-in tools (data profiler, correlation analysis, visualization)
- Visualization helpers

### 2.6 Investigation Modes

All three modes use the same agent architecture and the same Python package. The differences are in orchestrator behavior, system prompts, and evaluator configuration:

**Exploratory mode** (default): Optimize one or more metrics. No pre-registration. The suggestion agent can recommend any direction. The leaderboard ranks all methods tried. Success = metric threshold reached or turn limit exhausted with best-effort results.

**Confirmatory mode**: Pre-specified hypothesis and analysis plan. Guardrails enforce:
- Analysis plan locked after registration (`config/analysis_plan.json`, read-only to all agents)
- Task agents cannot change the primary metric or test
- Evaluator flags deviations from the registered plan
- Multiple comparisons corrections enforced
- Suggestion agent restricted to sensitivity analyses
- `confirmatory_audit.json` records every decision point
- No leaderboard (prevents cherry-picking)

**Pipeline mode**: Ordered preprocessing stages (e.g., filtering -> artifact rejection -> epoching -> feature extraction -> modelling). Each stage has defined inputs and outputs. Task agents work one stage at a time. The orchestrator advances stages only when the evaluator approves the current stage's outputs. Essential for EEG, motor control, and wearable sensor data.

### 2.7 Session and Experiment Tracking

Pi sessions track conversations. Urika's experiment tracking is filesystem-based, managed by the Python package and written to by agents:

```
results/
    sessions/
        session_001/
            session.json              # metadata: start time, status, config snapshot
            progress.json             # run-by-run tracking (agents write, all read)
            evaluation/
                metrics.json          # evaluator output
                criteria_check.json   # pass/fail per criterion
            runs/
                run_001.json          # individual experiment results
                run_002.json
            scripts/                  # agent-written analysis scripts (auditable)
                run_ridge.py
                run_xgboost.py
        session_002/
            ...
    leaderboard.json                  # global method rankings
    suggestions/                      # cross-session suggestions
        suggestion_001.json
```

Pi's tree-structured JSONL sessions provide conversation history and branching. Urika's filesystem JSON provides experiment semantics: runs, metrics, hypotheses, method comparisons. The two are complementary, not redundant.

---

## 3. What Urika Develops vs What Pi Provides

### Complete Component Breakdown

| Component | Provider | Description |
|---|---|---|
| **Agent loop** (prompt -> tools -> repeat) | Pi | Core agent execution cycle |
| **LLM provider abstraction** (15+ providers) | Pi | Model selection, auth, retry, token counting |
| **Built-in tools** (read, write, edit, bash, grep, find) | Pi | Filesystem and shell access for agents |
| **Session persistence** (JSONL with branching) | Pi | Conversation history, compaction, resumption |
| **Extension system** (tool registration, event hooks) | Pi | Platform for Urika's orchestration and security |
| **Skills system** (SKILL.md templates) | Pi | Distribution mechanism for domain-specific prompts |
| **Package distribution** (npm install) | Pi | `pi install npm:@urika/pi-urika` |
| **TUI** (terminal interface) | Pi | Interactive sessions, streaming output |
| **Context compaction** | Pi | Automatic context management for long sessions |
| **Multi-agent orchestration** | **Urika extension** (TS) | Sequencing task -> evaluator -> suggestion -> tool builder |
| **Security boundaries** | **Urika extension** (TS) | Per-agent write restrictions via tool_call hooks |
| **Custom commands** (/investigate, /evaluate, /status) | **Urika extension** (TS) | Investigation lifecycle management |
| **Agent factory** (session creation per role) | **Urika extension** (TS) | Configured createAgentSession() per agent type |
| **Session metadata** (experiment tracking) | **Urika extension** (TS) | Thin layer mapping experiments to Pi sessions |
| **Investigation mode logic** | **Urika extension** (TS) | Exploratory/confirmatory/pipeline mode behavior |
| **Agent system prompts** | **Urika prompts** (MD) | Role-specific instructions per agent type |
| **Domain skills** | **Urika skills** (MD) | Analytical reasoning templates per domain |
| **Data loading and profiling** | **Urika Python package** | CSV, Parquet, JSON, HDF5, EDF, C3D, etc. |
| **Method base classes and registry** | **Urika Python package** | IAnalysisMethod, discover_methods() |
| **Built-in analysis methods** | **Urika Python package** | Regression, classification, hypothesis tests, etc. |
| **Evaluation runner** | **Urika Python package** | Run method, compute metrics, validate criteria |
| **Metrics library** | **Urika Python package** | R2, RMSE, AUC, Cohen's d, ICC, AIC, BIC, etc. |
| **Criteria validation** | **Urika Python package** | Check metrics against success thresholds |
| **Leaderboard management** | **Urika Python package** | Ranked results across sessions |
| **Built-in tools** (profiler, correlations, viz) | **Urika Python package** | Importable analysis utilities |
| **Knowledge pipeline** (PDF, literature, indexing) | **Urika Python package** | Document ingestion, search, knowledge base |
| **Guardrails** (p-hacking prevention) | **Urika Python package** | Confirmatory mode enforcement |
| **Visualization helpers** | **Urika Python package** | Matplotlib/seaborn plot generation |
| **Session tracking helpers** | **Urika Python package** | progress.json, run records, session lifecycle |

### Summary by Count

- **Pi provides**: 10 components (all infrastructure/runtime)
- **Urika TypeScript extension**: 6 components (orchestration, security, commands)
- **Urika prompts/skills**: 2 components (agent instructions)
- **Urika Python package**: 13 components (all domain/analysis logic)

The TypeScript surface area is small and focused: orchestration, security hooks, commands, and session metadata. Everything analytical is Python.

---

## 4. The Python Analysis Framework

This is the largest piece of work Urika must build. It is a pip-installable package (`urika`) that agents' scripts import. It is a library, not a server, not a bridge, not a framework with its own event loop.

### 4.1 Design Philosophy

Agents write Python scripts. Those scripts import `urika` modules the same way a data scientist imports pandas or scikit-learn. The package provides convenience functions, base classes, registries, and evaluation infrastructure. It does not provide an agent runtime, LLM calls, or tool dispatch — that is Pi's job.

Example of what an agent-written script looks like:

```python
#!/usr/bin/env python3
"""Exploratory analysis: try multiple regression approaches."""
import json
from urika.data import load_dataset, profile_dataset
from urika.methods.builtin.regression import (
    OLSRegression, RidgeRegression, LassoRegression, ElasticNetRegression
)
from urika.evaluation import run_evaluation
from urika.leaderboard import update_leaderboard
from urika.session import record_run

# Load and profile
dataset = load_dataset("data/survey_responses.csv", target="satisfaction")
profile = profile_dataset(dataset)
print(f"Dataset: {profile.n_rows} rows, {profile.n_cols} cols")
print(f"Missing: {profile.missing_summary}")

# Try each method
methods = [
    ("ols", OLSRegression()),
    ("ridge", RidgeRegression(alpha=1.0)),
    ("lasso", LassoRegression(alpha=0.1)),
    ("elasticnet", ElasticNetRegression(alpha=0.5, l1_ratio=0.5)),
]

for name, method in methods:
    result = run_evaluation(
        method=method,
        dataset=dataset,
        metrics=["r2", "rmse", "mae", "aic"],
        cv_folds=5,
    )

    update_leaderboard(
        investigation_root=".",
        method_name=name,
        params=method.get_params(),
        metrics=result.metrics,
        run_id=result.run_id,
        primary_metric="r2",
        direction="higher_is_better",
    )

    record_run(
        session_dir="results/sessions/session_001",
        run_id=result.run_id,
        method=name,
        params=method.get_params(),
        metrics=result.metrics,
        hypothesis=f"Test {name} as baseline regression approach",
        observation=f"R2={result.metrics['r2']:.3f}, RMSE={result.metrics['rmse']:.3f}",
    )

    print(f"{name}: R2={result.metrics['r2']:.3f}, RMSE={result.metrics['rmse']:.3f}")

# Print current leaderboard
from urika.leaderboard import load_leaderboard
lb = load_leaderboard(".")
print("\nLeaderboard:")
for rank, entry in enumerate(lb.entries, 1):
    print(f"  {rank}. {entry.method_name}: {entry.primary_metric_name}={entry.primary_metric_value:.3f}")
```

### 4.2 Package Structure

```
urika-python/                        # Python package root
    pyproject.toml                   # PEP 621, hatch build system
    LICENSE                          # MIT

    src/urika/
        __init__.py                  # Package version, top-level imports
        py.typed                     # PEP 561 marker

        # -- Data Layer -------------------------------------------------------
        data/
            __init__.py              # Re-exports: load_dataset, profile_dataset
            dataset.py               # DatasetSpec, DatasetView, DataSummary, ColumnSchema
            loader.py                # Unified loader with format auto-detection
            profiler.py              # Automated EDA: dtypes, distributions, missing, outliers
            schema.py                # Column role inference (target, feature, id, group, time)
            readers/
                __init__.py
                base.py              # IDataReader protocol
                tabular.py           # CSV, TSV, Excel, Parquet, SPSS (.sav), Stata (.dta)
                json_reader.py       # JSON, JSON Lines
                hdf5_reader.py       # HDF5, MAT v7.3 (optional: h5py)
                edf_reader.py        # EDF/EDF+/BDF (optional: mne or pyedflib)
                c3d_reader.py        # C3D motion capture (optional: ezc3d)
                imu_reader.py        # Axivity CWA, ActiGraph GT3X (optional: actipy)
                audio_reader.py      # WAV, MP3 (optional: librosa)
                bids_reader.py       # BIDS neuroimaging format (optional: mne-bids)

        # -- Method System ----------------------------------------------------
        methods/
            __init__.py              # Re-exports: list_methods, get_method, discover_methods
            base.py                  # IAnalysisMethod ABC, MethodResult dataclass
            registry.py              # MethodRegistry with auto-discovery from builtin/ + investigation methods/
            domain_bases.py          # ITabularMethod, ITimeSeriesMethod, IPipelineMethod

            builtin/
                __init__.py
                regression.py        # OLS, Ridge, Lasso, ElasticNet, PolynomialRegression
                classification.py    # LogisticRegression, RandomForest, SVM, KNN, XGBoost
                clustering.py        # KMeans, DBSCAN, AgglomerativeClustering, GaussianMixture
                hypothesis_tests.py  # t-test, paired t, ANOVA, mixed ANOVA, chi-squared,
                                     # Mann-Whitney, Kruskal-Wallis, Friedman
                factor_analysis.py   # PCA, EFA (factor_analyzer), CFA stubs (semopy)
                mixed_effects.py     # Linear mixed-effects models (statsmodels)
                time_series.py       # ARIMA, exponential smoothing, seasonal decomposition
                survival.py          # Kaplan-Meier, Cox regression (lifelines)
                nonparametric.py     # Kernel density, permutation tests, bootstrap

        # -- Evaluation System ------------------------------------------------
        evaluation/
            __init__.py              # Re-exports: run_evaluation, check_criteria
            runner.py                # run_evaluation(method, dataset, metrics, cv_folds) -> EvalResult
            metrics.py               # IMetric ABC, MetricRegistry, built-in metrics:
                                     #   R2, RMSE, MAE, MSE, accuracy, precision, recall, F1,
                                     #   AUC, log_loss, Cohen_d, eta_squared, ICC, AIC, BIC,
                                     #   Cronbach_alpha, CFI, RMSEA, SRMR
            criteria.py              # Criterion dataclass, validate_criteria(), load_criteria()
                                     #   Supports: min/max thresholds, report_only, stage-dependent
            leaderboard.py           # update_leaderboard(), load_leaderboard(), LeaderboardEntry
            cross_validation.py      # k-fold, stratified k-fold, leave-one-out, time-series split

        # -- Knowledge Pipeline -----------------------------------------------
        knowledge/
            __init__.py              # Re-exports: search_knowledge, ingest_pdf, ingest_paper
            pdf_extractor.py         # Text + table extraction via pymupdf
            literature.py            # Web search (Semantic Scholar, Google Scholar via scraping)
            indexer.py               # Knowledge base indexing (TF-IDF + optional embedding)
            index.py                 # KnowledgeIndex: add, search, list entries

        # -- Session Tracking -------------------------------------------------
        session/
            __init__.py              # Re-exports: record_run, load_progress, create_session
            manager.py               # Session lifecycle: create, resume, complete, fail
            progress.py              # progress.json read/write, run recording
            comparison.py            # Cross-session metric comparison
            report.py                # Generate Markdown summary reports

        # -- Built-in Tools ---------------------------------------------------
        # (Importable modules AND CLI-callable via python -m urika.tools.<name>)
        tools/
            __init__.py              # Re-exports
            base.py                  # ITool ABC with dual CLI + importable API
            registry.py              # ToolRegistry, load_tool_prefixes(), discover_tools()

            builtin/
                __init__.py
                data_profiler.py     # Automated EDA with summary statistics, distributions
                correlation.py       # Pearson, Spearman, partial correlation matrices
                hypothesis_tests.py  # Quick statistical tests (wraps methods/ but simpler API)
                visualization.py     # Plot generation: histogram, scatter, box, line, heatmap,
                                     #   residual plots, Q-Q plots, correlation heatmaps
                outlier_detection.py # IQR, Z-score, Mahalanobis, isolation forest
                missing_data.py      # Missing data analysis, imputation strategies
                feature_importance.py# Permutation importance, SHAP values, mutual information
                power_analysis.py    # Statistical power, sample size estimation
                normality.py         # Shapiro-Wilk, Anderson-Darling, Q-Q diagnostics
                effect_sizes.py      # Cohen's d, eta-squared, odds ratio, risk ratio

        # -- Guardrails -------------------------------------------------------
        guardrails/
            __init__.py
            confirmatory.py          # p-hacking prevention: plan locking, multiple comparisons,
                                     #   HARKing detection, decision audit logging
            validators.py            # Statistical validity: assumption checking, sample size,
                                     #   degrees of freedom, convergence checks

        # -- Pipeline Support -------------------------------------------------
        pipeline/
            __init__.py
            stage.py                 # PipelineStage ABC, StageResult
            pipeline.py              # Pipeline: ordered stage execution with validation
            builtin_stages/
                __init__.py
                filtering.py         # Signal filtering (bandpass, notch, etc.)
                artifact_rejection.py# Threshold-based, ICA-based artifact removal
                epoching.py          # Event-based segmentation
                feature_extraction.py# Domain-agnostic feature computation
                normalization.py     # Standardization, min-max, robust scaling

        # -- Configuration ----------------------------------------------------
        config/
            __init__.py
            investigation.py         # InvestigationConfig: load from urika.toml
            schemas.py               # Pydantic/dataclass schemas for all config types
```

### 4.3 Core Abstractions

**DatasetView** — What methods receive:

```python
@dataclass
class DatasetView:
    spec: DatasetSpec             # path, format, original schema
    data: dict[str, Any]          # named data arrays/frames (e.g., {"X": df, "y": series})
    metadata: dict[str, Any]      # sampling rates, channel info, subject grouping, etc.
    summary: DataSummary          # n_rows, n_cols, dtypes, missing counts, distributions
    column_schema: dict[str, ColumnSchema]  # per-column: role, dtype, measurement level

@dataclass
class ColumnSchema:
    name: str
    role: str                     # "target", "feature", "id", "group", "time", "weight"
    dtype: str                    # "numeric", "categorical", "ordinal", "datetime", "text"
    measurement_level: str        # "nominal", "ordinal", "interval", "ratio"
    missing_count: int
    unique_count: int
```

**IAnalysisMethod** — What methods implement:

```python
class IAnalysisMethod(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def category(self) -> str: ...         # "regression", "classification", "hypothesis_test", etc.

    @abstractmethod
    def default_params(self) -> dict: ...

    def set_params(self, params: dict) -> None: ...
    def get_params(self) -> dict: ...

    @abstractmethod
    def run(self, data: DatasetView, context: AnalysisContext) -> MethodResult: ...

@dataclass
class MethodResult:
    outputs: dict[str, Any]        # predictions, coefficients, factor loadings, etc.
    metrics: dict[str, float]      # computed quality metrics
    diagnostics: dict[str, Any]    # method-specific diagnostic info (residuals, convergence, etc.)
    artifacts: list[str]           # paths to generated files (plots, tables, saved models)
    valid: bool                    # whether execution completed successfully
    run_id: str                    # unique identifier for this run
    runtime_seconds: float         # wall-clock execution time
```

**Domain-specific base classes** — Typed APIs on top of IAnalysisMethod:

```python
class ITabularMethod(IAnalysisMethod):
    """For structured data (most common case)."""
    @abstractmethod
    def fit_predict(self, X: pd.DataFrame, y: pd.Series,
                    X_test: pd.DataFrame | None = None) -> MethodResult: ...

    def run(self, data: DatasetView, context: AnalysisContext) -> MethodResult:
        X, y = data.data["X"], data.data["y"]
        return self.fit_predict(X, y)


class ITimeSeriesMethod(IAnalysisMethod):
    """For temporal/signal data."""
    @abstractmethod
    def analyze(self, signals: np.ndarray, sampling_rate: float,
                events: pd.DataFrame | None = None) -> MethodResult: ...

    def run(self, data: DatasetView, context: AnalysisContext) -> MethodResult:
        return self.analyze(
            data.data["signals"],
            data.metadata["sampling_rate"],
            data.data.get("events"),
        )
```

**Evaluation runner** — The core evaluation function:

```python
def run_evaluation(
    method: IAnalysisMethod,
    dataset: DatasetView,
    metrics: list[str],
    cv_folds: int = 5,
    cv_strategy: str = "stratified_kfold",  # or "kfold", "loo", "timeseries"
    random_state: int = 42,
) -> EvalResult:
    """
    Run a method on a dataset, compute metrics via cross-validation,
    and return structured results.

    Agents call this from their scripts. It handles:
    - Cross-validation splitting
    - Running the method on each fold
    - Computing requested metrics
    - Aggregating results (mean +/- std across folds)
    - Generating diagnostic artifacts (residual plots, confusion matrices)
    - Timing execution
    """
    ...

@dataclass
class EvalResult:
    run_id: str
    method_name: str
    metrics: dict[str, float]          # aggregated (mean across folds)
    metrics_std: dict[str, float]      # standard deviation across folds
    fold_metrics: list[dict[str, float]]  # per-fold results
    method_result: MethodResult        # result from final full-data fit
    criteria_check: CriteriaResult | None  # if criteria provided
    artifacts: list[str]               # paths to generated files
    runtime_seconds: float

    def summary(self) -> str:
        """Human-readable summary string."""
        ...
```

**Criteria validation:**

```python
@dataclass
class Criterion:
    metric: str
    threshold: float
    comparison: str           # ">=", "<=", ">", "<", "=="
    description: str
    type: str = "threshold"   # "threshold" | "report_only"
    stage: str | None = None  # for pipeline mode: which stage this applies to

def validate_criteria(
    metrics: dict[str, float],
    criteria: list[Criterion],
) -> CriteriaResult:
    """
    Compare computed metrics against success criteria.
    Returns (all_passed, per_criterion_results).
    """
    ...

@dataclass
class CriteriaResult:
    all_passed: bool
    results: list[CriterionCheck]  # per-criterion pass/fail with actual vs threshold
```

**Leaderboard:**

```python
@dataclass
class LeaderboardEntry:
    method_name: str
    params: dict[str, Any]
    metrics: dict[str, float]
    run_id: str
    session_id: str
    timestamp: str
    primary_metric_name: str
    primary_metric_value: float
    rank: int

def update_leaderboard(
    investigation_root: str,
    method_name: str,
    params: dict,
    metrics: dict[str, float],
    run_id: str,
    primary_metric: str,
    direction: str,          # "higher_is_better" | "lower_is_better"
    session_id: str | None = None,
) -> LeaderboardEntry:
    """Add a result to the leaderboard and re-rank. Returns the new entry with rank."""
    ...

def load_leaderboard(investigation_root: str) -> Leaderboard:
    """Load the current leaderboard from results/leaderboard.json."""
    ...
```

### 4.4 Built-in Methods

Ship with the package, covering the most common analytical approaches:

| Category | Methods | Key Libraries |
|---|---|---|
| **Regression** | OLS, Ridge, Lasso, ElasticNet, Polynomial | scikit-learn, statsmodels |
| **Classification** | Logistic, Random Forest, SVM, KNN, XGBoost, Gradient Boosting | scikit-learn, xgboost |
| **Clustering** | K-Means, DBSCAN, Agglomerative, Gaussian Mixture | scikit-learn |
| **Hypothesis Tests** | t-test, paired t, Welch's t, ANOVA, mixed ANOVA, chi-squared, Mann-Whitney, Kruskal-Wallis, Friedman, Wilcoxon | scipy, pingouin |
| **Factor Analysis** | PCA, EFA, CFA stubs | scikit-learn, factor_analyzer, semopy |
| **Mixed Effects** | Linear mixed-effects, generalized mixed-effects | statsmodels |
| **Time Series** | ARIMA, exponential smoothing, seasonal decomposition | statsmodels |
| **Survival** | Kaplan-Meier, Cox proportional hazards | lifelines |
| **Nonparametric** | Kernel density estimation, permutation tests, bootstrap | scipy, scikit-learn |

Each method follows the `IAnalysisMethod` interface. Agents can also write custom methods that import `urika.methods.base` and implement the interface.

### 4.5 Built-in Tools

These are dual-API: importable as Python modules (`from urika.tools.builtin.data_profiler import profile`) AND callable from CLI (`python -m urika.tools.builtin.data_profiler --dataset data.csv`). The CLI mode enables agents to use them directly via bash without writing a script.

| Tool | What It Does |
|---|---|
| `data_profiler` | Automated EDA: dtypes, distributions, summary statistics, missing data, correlations |
| `correlation` | Pearson, Spearman, partial correlation matrices with significance tests |
| `hypothesis_tests` | Quick statistical tests with automatic assumption checking |
| `visualization` | Generate standard plots: histogram, scatter, box, line, heatmap, Q-Q, residuals |
| `outlier_detection` | IQR, Z-score, Mahalanobis distance, isolation forest |
| `missing_data` | Missing data patterns, MCAR/MAR/MNAR tests, imputation strategies |
| `feature_importance` | Permutation importance, SHAP values, mutual information |
| `power_analysis` | Statistical power calculation, required sample size estimation |
| `normality` | Shapiro-Wilk, Anderson-Darling, D'Agostino-Pearson, Q-Q diagnostics |
| `effect_sizes` | Cohen's d, Hedges' g, eta-squared, odds ratio, risk ratio |

---

## 5. Project Structure

### 5.1 Pi Package (TypeScript)

```
pi-urika/                             # The Pi package (npm-publishable)
    package.json                      # Pi package manifest with "pi" field
    tsconfig.json
    vitest.config.ts

    extensions/
        urika.ts                      # Main extension entry point
                                      #   - Registers /investigate, /evaluate, /status, /leaderboard
                                      #   - Sets up security hooks
                                      #   - Initializes orchestrator

        orchestrator/
            orchestrator.ts           # Main control loop (deterministic, not LLM)
            agent-factory.ts          # createTaskAgent(), createEvaluator(), etc.
            session-tracker.ts        # Maps Pi sessions to investigation experiments
            investigation.ts          # Load/validate urika.toml config
            modes/
                exploratory.ts        # Exploratory mode orchestrator behavior + prompts
                confirmatory.ts       # Confirmatory mode with guardrails
                pipeline.ts           # Pipeline mode with stage gating

        security/
            path-guard.ts             # Per-agent write path validation
            bash-guard.ts             # Mutating command detection and blocking
            roles.ts                  # AgentRole definitions, per-role allowed paths

        commands/
            investigate.ts            # /investigate — interactive setup (system builder agent)
            evaluate.ts               # /evaluate — trigger manual evaluation
            status.ts                 # /status — show investigation state
            leaderboard.ts            # /leaderboard — display current rankings
            report.ts                 # /report — generate summary report

    skills/
        exploratory-analysis/
            SKILL.md                  # Open-ended data exploration strategy
        statistical-modelling/
            SKILL.md                  # Statistical model building and comparison
        hypothesis-testing/
            SKILL.md                  # Confirmatory hypothesis testing workflow
        data-profiling/
            SKILL.md                  # Initial dataset assessment strategy
        literature-review/
            SKILL.md                  # Literature search and synthesis
        eeg-analysis/
            SKILL.md                  # EEG-specific preprocessing and analysis
        survey-analysis/
            SKILL.md                  # Psychometrics and survey data analysis

    prompts/
        system-builder.md             # Investigation setup conversation
        task-agent.md                 # Task agent system prompt
        evaluator.md                  # Evaluator system prompt
        suggestion-agent.md           # Suggestion agent system prompt
        tool-builder.md               # Tool builder system prompt
        literature-agent.md           # Literature/knowledge agent system prompt

    test/
        orchestrator.test.ts          # Orchestration loop tests
        security.test.ts              # Security boundary tests (adversarial)
        agent-factory.test.ts         # Agent creation tests
        commands.test.ts              # Slash command tests
```

**package.json:**

```json
{
  "name": "@urika/pi-urika",
  "version": "0.1.0",
  "keywords": ["pi-package"],
  "pi": {
    "extensions": ["./extensions"],
    "skills": ["./skills"],
    "prompts": ["./prompts"]
  },
  "scripts": {
    "build": "tsc",
    "test": "vitest",
    "postinstall": "echo 'Run: pip install urika (or uv pip install urika) to install the Python analysis package'"
  },
  "dependencies": {
    "@mariozechner/pi-coding-agent": "^0.55.0"
  }
}
```

### 5.2 Python Analysis Package

```
urika-python/                         # Separate repository or monorepo subdirectory
    pyproject.toml                    # PEP 621, hatch build, dependency groups
    LICENSE                           # MIT
    src/urika/                        # (full tree shown in Section 4.2 above)
    tests/
        conftest.py                   # Shared fixtures: sample datasets, temp investigation dirs
        test_data/
            test_loader.py            # Format detection, loading, schema inference
            test_profiler.py          # Data profiling accuracy
            test_readers/
                test_tabular.py
                test_json.py
        test_methods/
            test_base.py              # IAnalysisMethod contract tests
            test_registry.py          # Method discovery
            test_builtin/
                test_regression.py
                test_classification.py
                test_hypothesis.py
        test_evaluation/
            test_runner.py            # Evaluation pipeline
            test_metrics.py           # Metric computation accuracy
            test_criteria.py          # Criteria validation logic
            test_leaderboard.py       # Leaderboard ranking
            test_cross_validation.py
        test_knowledge/
            test_pdf_extractor.py
            test_indexer.py
        test_session/
            test_manager.py
            test_progress.py
        test_tools/
            test_data_profiler.py
            test_visualization.py
        test_guardrails/
            test_confirmatory.py
        test_pipeline/
            test_stages.py
            test_pipeline.py
        integration/
            test_end_to_end.py        # Full: load data -> run method -> evaluate -> leaderboard
```

**pyproject.toml:**

```toml
[project]
name = "urika"
version = "0.1.0"
description = "Scientific analysis framework for agentic investigation"
requires-python = ">=3.10"
license = "MIT"
dependencies = [
    "numpy>=1.24",
    "pandas>=2.0",
    "scipy>=1.10",
    "scikit-learn>=1.3",
    "statsmodels>=0.14",
    "pingouin>=0.5",
    "matplotlib>=3.7",
    "seaborn>=0.12",
    "pymupdf>=1.23",
]

[project.optional-dependencies]
neuroscience = ["mne>=1.5", "mne-bids>=0.13", "pyedflib>=0.1"]
motor-control = ["ezc3d>=1.5"]
wearables = ["neurokit2>=0.2", "actipy>=3.0"]
linguistics = ["spacy>=3.6", "librosa>=0.10", "parselmouth>=0.4"]
ml-extended = ["xgboost>=2.0", "lightgbm>=4.0", "shap>=0.42"]
survival = ["lifelines>=0.27"]
factor-analysis = ["factor-analyzer>=0.5", "semopy>=2.6"]
all = ["urika[neuroscience,motor-control,wearables,linguistics,ml-extended,survival,factor-analysis]"]
dev = ["pytest>=7.0", "pytest-cov>=4.0", "ruff>=0.1", "mypy>=1.5"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/urika"]
```

### 5.3 Investigation Workspace (Created by `/investigate`)

```
my-investigation/                     # Created by the system builder agent
    urika.toml                       # Investigation config: question, dataset, mode, agent config
    config/
        success_criteria.json        # Metric thresholds for success
        agents.json                  # Agent team configuration (models, turn limits)
        analysis_plan.json           # (confirmatory mode only) locked analysis plan
    data/
        raw/                         # Original data files (user-provided)
        processed/                   # Agent-generated processed versions
    methods/                         # Investigation-specific methods (agent-writable)
        custom_method_01.py
    tools/                           # Investigation-specific tools (agent-writable)
        tools_registry.json
    scripts/                         # Agent-written analysis scripts (auditable)
        run_ridge.py
        run_xgboost.py
        evaluate_cluster.py
    results/
        sessions/
            session_001/
                session.json
                progress.json
                evaluation/
                    metrics.json
                    criteria_check.json
                runs/
                    run_001.json
                    run_002.json
                scripts/             # Copy of scripts that produced these results
        leaderboard.json
        suggestions/
            suggestion_001.json
    knowledge/
        papers/                      # Ingested PDFs
        index.json                   # Knowledge base index
        summaries/                   # Structured paper summaries
    reports/
        final_report.md              # Generated summary report
```

---

## 6. Implementation Plan

### Phase 0: Validate Pi SDK Embedding (1 week)

**Goal:** Prove that Pi's SDK can be used to programmatically spawn agent sessions with custom tools, enforce security via event hooks, and sequence multiple agents. This is the go/no-go gate.

**What gets built:**

1. **Minimal Pi extension** (`extensions/spike.ts`) that:
   - Registers a `/spike` command
   - Uses `createAgentSession()` to spawn a session with a custom system prompt
   - The session has access to Pi's built-in tools (read, write, bash)
   - The agent writes a Python script, runs it via bash, reads the output
   - Verify: the agent can successfully write and execute Python code

2. **Security hook spike**: Register a `tool_call` event hook that blocks writes to a specific directory. Verify the hook fires, the write is blocked, and the agent receives the error message.

3. **Multi-agent sequencing spike**: Spawn two sessions sequentially — first agent writes a file, second agent reads it and writes a response. Verify filesystem-based communication works.

4. **Python package import spike**: Install a minimal `urika` package (`pip install -e .`), have the agent write a script that `from urika import something`, run it, verify it works.

**Pass criteria:**
- Agent can write and run Python scripts that import urika
- Security hooks successfully block unauthorized writes
- Two agents can communicate via filesystem
- Total overhead of session creation is acceptable (<2s)

**Fail criteria (abort Option B):**
- createAgentSession() does not support custom tool restrictions
- Event hooks cannot block tool execution (only observe)
- Session creation overhead is >10s
- SDK is too unstable to build on

### Phase 1: Core Python Package — Data and Methods (2-3 weeks)

**Goal:** The urika Python package can load data, run methods, and compute metrics. No agents yet — this is the foundation that agents' scripts will import.

**1.1 Data layer**
- `data/dataset.py`: `DatasetSpec`, `DatasetView`, `DataSummary`, `ColumnSchema` dataclasses
- `data/loader.py`: `load_dataset(path, target=None, features=None)` with format auto-detection (CSV, TSV, Excel, Parquet, JSON)
- `data/schema.py`: Column role inference (heuristics: column named "id" is id, datetime columns are time, etc.)
- `data/profiler.py`: `profile_dataset(dataset) -> DataSummary` — dtypes, missing counts, unique counts, basic distributions
- `data/readers/base.py`: `IDataReader` protocol
- `data/readers/tabular.py`: CSV, TSV, Excel, Parquet, SPSS, Stata via pandas
- `data/readers/json_reader.py`: JSON and JSON Lines
- Tests for all of the above with sample datasets

**1.2 Method system**
- `methods/base.py`: `IAnalysisMethod` ABC with `name()`, `description()`, `category()`, `default_params()`, `set_params()`, `get_params()`, `run()`. `MethodResult` dataclass.
- `methods/domain_bases.py`: `ITabularMethod`, `ITimeSeriesMethod` with typed APIs
- `methods/registry.py`: `MethodRegistry` with `discover_methods()` — scans `builtin/` and optionally an investigation's `methods/` directory. Registration by name, lookup by name or category.
- Tests: method registration, discovery, base class contracts

**1.3 First built-in methods**
- `methods/builtin/regression.py`: OLS, Ridge, Lasso, ElasticNet — all implementing `ITabularMethod`
- `methods/builtin/classification.py`: Logistic Regression, Random Forest — implementing `ITabularMethod`
- `methods/builtin/hypothesis_tests.py`: Independent t-test, paired t-test, one-way ANOVA — implementing `IAnalysisMethod` directly
- Tests: each method runs on sample data, produces valid MethodResult

**1.4 Configuration**
- `config/investigation.py`: `InvestigationConfig` dataclass, `load_config(path) -> InvestigationConfig` from TOML
- `config/schemas.py`: Pydantic or dataclass schemas for `urika.toml`, `success_criteria.json`, `agents.json`

**Deliverables:**
- `pip install -e .` works
- `from urika.data import load_dataset` loads a CSV and returns a DatasetView
- `from urika.methods.builtin.regression import RidgeRegression` creates a method, `.run()` returns a MethodResult
- `from urika.methods import list_methods` returns all discovered methods
- Tests pass

### Phase 2: Core Python Package — Evaluation and Sessions (2 weeks)

**Goal:** The evaluation pipeline works end-to-end: run method, compute metrics, validate criteria, update leaderboard, record session progress.

**2.1 Metrics library**
- `evaluation/metrics.py`: `IMetric` ABC, `MetricRegistry` with auto-discovery
- Built-in metrics: R2, RMSE, MAE, MSE, accuracy, precision, recall, F1, AUC, log_loss, Cohen_d, eta_squared
- Each metric: `name()`, `compute(y_true, y_pred, **kwargs)`, `direction()` ("higher_is_better" | "lower_is_better")
- Tests: metric computation against known values (e.g., R2 of perfect prediction = 1.0)

**2.2 Cross-validation**
- `evaluation/cross_validation.py`: `cross_validate(method, dataset, metrics, folds, strategy)` — returns per-fold and aggregated metrics
- Strategies: k-fold, stratified k-fold, leave-one-out, time-series split
- Tests: correct fold counts, stratification works, aggregation is correct

**2.3 Evaluation runner**
- `evaluation/runner.py`: `run_evaluation(method, dataset, metrics, cv_folds, cv_strategy)` — the main function agents call
- Handles: cross-validation, metric computation, result assembly, artifact generation (basic residual plots), timing
- Returns `EvalResult` with aggregated metrics, fold metrics, method result, artifacts
- Tests: end-to-end evaluation with sample data

**2.4 Criteria validation**
- `evaluation/criteria.py`: `Criterion` dataclass, `load_criteria(path)`, `validate_criteria(metrics, criteria) -> CriteriaResult`
- Support `threshold` type (pass/fail) and `report_only` type (logged but not checked)
- Support stage-dependent criteria (for pipeline mode)
- Tests: criteria passing, failing, report_only, edge cases

**2.5 Leaderboard**
- `evaluation/leaderboard.py`: `update_leaderboard()`, `load_leaderboard()`, `LeaderboardEntry`
- Leaderboard stored as `results/leaderboard.json`
- Sorted by `primary_metric` in configured `direction`
- Tests: adding entries, re-ranking, loading/saving

**2.6 Session tracking**
- `session/manager.py`: `create_session()`, `resume_session()`, `complete_session()`, `fail_session()`
- `session/progress.py`: `record_run()`, `load_progress()`, `update_progress()`
- Progress format: JSON with run records including method, params, metrics, hypothesis, observation, next_step
- Tests: session lifecycle, run recording, progress loading

**Deliverables:**
- A Python script can: load data -> run a method -> evaluate with cross-validation -> check criteria -> update leaderboard -> record session progress
- All filesystem JSON files are written correctly
- Tests pass for the complete evaluation pipeline

### Phase 3: Pi Extension — Orchestration and Security (2-3 weeks)

**Goal:** The TypeScript extension orchestrates multi-agent sessions with security enforcement.

**3.1 Extension skeleton**
- `extensions/urika.ts`: Main entry point that registers with Pi
- Reads configuration, sets up security hooks, registers commands
- Tests: extension loads successfully in Pi

**3.2 Security layer**
- `extensions/security/roles.ts`: `AgentRole` enum (TaskAgent, Evaluator, SuggestionAgent, ToolBuilder), per-role writable/readable paths
- `extensions/security/path-guard.ts`: `isPathAllowed(path, role, operation)` — validates file paths against role permissions
- `extensions/security/bash-guard.ts`: `containsMutatingOperation(command)` — detects `>`, `>>`, `tee`, `mv`, `cp`, `rm`, `dd` in bash commands
- Integration with Pi's `tool_call` event hook
- Tests: adversarial paths (symlinks, `../` traversal, tilde expansion), adversarial bash commands (piped writes, subshell writes)

**3.3 Agent factory**
- `extensions/orchestrator/agent-factory.ts`:
  - `createTaskAgent(config)`: Pi session with full tools, task agent system prompt, writable to methods/ and results/sessions/<id>/
  - `createEvaluator(config)`: Pi session with restricted bash, evaluator system prompt, writable to leaderboard and evaluation/
  - `createSuggestionAgent(config)`: Pi session with restricted bash, suggestion prompt, writable to results/suggestions/
  - `createToolBuilder(config)`: Pi session with full tools, tool builder prompt, writable to tools/
- Each function: selects model, loads system prompt, configures tools, attaches security hook
- Tests: correct tool sets, correct system prompts, security hooks attached

**3.4 Orchestrator**
- `extensions/orchestrator/orchestrator.ts`: The deterministic control loop
  - Load investigation config
  - Create/resume session
  - Loop: task agent -> evaluator -> criteria check -> suggestion agent -> (optional) tool builder -> repeat
  - Termination: criteria met, max turns, user stop
  - Turn tracking, cost estimation, progress reporting
- `extensions/orchestrator/investigation.ts`: Load and validate `urika.toml`
- `extensions/orchestrator/session-tracker.ts`: Map experiments to Pi sessions, track which agents ran when
- Tests: orchestration loop with mock agents, termination conditions

**3.5 Investigation modes**
- `extensions/orchestrator/modes/exploratory.ts`: Default mode — unrestricted exploration, full leaderboard
- `extensions/orchestrator/modes/confirmatory.ts`: Locked analysis plan, restricted suggestions, no leaderboard, audit logging
- `extensions/orchestrator/modes/pipeline.ts`: Ordered stages, stage-gated progression, stage-specific criteria
- Each mode: provides mode-specific system prompt fragments and orchestrator behavior overrides
- Tests: confirmatory mode blocks plan changes, pipeline mode gates stages

**Deliverables:**
- `/investigate` starts an interactive setup session (system builder agent)
- The orchestrator runs a complete loop: task agent writes and runs Python scripts, evaluator validates results, suggestion agent proposes next steps
- Security boundaries are enforced (evaluator cannot write to methods/)
- All three investigation modes work
- Tests pass

### Phase 4: Remaining Built-in Methods and Tools (2 weeks)

**Goal:** Full method library and tool suite for agents to use.

**4.1 Additional methods**
- `methods/builtin/classification.py`: Add SVM, KNN, XGBoost, Gradient Boosting
- `methods/builtin/clustering.py`: K-Means, DBSCAN, Agglomerative, Gaussian Mixture
- `methods/builtin/hypothesis_tests.py`: Add mixed ANOVA, chi-squared, Mann-Whitney, Kruskal-Wallis, Friedman, Wilcoxon
- `methods/builtin/factor_analysis.py`: PCA, EFA (via factor_analyzer), CFA stubs (via semopy)
- `methods/builtin/mixed_effects.py`: Linear mixed-effects models (via statsmodels)
- `methods/builtin/time_series.py`: ARIMA, exponential smoothing, seasonal decomposition
- `methods/builtin/survival.py`: Kaplan-Meier, Cox regression (via lifelines)
- `methods/builtin/nonparametric.py`: Permutation tests, bootstrap confidence intervals
- Tests for each method with appropriate sample data

**4.2 Built-in tools**
- `tools/builtin/data_profiler.py`: Full automated EDA with summary and distribution analysis
- `tools/builtin/correlation.py`: Correlation matrices with significance
- `tools/builtin/hypothesis_tests.py`: Quick testing with automatic assumption checking
- `tools/builtin/visualization.py`: Standard plot generation (histogram, scatter, box, line, heatmap, Q-Q, residuals)
- `tools/builtin/outlier_detection.py`: Multiple detection methods
- `tools/builtin/missing_data.py`: Missing data analysis and imputation
- `tools/builtin/feature_importance.py`: Permutation importance, SHAP
- `tools/builtin/power_analysis.py`: Power and sample size
- `tools/builtin/normality.py`: Normality testing
- `tools/builtin/effect_sizes.py`: Effect size computation
- Each tool: importable API + CLI via `python -m urika.tools.builtin.<name>`
- Tool registry: `tools/registry.py` with auto-discovery

**4.3 Pipeline support**
- `pipeline/stage.py`: `PipelineStage` ABC, `StageResult`
- `pipeline/pipeline.py`: `Pipeline` class — ordered execution with inter-stage validation
- `pipeline/builtin_stages/`: filtering, artifact rejection, epoching, feature extraction, normalization
- Tests: pipeline execution, stage ordering, inter-stage data passing

**Deliverables:**
- 25+ analysis methods available
- 10+ built-in tools available
- Pipeline mode has usable built-in stages
- Method and tool registries discover everything automatically

### Phase 5: Knowledge Pipeline (1-2 weeks)

**Goal:** Agents can ingest papers, search literature, and reference domain knowledge.

**5.1 PDF extraction**
- `knowledge/pdf_extractor.py`: Extract text and tables from PDFs using pymupdf
- Handle: multi-column layouts, embedded tables, references sections
- Output: structured JSON with sections, tables, references
- Tests: extraction from sample academic PDFs

**5.2 Literature search**
- `knowledge/literature.py`: Search Semantic Scholar API, parse results
- Fetch paper metadata: title, authors, abstract, year, citation count
- Optional: full text download where available
- Tests: search returns relevant results, metadata parsing

**5.3 Knowledge indexing**
- `knowledge/indexer.py`: Build TF-IDF index over ingested documents
- `knowledge/index.py`: `KnowledgeIndex` — add entries, search by query, list all
- Index stored as `knowledge/index.json` with `knowledge/summaries/*.json` per document
- Optional: embedding-based search if sentence-transformers available
- Tests: indexing, search relevance, persistence

**5.4 Integration with agents**
- Agent scripts can call: `from urika.knowledge import search_knowledge, ingest_pdf`
- Suggestion agent uses knowledge to recommend approaches from literature
- Tool builder references papers when creating methods
- Tests: end-to-end knowledge ingestion and retrieval

**Deliverables:**
- `python -m urika.knowledge.pdf_extractor paper.pdf` extracts text and tables
- `from urika.knowledge import search_knowledge` returns relevant knowledge entries
- Knowledge base persists across sessions

### Phase 6: Agent Prompts and Skills (1-2 weeks)

**Goal:** High-quality system prompts that make agents effective at scientific analysis.

**6.1 System prompts**
- `prompts/system-builder.md`: Guide investigation setup — ask about dataset, question, success criteria, domain, investigation mode. Generate urika.toml and config files.
- `prompts/task-agent.md`: Instruct the agent on how to use the urika Python package — writing scripts, running evaluations, interpreting results, recording progress. Include: how to read suggestions, how to try novel approaches, how to use the method registry.
- `prompts/evaluator.md`: Instruct on independent validation — re-run metrics, verify claimed results, check criteria, update leaderboard. Emphasize: do not trust agent claims, run your own evaluation scripts.
- `prompts/suggestion-agent.md`: Instruct on strategic analysis — what methods remain untried, what parameter ranges unexplored, what the literature says, how to write actionable suggestions with priorities and implementation sketches.
- `prompts/tool-builder.md`: Instruct on creating Python tools and methods that follow the urika interfaces, testing them, registering them.
- `prompts/literature-agent.md`: Instruct on knowledge acquisition — searching for relevant papers, extracting methods and findings, building the knowledge base.

**6.2 Domain skills**
- `skills/exploratory-analysis/SKILL.md`: Strategy for open-ended data exploration
- `skills/statistical-modelling/SKILL.md`: Statistical model selection and comparison
- `skills/hypothesis-testing/SKILL.md`: Confirmatory testing workflow
- `skills/data-profiling/SKILL.md`: Systematic dataset assessment
- `skills/literature-review/SKILL.md`: Academic literature search and synthesis
- `skills/survey-analysis/SKILL.md`: Psychometrics, factor analysis, reliability
- `skills/eeg-analysis/SKILL.md`: EEG preprocessing and analysis pipeline

**6.3 Prompt iteration**
- Run test investigations with each agent
- Identify failures: agents not using the urika package correctly, not recording progress, not reading suggestions
- Iterate prompts based on observed behavior

**Deliverables:**
- All agent prompts written and tested
- Domain skills packaged
- Agents successfully use the urika package in their scripts
- Agents communicate effectively via filesystem JSON

### Phase 7: Commands, Reporting, and Polish (1-2 weeks)

**Goal:** User-facing commands work smoothly, reports are generated, and the experience is polished.

**7.1 Slash commands**
- `/investigate` (or `/investigate <name>`): Start interactive investigation setup
- `/evaluate`: Trigger manual evaluation of current results
- `/status`: Show investigation state — current session, turn count, best metrics, criteria status
- `/leaderboard`: Display current method rankings
- `/report`: Generate Markdown summary report

**7.2 Reporting**
- `session/report.py`: Generate comprehensive Markdown reports including:
  - Investigation summary (question, dataset, criteria)
  - Method comparison table
  - Best results with parameters
  - Metric trajectories over turns
  - Suggestion log
  - Knowledge references
  - Reproducibility information (method params, data hash, package versions)

**7.3 Session management polish**
- `session/comparison.py`: Compare results across sessions
- Resume interrupted investigations with full context
- Clean display of progress in terminal

**7.4 Guardrails**
- `guardrails/confirmatory.py`: Plan locking, multiple comparisons correction (Bonferroni, Holm, FDR), HARKing detection, decision audit logging
- `guardrails/validators.py`: Assumption checking (normality, homoscedasticity, independence), sample size warnings, convergence checks

**Deliverables:**
- All commands work
- Reports are comprehensive and well-formatted
- Confirmatory mode guardrails prevent p-hacking
- Session resume works correctly

### Phase 8: End-to-End Testing and Packaging (1-2 weeks)

**Goal:** Ship a working Pi package with comprehensive tests.

**8.1 End-to-end tests**
- Test 1: Survey data (CSV) -> exploratory mode -> agents try regression methods -> leaderboard shows rankings -> criteria met
- Test 2: Experimental data -> confirmatory mode -> pre-registered analysis -> guardrails prevent deviation
- Test 3: Time series data -> pipeline mode -> preprocessing stages -> analysis
- Each test: verify correct filesystem state, correct leaderboard, correct criteria checks

**8.2 Security tests**
- Adversarial prompt tests: can an agent bypass write restrictions?
- Path traversal tests: `../`, symlinks, absolute paths outside investigation
- Bash injection tests: encoded writes, subshell escapes

**8.3 Python package release**
- Final `pyproject.toml` review
- Test installation on clean environments (Python 3.10, 3.11, 3.12)
- Publish to PyPI (or keep private initially)

**8.4 Pi package release**
- Final `package.json` review
- `pi install` from npm works
- Documentation: getting started, writing custom methods, investigation modes, architecture
- CI: TypeScript tests + Python tests

**Deliverables:**
- Published Pi package: `pi install npm:@urika/pi-urika`
- Published Python package: `pip install urika`
- CI passing with end-to-end tests
- Documentation for users and method authors

### Phase 9: Domain Packs (Post-Core, Ongoing)

Domain packs are optional extensions that add domain-specific methods, metrics, data readers, pipeline stages, and skills. Each is a separate pip-installable package.

Priority order:

1. **Survey/Psychometrics** — Most accessible, simplest data. Adds: factor analysis methods (CFA, IRT), reliability metrics (Cronbach's alpha, McDonald's omega), survey-specific profiling, psychometrics skill.

2. **Cognitive Experiments** — Common in psychology research. Adds: RT distribution methods (ex-Gaussian, DDM), signal detection theory, mixed ANOVA helpers, cognitive experiment skill.

3. **Wearable Sensors** — Growing field, time series focus. Adds: IMU readers, activity classification, HR/HRV analysis, accelerometry features, wearable analysis skill.

4. **Motor Control** — Specialized kinematics. Adds: C3D reader, coordination metrics (relative phase, UCM), trajectory analysis, movement segmentation, motor control skill.

5. **Eye Tracking** — Fixation and scanpath analysis. Adds: fixation detection, AOI analysis, scanpath comparison, pupillometry, eye tracking skill.

6. **Cognitive Neuroscience** — Complex preprocessing. Adds: EDF/BDF readers, MNE integration, ERP analysis, time-frequency decomposition, MVPA, EEG/fMRI skills.

7. **Linguistics** — NLP and speech. Adds: audio reader, speech feature extraction, corpus analysis, syntactic complexity, linguistics skill.

8. **Epidemiology** — Survival and spatial. Adds: advanced survival analysis, spatial clustering, case-control methods, epidemiology skill.

---

## 7. Risks and Mitigations

### Risk 1: Pi SDK Stability

**Risk:** Pi is pre-1.0 (v0.55 as of writing). The SDK, extension API, and session format may change. Breaking changes could require significant rework of the TypeScript layer.

**Likelihood:** Medium-high.

**Mitigation:**
- Pin Pi to a specific version range in `package.json`
- Isolate Pi-specific code behind adapters. The agent factory (`agent-factory.ts`) wraps `createAgentSession()` — API changes are absorbed in one file, not scattered across the codebase
- The Python analysis package has zero Pi dependency. It does not know Pi exists. If Pi becomes untenable, the Python package works with any other orchestrator
- Monitor Pi changelog, test against new versions in CI
- Maintain communication with Pi maintainer(s)
- Worst case: fork Pi (MIT licensed) and maintain a stable branch for Urika

### Risk 2: Security Hook Limitations

**Risk:** Pi's `tool_call` event hooks may not be powerful enough to enforce Urika's security model. If hooks can only observe (not block) tool calls, or if they race with execution, the evaluator could write to methods/ and compromise the trust model.

**Likelihood:** Medium. Pi's extension system is designed for this, but edge cases exist.

**Mitigation:**
- Phase 0 spike specifically tests blocking behavior of hooks
- If hooks cannot block: wrap Pi's tools with Urika-owned versions that check permissions before delegating to the real tool. Each agent gets Urika's wrapped tools, not Pi's raw tools.
- Defense in depth: filesystem permissions (Unix) as a second layer. Run agents in processes with restricted file access at the OS level.
- Audit logging: every tool call is logged regardless, so violations are detectable even if not preventable in real time

### Risk 3: Python Environment Management

**Risk:** Users have different Python versions, missing scientific packages, broken pip installs, conda vs pip conflicts. The urika Python package fails to install or import.

**Likelihood:** High. Python environment management is notoriously fragile, and scientific packages (numpy, scipy, etc.) have native dependencies.

**Mitigation:**
- Require Python >=3.10, detect and report version issues at install time
- Recommend `uv` for installation (`uv pip install urika`) — faster, more reliable than pip
- Provide a `/investigate doctor` command that checks: Python version, required packages importable, urika package version, sample data loads correctly
- Support `URIKA_PYTHON` environment variable to point to a specific Python binary (e.g., conda env)
- Minimal core dependencies: numpy, pandas, scipy, scikit-learn, statsmodels. Domain-specific packages are optional extras: `pip install urika[neuroscience]`
- Consider Docker image for users who cannot get Python working locally
- Test installation on Linux, macOS, Windows in CI

### Risk 4: Agent Quality and Reliability

**Risk:** LLM agents write buggy Python scripts. Scripts crash, import the wrong things, write incorrect JSON formats, fail to record progress. The multi-agent loop degrades because one agent's output is garbage that the next agent cannot process.

**Likelihood:** High. This is the fundamental challenge of agentic systems.

**Mitigation:**
- High-quality system prompts with concrete examples of correct scripts (Phase 6)
- The urika Python package validates inputs aggressively — `load_dataset()` raises clear errors for wrong paths/formats, `record_run()` validates JSON schema, `update_leaderboard()` validates metric values
- The evaluation runner catches exceptions and returns structured error results (not crashes)
- The orchestrator checks agent outputs between turns — if progress.json is malformed or missing, the next agent gets an error message with instructions to fix it
- Retry logic: if an agent's script fails, the orchestrator can re-prompt the agent with the error
- Well-typed Python APIs reduce the surface area for errors — agents follow patterns from the system prompt, and the package's API is designed to be hard to misuse

### Risk 5: LLM Token Costs

**Risk:** Multi-agent orchestration multiplies LLM costs. Each orchestrator turn involves 4+ agent sessions. An investigation with 50 turns means 200+ LLM calls, potentially costing $50-100+ with Opus.

**Likelihood:** High. Inherent to multi-agent architectures.

**Mitigation:**
- Model tiering: Sonnet (cheap) for task agents and evaluator, Opus (expensive) only for the suggestion agent which needs strategic reasoning. Haiku-class models for data profiling.
- Aggressive context management: agents get only what they need. The evaluator gets method outputs and criteria, not full conversation history.
- Turn budgets: configurable `max_turns` with cost estimation before each turn
- Cost tracking: the orchestrator logs cumulative LLM costs, can pause for user confirmation at thresholds
- Short agent sessions: each agent is spawned fresh with focused context, not a long-running conversation
- Pi's context compaction reduces token waste from long sessions

### Risk 6: Researcher Adoption

**Risk:** Target users (behavioral/health science researchers) may not have Node.js installed, may be intimidated by a terminal agent, and may prefer Python-native tools (Jupyter, pure Python CLI).

**Likelihood:** High. This is a market risk, not a technical risk.

**Mitigation:**
- Method/tool authors (the extension point) never touch TypeScript — they write Python
- End users interact via Pi's TUI — they do not write TypeScript either
- Installation should be: `npx pi install npm:@urika/pi-urika` + `pip install urika`
- Consider shipping a standalone binary (Pi supports Bun-based builds) that bundles Node.js
- Long-term escape hatch: the Python package is Pi-independent. If the audience demands a pure Python experience, the orchestration can be rewritten in Python (~2 weeks) while keeping the entire analysis package unchanged
- Jupyter integration as a future extension (not v1)

### Risk 7: Orchestrator Complexity

**Risk:** The deterministic orchestrator loop is simple in design but complex in practice. Edge cases: agent dies mid-turn, criteria change during investigation, filesystem gets corrupted, two suggestions conflict, tool builder creates a broken tool that crashes task agents.

**Likelihood:** Medium. Orchestration is always harder than it looks.

**Mitigation:**
- Start with the simplest possible loop (Phase 3) — linear sequence, no parallelism, no fancy error recovery
- Add resilience incrementally: retry failed agents, skip corrupted suggestions, quarantine broken tools
- Every filesystem write is atomic (write to temp, rename) to prevent corruption
- Session state is reconstructable from filesystem — if session.json is lost, re-derive from progress.json and leaderboard.json
- Extensive logging of orchestrator decisions for debugging
- Turn-level checkpointing: the orchestrator can resume from any turn, not just the beginning

### Risk 8: Session Model Mismatch

**Risk:** Pi sessions are conversation trees (user message -> assistant response -> tool calls). Urika needs experiment trees (hypothesis -> method -> result -> evaluation). Mapping one onto the other may be awkward or lossy.

**Likelihood:** Medium.

**Mitigation:**
- Do not force the mapping. Pi sessions store conversation history. Urika's filesystem JSON stores experiment data. They are complementary.
- Pi sessions are useful for: resuming agent conversations, branching analysis paths, context compaction
- Urika's JSON files are the source of truth for: runs, metrics, leaderboard, suggestions
- If Pi's session model becomes a hindrance rather than a help, agents can be spawned as stateless (no session persistence) and all state lives in Urika's filesystem JSON. This is a graceful degradation that requires changing one line in agent-factory.ts.

---

## 8. Migration Path

Option B sits between two alternatives. Understanding how all three relate helps clarify what is portable and what is not.

### Option A: Claude Agent SDK (All-Python, Fast Start)

Option A uses Anthropic's Claude Agent SDK to build the entire system in Python. There is no TypeScript, no Node.js, no npm. The orchestrator, security layer, agent factory, and CLI are all Python. This eliminates the split-stack tradeoff entirely: one language, one package manager (`uv`/`pip`), one test framework (`pytest`), one ecosystem.

Option A trades runtime maturity for development speed and ecosystem coherence. It does not get Pi's 15+ LLM providers, tree-structured sessions, TUI, or extension system for free. But it avoids the friction of maintaining TypeScript orchestration code in a scientific Python project.

### Option C: Custom Runtime (Full Control)

Option C builds a custom Python+TypeScript agent runtime from scratch. It provides maximum control over the agent loop, tool dispatch, session management, and every other runtime detail. The cost is 4-6 additional weeks of development and permanent maintenance responsibility for infrastructure that Pi (Option B) or the Claude Agent SDK (Option A) would provide.

### What Is Shared Across All Three Options

**The `urika` Python package is identical in all three options.** The data layer, method system, evaluation runner, metrics library, leaderboard, knowledge pipeline, session tracking, built-in methods, built-in tools, guardrails, and pipeline support do not change. This is the core product — the thing that makes Urika useful for scientific analysis. It is a library that agent-written scripts import. It does not know or care which runtime spawned the agent that wrote the script.

This means migration between options is a matter of replacing the orchestration layer, not rewriting the analysis framework:

- **Option B to Option A**: Replace the TypeScript Pi extension with a Python orchestrator using the Claude Agent SDK. The agent factory, security layer, and CLI commands are rewritten in Python. The `urika` package, all prompts, and all investigation workspace conventions remain unchanged. Estimated effort: 2-3 weeks.

- **Option B to Option C**: Replace Pi's runtime with a custom TypeScript runtime. The orchestration logic in `extensions/orchestrator/` transfers directly — the control loop, agent sequencing, and security model are the same. What changes is the underlying session management and tool dispatch. Estimated effort: 4-6 weeks (the Phase 1 from Option C's plan).

- **Option A to Option B**: Wrap the Python orchestrator's logic in a TypeScript Pi extension. The `urika` package is unchanged. The orchestration logic is ported from Python to TypeScript. Estimated effort: 2-3 weeks.

### When to Choose Option B

Option B is the right choice when:
- Pi's runtime is stable enough to build on (validated by Phase 0)
- The 15+ LLM provider support, tree-structured sessions, and TUI justify the split-stack cost
- The team is comfortable maintaining TypeScript alongside Python
- The project benefits from Pi's extension and skills ecosystem

Option B is the wrong choice when:
- Pi's SDK proves too unstable or limited (Phase 0 fails)
- The split-stack friction outweighs the runtime benefits
- The target audience cannot tolerate a Node.js dependency
- Development velocity matters more than runtime features (Option A is faster to ship)
