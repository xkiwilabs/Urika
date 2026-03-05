# Urika: Agentic Scientific Analysis Platform — PRD & Implementation Plan

## Context

Urika is a domain-agnostic, open-source platform for scientific analysis across behavioral and health sciences. It uses a multi-agent architecture where agents write and run Python code to explore data, test analytical methods, evaluate results, and build tools — communicating via filesystem-based JSON messages with enforced security boundaries.

Urika's agents are fundamentally coding agents: they write Python scripts that import the `urika` library, run experiments, generate plots, and produce structured results. The platform provides the scientific analysis framework that these agents work with — data loading, method registries, evaluation metrics, leaderboards, knowledge pipelines — while the agent runtime handles the prompt → response → tool dispatch loop.

### Runtime Strategy

The Python `urika` package — data loading, methods, evaluation, metrics, leaderboard, knowledge pipeline, built-in methods, session management — is ~80% of the codebase and is **identical regardless of which agent runtime is used**. The runtime only affects the ~20% orchestration and security layer.

**Plan**:
1. **Phase 1 (v0.x)**: Build Urika on the **Claude Agent SDK** (see `docs/dev/option-a-claude-agent-sdk.md`). This keeps the entire stack in Python, provides built-in multi-agent orchestration and security, and is the fastest path to a working product. The tradeoff is Claude-only LLM support.
2. **Phase 2 (v1.x)**: Once the platform is complete, tested, and robust, build a **custom Python runtime** inspired by Pi and the Claude Agent SDK (see `docs/dev/option-c-custom-runtime.md`). This gives full control, model-agnostic LLM support, and removes the Anthropic dependency — making the entire platform custom.

The migration is clean because agents interact with the runtime through a thin orchestration layer. Swapping Claude SDK for a custom runtime means rewriting that layer (~500-1500 lines), not the analysis framework.

For the Pi-based alternative approach, see `docs/dev/option-b-build-on-pi.md`.

---

## Part 1: Product Requirements Document

### 1.1 Vision

A researcher downloads Urika, points it at their dataset and research question, and the system autonomously explores analytical approaches, builds tools, evaluates methods against success criteria, and documents everything — producing a ranked set of analysis solutions with full reproducibility.

### 1.2 Users

- **Primary**: Researchers in behavioral/health sciences who have data and a question but want to explore analytical approaches systematically
- **Secondary**: Data scientists who want a structured framework for autonomous method comparison
- **Tertiary**: Teams who want reproducible, documented analysis pipelines

### 1.3 Core Capabilities

**Investigation Setup** (`urika init`)
- Interactive session with System Builder agent to define the problem
- Dataset ingestion with automatic schema detection and profiling
- Success criteria definition (metrics + thresholds)
- Knowledge ingestion: PDFs, papers, URLs, existing results
- Automated literature review via web search
- Agent team configuration for the specific domain

**Autonomous Analysis** (`urika run`)
- Task agents explore data, write analysis methods, run experiments
- Evaluator agent scores results against success criteria (read-only, trustworthy)
- Suggestion agent analyzes results, searches literature, proposes next experiments
- Tool builder agent creates new analysis tools on demand
- All work documented: hypotheses, observations, metrics, artifacts

**Session Management**
- Sessions = analysis experiments, each with tracked runs
- Stop/continue: `urika run --continue`
- Turn limits: `urika run --max-turns 50`
- Cross-session comparison and leaderboards
- Full audit trail in JSON files on disk

**Knowledge Pipeline**
- PDF/paper ingestion with text and table extraction
- Web search for literature review
- Domain knowledge base that grows over time
- Methods tried, results achieved, approaches unexplored

### 1.4 Target Domains

