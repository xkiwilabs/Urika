# Project Builder Agent Design

**Date:** 2026-03-20
**Status:** Approved

## Problem

The current `urika new` is a simple CLI command that creates directories and writes a config file. It can't reason about data, ask clarifying questions, or scope initial tasks. For real projects (e.g., 480 CSVs in nested directories with papers and code alongside), we need an interactive agent session that understands the data and collaborates with the user to plan the project.

## Design

### Architecture

The project builder is **pure Urika code** with no SDK dependencies. It orchestrates data discovery, profiling, user interaction, and agent calls through the existing `AgentRunner` ABC.

```
urika new (CLI)
    │
    ▼
ProjectBuilder (Urika core)       ← pure Python, no SDK imports
    ├── scan_source_path()         ← classify files: data, docs, papers, code
    ├── profile_data()             ← uses urika.tools.data_profiler
    ├── generate_questions()       ← agent call via AgentRunner
    ├── run_suggestion_loop()      ← calls suggestion agent via AgentRunner
    ├── run_planning_loop()        ← calls planning agent via AgentRunner
    ├── ingest_knowledge()         ← uses urika.knowledge.KnowledgeStore
    └── write_project()            ← writes config, suggestions, tasks to disk
          │
          ▼
    AgentRunner (ABC)              ← abstract interface
          │
    ClaudeSDKRunner                ← current implementation
    (future: PiRunner, etc.)
```

User interaction happens at the CLI level (Click prompts), not through the SDK. This keeps the interactive loop SDK-independent.

### Entry Point

```bash
urika new "my-project" --data /path/to/data --description "Predict which target..."
```

If `--description` is omitted, the builder's first question is:
```
Tell me about this project — what are you trying to analyse or predict,
and what does your data represent?
```

The `--data` path can be a single file, a data directory, or a full research repo with papers, code, and data in subdirectories.

### Step 1: Intelligent Path Scanning

The builder scans the provided path and classifies what it finds:

- **Data files** — CSVs, parquet, Excel, etc. Grouped by directory structure.
- **Documentation** — README.md, text files, markdown docs.
- **Research papers** — PDFs in any subdirectory.
- **Code** — Python scripts, notebooks (existing processing/analysis code).

Reports to user:
```
Scanning /path/to/research-repo/...

Data files:
  datasets/HA_FOV_Angular/ — 480 CSVs (2Player: 300, 3Player: 180)

Documentation:
  README.md, datasets/README.md (column definitions)

Research papers:
  DH-Game-Information/Lam_2026_MRes_Thesis.pdf (44 MB)
  DH-Game-Information/Simpson_et_al_2026_*.pdf (3 files)

Code:
  datasets/clean_dht_data.py, datasets/HA_FOV_Processor.py
```

Asks:
1. "Is [detected path] the primary dataset?" — confirms data location
2. "Should I ingest the documentation and papers into the knowledge base?" — if yes, READMEs/text → knowledge store directly, PDFs → knowledge pipeline extractors, code → scanned for context

### Step 2: Data Profiling

Profiles a sample of data files (3-5 files from different parts of the structure):

- Runs `data_profiler` tool on sample files
- Identifies common schema across files, column types, missing values
- Flags schema inconsistencies between files
- Reports total row count estimate

Prints schema summary, asks: "Is this the right data? Anything to exclude?"

### Step 3: Research Question Scoping

The user's description (from CLI or first question) seeds this phase. The builder uses an agent call to analyze the data profile against the description and generate clarifying questions one at a time:

- "I see position/visibility data but no target selection labels. How should we define a target selection event?"
- "Should we model 2-player and 3-player teams separately or together?"
- "What metrics define success? e.g., prediction accuracy > 80%?"

Each answer feeds into context for the next question. Builder stops when it has enough to scope the project.

### Step 4: Interactive Suggestion → Planning Loop

Builder calls suggestion agent (with accumulated context), then planning agent. Presents the plan to the user:

```
Proposed initial plan:

Task 1: Derive target selection labels
  - Define selection as: player within X distance for 2+ seconds
  - Create preprocessing tool that adds 'selected_target' column

Task 2: Consolidate dataset
  - Merge 480 CSVs into unified DataFrame with session/trial metadata

Task 3: Feature engineering
  - Angular deviation, distance, visibility count, time-since-last-switch

Task 4: Baseline model
  - Logistic regression predicting target choice from features
  - 5-fold CV, stratified by participant (group_split)

Refine this plan, or type 'ok' to proceed:
```

User can:
- **Approve** → proceed to write project
- **Modify** → type corrections ("skip task 2, I want to keep files separate")
- **Ask questions** → "why logistic regression as baseline?"
- **Add suggestions** → "also try a random forest and an LSTM"
- **Loop** → runs suggestion → planning again with updated context

Continues until user is satisfied.

### Step 5: Write Project

On approval, the builder writes:

- `project_dir/urika.toml` — config with data source, research question, success criteria, description
- `project_dir/suggestions/initial.json` — seeded suggestions for first orchestrator loop
- `project_dir/tasks/initial.json` — scoped task list
- Standard directory structure: `experiments/`, `tools/`, `methods/`, `knowledge/`, `labbook/`
- Knowledge store populated with ingested docs/papers (if user approved)
- Registers project in `~/.urika/projects.json`

### Multi-File Dataset Support

**urika.toml data config:**
```toml
[data]
source = "/path/to/data/directory"
format = "csv_directory"
pattern = "**/*.csv"
```

**Data loader changes:**
- New `load_dataset_directory()` function that reads matching files and concatenates into one DataFrame
- Adds source file metadata columns (filename, subdirectory)
- Can also load individual files when needed
- Existing `load_dataset()` for single files remains unchanged

### What the Builder Does NOT Do

- Run experiments — that's `urika run`
- Write method or tool code — that's the task agent
- Evaluate results — no evaluator during setup
- Make irreversible decisions without user confirmation

### What Changes

| Component | Change |
|-----------|--------|
| `src/urika/core/project_builder.py` | New: ProjectBuilder class with scan/profile/question/plan loop |
| `src/urika/data/loader.py` | Add: `load_dataset_directory()` for multi-file datasets |
| `src/urika/data/models.py` | Update: `DatasetSpec` to support directory sources |
| `src/urika/cli.py` | Update: `urika new` to launch interactive builder session |
| `src/urika/core/workspace.py` | Update: support new data config format in urika.toml |
| `src/urika/core/models.py` | Update: `ProjectConfig` to include description, data source config |
| Agent prompts | Update: project_builder prompt for interactive scoping |
| Tests | New tests for ProjectBuilder, directory loader, updated CLI |