| Domain | Data Types | Key Libraries | Example Question |
|--------|-----------|---------------|------------------|
| Survey/Psychometrics | Likert scales, demographics | `factor_analyzer`, `semopy` | "What latent factors explain this 40-item questionnaire?" |
| Cognitive Experiments | Reaction times, accuracy | `pingouin`, `HDDM` | "Does the Stroop effect interact with age group?" |
| Psychology/Health | Clinical assessments, longitudinal | `statsmodels`, `lifelines` | "What predicts treatment response at 6 months?" |
| Motor Control | Kinematics, trajectories, EMG | `scipy`, `ezc3d` | "How does coordination change with practice?" |
| Wearable Sensors | Accelerometry, HR, EDA | `neurokit2`, `actipy` | "Can we classify activity patterns from wrist-worn IMU?" |
| Eye Tracking | Fixations, saccades, pupil | custom, `scipy` | "Do scanpath patterns differ between expert and novice?" |
| Cognitive Neuroscience | EEG, fMRI, MEG | `mne`, `nilearn` | "Which ERP component predicts behavioral accuracy?" |
| Computer Vision/LiDAR | Point clouds, detections | `open3d`, `opencv` | "Optimize 3D bbox estimation from 2D+LiDAR fusion" |
| Linguistics | Corpora, speech, phonetics | `spacy`, `parselmouth` | "What acoustic features predict perceived fluency?" |
| Epidemiology | Survival, spatial, case-control | `lifelines`, `geopandas` | "Is there spatial clustering of this health outcome?" |

### 1.5 Non-Goals (v1)

- Real-time/streaming analysis
- GUI/web interface (CLI only, with optional viewer later)
- Multi-user collaboration features
- Cloud deployment or remote execution
- Training deep learning models from scratch (can use pre-trained)

---

## Part 2: Architecture

### 2.1 Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Agent runtime (v0.x) | Claude Agent SDK | All-Python stack. Built-in orchestration, security, retries. Fastest to prototype. |
| Agent runtime (v1.x) | Custom Python runtime | Model-agnostic, full control, no vendor dependency. |
| LLM (v0.x) | Claude (via SDK) | Opus for complex reasoning, Sonnet for routine tasks. |
| LLM (v1.x) | Any (via litellm or custom adapters) | Claude, GPT-4, Gemini, open-source models. |
| CLI | `click` | Mature, composable subcommands. |
| Config | `tomllib` (stdlib) + JSON | TOML for human-editable config, JSON for machine-to-machine. |
| Data | `pandas` | Ubiquitous. `polars` as optional for large datasets. |
| Scientific | `numpy`, `scipy`, `scikit-learn` | Foundation stack for scientific computing. |
| Stats | `statsmodels`, `pingouin` | Comprehensive statistical modeling and testing. |
| PDF extraction | `pymupdf` | Fast, reliable, no Java dependency. |
| Session storage | `sqlite3` (stdlib) | Lightweight metadata queries. JSON files remain primary data exchange. |
| Visualization | `matplotlib`, `seaborn` | Universal. Agents generate plots for reports. |
| Testing | `pytest` | Standard. |
| Packaging | `pyproject.toml` + `hatch` | Modern Python packaging with PEP 621. |

### 2.2 Agent Architecture

Agents are coding agents. They use read/write/edit/bash tools to write Python scripts that `import urika`, run them, and produce structured results. The runtime provides the agent loop; Urika provides the scientific framework those scripts use.

```
Phase 1: Setup                    Phase 2: Execution
─────────────────                 ──────────────────────────────────────────

  System Builder                     Orchestrator
  (interactive)                      (deterministic Python loop)
       │                                  │
       │ generates config                 ├── spawns ──→ Task Agent(s)
       │                                  │                  │
       ▼                                  │                  ├─ writes Python scripts
  urika.toml                              │                  ├─ runs evaluations
  success_criteria.json                   │                  └─ records progress
  agents.json                             │
  knowledge/                              ├── spawns ──→ Evaluator
                                          │                  │
                                          │                  └─ validates metrics (read-only)
                                          │
                                          ├── spawns ──→ Suggestion Agent
                                          │                  │
                                          │                  ├─ analyzes results
                                          │                  ├─ searches literature
                                          │                  └─ writes suggestions
                                          │
                                          └── spawns ──→ Tool Builder
                                                             │
                                                             ├─ reads tool requests
                                                             ├─ creates tools
                                                             └─ tests & registers
```

**Agent communication is filesystem-based**:
- `results/sessions/<id>/progress.json` — Task agents write, evaluator/suggestion agents read
- `results/suggestions/*.json` — Suggestion agent writes, task agents read
- `results/leaderboard.json` — Evaluator writes, all agents read
- `results/tool_builder/tools_registry.json` — Tool builder writes, all agents read

Every inter-agent message is a JSON file on disk. Debuggable, resumable, auditable.

### 2.3 Agent Roles

**System Builder** — Runs during `urika init`. Interactive conversation to:
- Define research question, dataset paths, success criteria
- Ingest domain knowledge (papers, PDFs, URLs)
- Run automated literature review
- Configure agent team
- Output: `urika.toml`, `config/success_criteria.json`, `config/agents.json`

**Orchestrator** — Deterministic Python loop (not an LLM agent):
- Creates sessions, dispatches task agents, chains evaluation → suggestion → next task
- Enforces turn limits, checks criteria, determines termination
- Selects behavior based on investigation mode (exploratory/confirmatory/pipeline)

**Task Agent** — The workhorse:
- Reads investigation config and current progress
- Reads suggestions from suggestion agent
- Writes Python scripts that `import urika` to explore data, test methods, compute metrics
- Runs experiments via bash, records hypotheses, observations, next steps in `progress.json`
- Security: writable to `methods/` and `results/sessions/<id>/`, read-only to `evaluation/`

**Evaluator** — Read-only scoring:
- Runs evaluation metrics, validates against `success_criteria.json`
- Corrects agent-claimed success flags independently
- Cannot write to `methods/` or `tools/`

**Suggestion Agent** — Strategic analysis:
- Reads all results, runs analysis tools, searches web for papers
- Writes structured suggestions with priorities, categories, implementation sketches
- Can issue `tool_request` suggestions consumed by Tool Builder
- Writes to `results/suggestions/` only

**Tool Builder** — Dynamic capability extension:
- Reads tool requests from suggestion files
- Creates Python tools following the dual-API template (CLI + importable)
- Tests on data, registers in `tools_registry.json`
- Worker agents automatically pick up new tools via `load_tool_prefixes()`

**Literature Agent** — Knowledge acquisition:
- Searches academic databases, ArXiv, Google Scholar via web
- Fetches and parses PDF papers
- Builds indexed knowledge base in `knowledge/`
- Writes structured summaries with methods, findings, references

### 2.4 Orchestration Layer (runtime-specific)

The orchestration layer is the only part that changes between runtimes. It is responsible for:
- Spawning agent subprocesses with configured tools, prompts, and security boundaries
- Sequencing agents: task → evaluate → suggest → tool build → repeat
- Enforcing per-agent write permissions and bash command allowlists
- Managing turn limits and termination criteria

**v0.x (Claude Agent SDK)**: Uses `query()` to spawn agents, `can_use_tool` handler for security, `allowed_tools` for tool restriction, `bypassPermissions` for autonomous runs. See `docs/dev/option-a-claude-agent-sdk.md` for details.

**v1.x (Custom runtime)**: Custom agent loop with LLM provider abstraction (litellm or adapters), per-agent tool registries for security, tree-structured sessions. See `docs/dev/option-c-custom-runtime.md` for details.

### 2.5 Core Abstractions (runtime-independent)

**Two-level method system**:

```python
# Level 1: Universal (what the registry and runner care about)
class IAnalysisMethod(ABC):
    def name(self) -> str: ...
    def description(self) -> str: ...
    def category(self) -> str: ...           # "regression", "classification", "signal_processing"
    def default_params(self) -> dict: ...
    def set_params(self, params: dict): ...
    def get_params(self) -> dict: ...
    def run(self, data: DatasetView, context: AnalysisContext) -> MethodResult: ...

# Level 2: Domain-specific (typed signatures for specific domains)
class ITimeSeriesMethod(IAnalysisMethod):
    def analyze(self, signals: np.ndarray, sampling_rate: float,
                events: pd.DataFrame | None = None) -> MethodResult: ...

    def run(self, data, context):  # extracts typed data from generic DatasetView
        return self.analyze(data.data['signals'], data.metadata['sampling_rate'], ...)
```

**MethodResult**:
```python
@dataclass
class MethodResult:
    outputs: dict[str, Any]      # predictions, coefficients, etc.
    metrics: dict[str, float]    # computed quality metrics
    diagnostics: dict            # method-specific diagnostic info
    artifacts: list[str]         # paths to generated files (plots, tables)
    valid: bool                  # whether execution succeeded
```

**DatasetView**:
```python
@dataclass
class DatasetView:
    spec: DatasetSpec            # path, format, schema
    data: dict[str, Any]         # named data arrays/frames
    metadata: dict               # sampling rates, channel info, subject info
    summary: DataSummary         # n_rows, n_cols, dtypes, missing, distributions
```

**AgentConfig** (thin adapter — wraps runtime-specific config):
```python
@dataclass
class AgentConfig:
    name: str
    prompts_dir: Path
    writable_dirs: list[Path]
    readonly_dirs: list[Path]
    allowed_bash_prefixes: list[str]
    allowed_tools: list[str]
    results_dir: Path | None
    max_turns: int
    default_prompt: str
    continue_prompt: str
    success_criteria_key: str | None
    investigation_config: InvestigationConfig | None = None
    session_id: str | None = None
```

### 2.6 Evaluation Framework

**Metric registry** — Pluggable metrics with auto-discovery:
```python
class IMetric(ABC):
    def name(self) -> str: ...
    def compute(self, y_true, y_pred, **kwargs) -> float: ...
    def direction(self) -> str: ...  # "higher_is_better" | "lower_is_better"
```

Built-in metrics: RMSE, MAE, R2, accuracy, F1, AUC, AIC, BIC, Cohen's d, effect sizes, ICC.

**Success criteria validation**:
```python
def validate_criteria(metrics: dict, criteria: dict) -> tuple[bool, list[str]]:
    # Compares metric values against min/max thresholds
    # Entries with type="report_only" are tracked but don't gate success
    # Returns (passed, list_of_failures)
```

**Trust model** — The most important architectural property:
1. `evaluation/` is read-only for task agents (enforced by orchestration layer)
2. `success_criteria.json` is read-only for task agents
3. Orchestrator validates criteria independently after agent claims success
4. If agent lies about `criteria_met`, orchestrator corrects the flag on disk

**Leaderboard**:
```python
def update_leaderboard(investigation_root, method, metrics, run_id, params,
                       primary_metric, direction):
```

### 2.7 Investigation Modes

Three modes to handle the tension between exploratory and confirmatory science:

**Exploratory mode** (default): Try methods → evaluate → rank on leaderboard → suggest improvements → repeat. For prediction, classification, optimization problems.

**Confirmatory mode**: Pre-specify a single analysis → run → diagnostic checks → report. No leaderboard. No method shopping. Guardrails against p-hacking:
- Logs which analysis was pre-specified vs post-hoc explorations
- Recommends multiple comparison corrections when needed
- Transparency section in reports documenting all models attempted
- Run metadata distinguishes "pre-specified" from "exploratory follow-up"

**Pipeline mode**: Ordered preprocessing stages → analysis. For domains requiring multi-step preprocessing (EEG: filter → artifact reject → ICA → epoch → baseline correct → analyze). Composable `PipelineStage` + `Pipeline` with cached intermediate data.

```toml
# urika.toml
[investigation]
mode = "exploratory"   # "exploratory" | "confirmatory" | "pipeline"
```

### 2.8 Tool System

**Tool design principles**:
- Dual API: CLI (`python -m urika.tools.<name> --dataset <path>`) + importable
- Dataclass config with defaults
- JSON output, errors to stderr
- Safety classification: `read_only` or `write`

**Dynamic registry**:
- `load_tool_prefixes()` returns bash prefixes for tested tools
- Worker agents get new tool capabilities automatically
- Registry tracks: module, description, safety, tested flag, creation source

**Built-in tools** (ship with platform):

| Category | Tools |
|----------|-------|
| Exploration | data_profiler, distributions, correlations, missing_data, outliers |
| Statistics | descriptives, hypothesis_tests, effect_sizes, power_analysis |
| ML | pipeline_builder, cross_validation, hyperparameter_search, feature_importance |
| Time Series | preprocessing, decomposition, spectral, filtering, stationarity |
| Visualization | plot_builder, statistical_plots, report_builder |

### 2.9 Data System

**Format readers** — pluggable via `IDataReader` protocol:

| Reader | Formats | Required For |
|--------|---------|-------------|
| `tabular.py` | CSV, TSV, Excel, Parquet, SPSS, Stata | All domains (core) |
| `hdf5_reader.py` | HDF5, MAT v7.3 | Neuroscience, motor control |
| `json_reader.py` | JSON, JSON Lines | General |
| `edf_reader.py` | EDF, EDF+, BDF | EEG, polysomnography |
| `bids_reader.py` | BIDS format | Neuroimaging |
| `c3d_reader.py` | C3D | Motor control, biomechanics |
| `imu_reader.py` | Axivity CWA, ActiGraph GT3X | Wearable sensors |
| `audio_reader.py` | WAV, MP3 | Linguistics, speech |
| `point_cloud_reader.py` | DRC, PLY, PCD, LAS | Computer vision |

Core install includes `tabular.py` and `json_reader.py`. Others are optional dependencies via domain packs.

### 2.10 Knowledge Pipeline

```
User input              Processing                    Output
──────────              ──────────                    ──────
PDF papers    → pdf_extractor.py → text, tables  ─┐
ArXiv URLs    → literature.py → fetch + parse    ──┤
Web search    → literature.py → summaries        ──┤── knowledge/index.json
Dataset       → data/profiler.py → schema+stats  ──┤
User notes    → direct write                     ──┘
```

`knowledge/index.json` tracks: papers ingested, methods described, datasets profiled, methods tried.

### 2.11 Session & Experiment Management

```
results/
    sessions/
        session_001/
            session.json              # metadata: start, status, config
            progress.json             # run-by-run tracking
            evaluation/
                metrics.json          # evaluator output
                criteria_check.json   # pass/fail per criterion
            runs/
                run_001.json          # individual experiment results
        session_002/
            ...
    leaderboard.json                  # global method rankings
    suggestions/                      # cross-session suggestions
```

`progress.json` format:
```json
{
    "session_id": "session_001",
    "status": "in_progress",
    "criteria_met": false,
    "best_run": {"run_id": "run_003", "method": "xgboost_v2", "metrics": {"rmse": 0.042}},
    "runs": [
        {
            "run_id": "run_001",
            "method": "linear_regression",
            "params": {"alpha": 0.1},
            "metrics": {"rmse": 0.15, "r2": 0.72},
            "hypothesis": "Baseline linear model to establish floor",
            "observation": "R2=0.72, significant nonlinearity in residuals",
            "next_step": "Try tree-based methods for nonlinear relationships"
        }
    ]
}
```

---

## Part 3: Project Structure

```
urika/
    pyproject.toml                   # PEP 621, entry points, dependency groups
    README.md
    LICENSE                          # MIT
    CLAUDE.md
    docs/
        dev/
            option-a-claude-agent-sdk.md # Runtime option details
            option-b-build-on-pi.md      # Runtime option details
            option-c-custom-runtime.md   # Runtime option details

    src/urika/
        __init__.py
        __main__.py                  # CLI entry: python -m urika
        cli.py                       # click CLI with subcommands

        core/
            config.py                # InvestigationConfig, ProjectConfig
            investigation.py         # Investigation lifecycle
            pipeline.py              # Composable PipelineStage + Pipeline
            progress.py              # progress.json read/write
            registry.py              # Generic auto-discovery base
            protocols.py             # IAnalysisMethod, IMetric, IDataReader, ITool protocols
            exceptions.py

        agents/
            __init__.py
            orchestrator.py          # Deterministic orchestration loop (runtime-agnostic interface)
            security.py              # SecurityPolicy (runtime-agnostic interface)
            agent_config.py          # AgentConfig dataclass
            agent_registry.py        # Auto-discover agents from */run.py

            # Runtime adapters (only one active at a time)
            sdk_adapter.py           # v0.x: Claude Agent SDK implementation
            # custom_adapter.py      # v1.x: Custom runtime implementation (future)

            system_builder/          # Investigation setup agent
                run.py
                prompts/
                    system_prompt.md
                    iteration_prompt.md

            task_agent/              # Worker agent
                run.py
                prompts/

            evaluator/               # Read-only evaluation agent
                run.py
                prompts/

            suggestion_agent/        # Strategic analysis agent
                run.py
                prompts/

            tool_builder/            # Dynamic tool creation agent
                run.py
                prompts/

            literature_agent/        # Knowledge acquisition agent
                run.py
                prompts/

        evaluation/
            evaluator.py             # Metric computation
            metric_registry.py       # Pluggable metrics with auto-discovery
            criteria.py              # validate_criteria()
            runner.py                # Evaluation harness
            leaderboard.py           # Method ranking

        methods/
            base.py                  # IAnalysisMethod ABC
            registry.py              # discover_methods()
            statistical/             # Built-in statistical methods
            ml/                      # Built-in ML methods
            timeseries/              # Built-in time series methods

        tools/
            base.py                  # ITool ABC (dual CLI+API pattern)
            registry.py              # Dynamic tool registry
            builtin/                 # Shipped tools
                data_profiler.py
                correlation.py
                hypothesis_tests.py
                visualization.py

        data/
            dataset.py               # DatasetSpec, DatasetView, DataSummary
            loader.py                # Unified loader with format auto-detection
            schema.py                # Column mapping and schema inference
            readers/
                base.py              # IDataReader protocol
                tabular.py           # CSV, Excel, Parquet, SPSS, Stata
                json_reader.py

        knowledge/
            ingestion.py             # Unified document ingestion
            pdf_extractor.py         # PDF text + table extraction (pymupdf)
            literature.py            # Web search, paper fetching
            index.py                 # Knowledge index management

        sessions/
            manager.py               # Session lifecycle management
            comparison.py            # Cross-session comparison
            persistence.py           # SQLite session metadata store

    # Per-investigation workspace (created by `urika init`):
    # my-investigation/
    #     urika.toml
    #     data/
    #     knowledge/
    #     methods/                   # Investigation-specific methods (agent-writable)
    #     tools/                     # Investigation-specific tools (agent-writable)
    #     results/
    #         sessions/
    #         suggestions/
    #         leaderboard.json
    #     config/
    #         success_criteria.json
    #         agents.json

    tests/
        conftest.py
        test_core/
        test_agents/
        test_evaluation/
        test_methods/
        test_data/
        test_tools/
```

---

## Part 4: Implementation Plan

### Phase 0: Validation Spike (1-2 days)

Verify Claude Agent SDK can do what we need before committing:
- Spawn an agent with `query()`, confirm tool dispatch works
- Test `can_use_tool` handler for write boundary enforcement
- Confirm `bypassPermissions` propagation to subagents
- Write a minimal orchestrator that chains two agents

**Fail criteria**: If SDK can't enforce per-agent security boundaries, reassess runtime choice.

### Phase 1: Core Infrastructure

**1.1** `core/protocols.py` — Define `IAnalysisMethod`, `IMetric`, `IDataReader`, `ITool` protocols. `MethodResult` dataclass.

**1.2** `core/config.py` — `InvestigationConfig` dataclass with investigation mode. TOML loading/saving for `urika.toml`.

**1.3** `core/pipeline.py` — Composable `PipelineStage` + `Pipeline` with ordered stages and config save/load.

**1.4** `data/dataset.py` — `DatasetSpec`, `DatasetView` (with `ColumnSchema`, `DataStructure` for measurement levels and nesting), `DataSummary`.

**1.5** `data/loader.py` + `data/readers/tabular.py` — `DataLoader` with format auto-detection. CSV/Excel/Parquet reader.

**1.6** `methods/base.py` + `methods/registry.py` — `AnalysisMethod` ABC. `discover_methods()` auto-discovery.

### Phase 2: Evaluation Framework

**2.1** `evaluation/metric_registry.py` — `IMetric` ABC, `MetricRegistry` with auto-discovery. Built-in metrics: RMSE, MAE, R2, accuracy, F1, AUC, Cohen's d.

**2.2** `evaluation/criteria.py` — `Criterion` dataclass with `report_only` type support and stage-dependent criteria. `validate_criteria()`.

**2.3** `evaluation/runner.py` — `run_evaluation()`: loads data, runs method, computes metrics. Domain-agnostic.

**2.4** `evaluation/leaderboard.py` — `update_leaderboard()` parameterized by `primary_metric` and `direction`.

### Phase 3: Tool System

**3.1** `tools/base.py` + `tools/registry.py` — `ITool` ABC with dual CLI+API pattern. `load_tool_prefixes()` for dynamic discovery.

**3.2** Built-in tools:
- `data_profiler.py` — automated EDA: dtypes, distributions, missing, correlations
- `hypothesis_tests.py` — t-tests, ANOVA, Mann-Whitney, chi-squared
- `correlation.py` — Pearson, Spearman, correlation matrices
- `visualization.py` — plot generation: histogram, scatter, box, line, heatmap

### Phase 4: Built-in Methods

**4.1** `methods/statistical/` — Core methods: `linear_regression.py`, `logistic_regression.py`, `paired_t_test.py`, `mixed_anova.py`, `random_forest.py`, `xgboost_model.py`.

**4.2** Domain-specific base classes: `ITabularMethod`, `ITimeSeriesMethod` — extract typed data from `DatasetView`.

### Phase 5: Orchestration & Agents (runtime-specific)

**5.1** `agents/sdk_adapter.py` — Claude Agent SDK adapter: spawn agents via `query()`, enforce security via `can_use_tool`, manage `bypassPermissions`.

**5.2** `agents/orchestrator.py` — Deterministic loop: task → evaluate → criteria check → suggest → tool build → repeat. Investigation mode selection. Turn limits.

**5.3** `agents/security.py` — Runtime-agnostic `SecurityPolicy` interface. SDK-specific implementation in `sdk_adapter.py`.

**5.4** Agent `run.py` modules — Each agent: `get_config() -> AgentConfig` + `main()`.

**5.5** Agent system prompts — `system_prompt.md` and `iteration_prompt.md` for each agent role.

### Phase 6: CLI

**6.1** `cli.py` + `__main__.py`:
```
urika init <name>               # Create investigation workspace
urika run                       # Start/continue investigation
urika run --continue            # Resume last session
urika run --max-turns <n>       # Limit turns
urika status                    # Show investigation status
urika results                   # Show all results
urika compare <s1> <s2>         # Compare sessions
urika report                    # Generate final report
urika knowledge ingest <path>   # Ingest document
urika knowledge search <query>  # Search knowledge base
urika agents --list             # List available agents
urika tools --list              # List available tools
```

### Phase 7: Knowledge Pipeline

**7.1** `knowledge/pdf_extractor.py` — PDF text extraction via `pymupdf`
**7.2** `knowledge/literature.py` — Web search integration
**7.3** `knowledge/index.py` — Knowledge index management
**7.4** `literature_agent/` — Prompts and run.py

### Phase 8: Session Management

**8.1** `sessions/manager.py` — Create, list, resume, compare
**8.2** `sessions/persistence.py` — SQLite backing for fast queries
**8.3** `sessions/comparison.py` — Cross-session analysis

### Phase 9: Domain Packs (post-core)

Domain packs are separate optional installs. Each provides:
- Domain-specific method base classes
- Domain-specific metrics
- File format readers
- Pre-built analysis methods
- Domain-specific prompt templates

Priority order:
1. Survey/Psychometrics (most accessible, simplest data)
2. Cognitive Experiments (RT analysis, SDT)
3. Wearable Sensors (time series, classification)
4. Motor Control (kinematics, coordination)
5. Eye Tracking (fixation analysis, scanpaths)
6. Cognitive Neuroscience (EEG/fMRI, requires MNE)
7. Computer Vision/LiDAR
8. Linguistics (NLP, speech)
9. Epidemiology (survival, spatial)

### Phase 10: Custom Runtime Migration (v1.x)

Once the platform is complete, tested, and robust on the Claude Agent SDK:

**10.1** Implement custom agent loop — prompt → response → tool dispatch cycle in Python.
**10.2** Implement LLM provider abstraction — adapters for Claude, OpenAI, Google, open-source models (via litellm or custom).
**10.3** Implement core tools — read, write, edit, bash, glob, grep (the same tools the SDK provides).
**10.4** Implement session management — context window fitting, compaction, conversation history.
**10.5** `agents/custom_adapter.py` — Drop-in replacement for `sdk_adapter.py`.
**10.6** Migrate orchestrator to use custom adapter. Verify all existing tests pass.

Design inspiration from both Pi (model-agnostic provider registry, extension system, tree-structured sessions) and Claude Agent SDK (security model, tool permissions, subagent patterns).

### Phase 11: Packaging & Release

**11.1** `pyproject.toml` with dependency groups
**11.2** GitHub repo setup: README, LICENSE (MIT), CI (pytest + ruff), CLAUDE.md
**11.3** End-to-end test: CSV dataset → `urika init` → `urika run --max-turns 20` → results

---

## Part 5: Cross-Domain Design Validation

### How the Architecture Handles Each Domain

**Survey Data** (Likert scales, demographics)
- Reader: `tabular.py` (CSV/SPSS)
- Methods: `factor_analysis.py`, `linear_regression.py`, `mixed_anova.py`
- Metrics: Cronbach's alpha, CFI, RMSEA, R2
- Success criteria: e.g., `{"cfi": {"min": 0.95}, "rmsea": {"max": 0.06}}`
- Agent workflow: Profile data → check assumptions → run factor analysis → compare models → report

**Cognitive Experiments** (RT, accuracy)
- Reader: `tabular.py` (CSV from PsychoPy/E-Prime)
- Methods: `mixed_anova.py`, `linear_mixed_effects.py`, custom RT methods
- Metrics: effect size (Cohen's d), p-value, d-prime (SDT)
- Challenge: RT distributions are skewed → assumption checking triggers alternative methods
- Agent workflow: Profile RT distributions → test normality → try parametric/non-parametric → SDT analysis if applicable

**Wearable Sensor Data** (accelerometry, HR, EDA)
- Reader: `imu_reader.py` (domain pack), or `tabular.py` for pre-processed CSV
- Methods: time series methods + ML classifiers
- Metrics: classification accuracy, F1, RMSE for regression
- Challenge: High-frequency data, needs signal processing tools
- Agent workflow: Profile signals → spectral analysis → feature engineering → classification pipeline → cross-validation

**Motor Control** (kinematics, trajectories)
- Reader: `c3d_reader.py` (domain pack) or `tabular.py`
- Methods: coordination analysis, variability metrics, dynamical systems
- Metrics: movement time CV, path length ratio, phase coupling
- Challenge: Multi-trial, multi-condition designs → methods must handle nested structure
- Agent workflow: Segment movements → compute kinematics → analyze coordination → compare conditions

**EEG** (event-related potentials, spectral)
- Reader: `edf_reader.py` (domain pack)
- Methods: ERP analysis, time-frequency, MVPA
- Metrics: ERP amplitude/latency, classification accuracy, cluster p-values
- Challenge: Preprocessing pipeline (filtering, artifact rejection, ICA) before analysis
- Agent workflow: Preprocess → epoch → average → statistical analysis or decoding

**Eye Tracking** (fixations, saccades, AOIs)
- Reader: `tabular.py` (most eye trackers export CSV) or `eyelink_reader.py`
- Methods: fixation analysis, scanpath comparison, pupillometry
- Metrics: fixation count, dwell time, scanpath similarity
- Agent workflow: Detect events → AOI mapping → statistical comparison → visualization

---

## Part 6: Critical Gaps & Mitigations

### Gap 1: P-Hacking Risk (CRITICAL — ethical)

**Problem**: In exploratory mode, agents try many methods and report the best. Researchers must understand this is exploration, not confirmation.

**Mitigation**: Investigation modes (Section 2.7). Confirmatory mode with pre-registration and guardrails. Transparency reporting in all modes.

### Gap 2: No Preprocessing Pipeline Abstraction

**Mitigation**: `core/pipeline.py` (Phase 1.3) with composable stages. Pipeline mode for domains that need it.

### Gap 3: DatasetView Needs Richer Schema

**Mitigation**: `ColumnSchema` (measurement levels, roles) and `DataStructure` (subject nesting, temporal structure) in Phase 1.4.

### Gap 4: Success Criteria Aren't Always Numeric Thresholds

**Mitigation**: `report_only` criterion type, stage-dependent criteria in Phase 2.2.

### Gap 5: Domain Expertise in Prompts

**Mitigation**: Domain packs (Phase 9) include prompt templates, not just methods and tools.

---

## Part 7: Open Questions & Decisions

1. **Naming**: "Task Agents" vs "Analysis Agents" vs "Worker Agents"?
2. **Parallel task agents**: Multiple agents on different sub-problems, or sequential?
3. **Domain pack distribution**: Separate PyPI packages (`urika-neuro`, `urika-motor`) vs optional dependency groups in the main package?
4. **Knowledge persistence**: Pure JSON vs SQLite + optional vector store?
5. **Custom runtime timeline**: When is the platform "robust enough" to justify building the custom runtime? After first successful end-to-end investigation? After 3 domains validated?
