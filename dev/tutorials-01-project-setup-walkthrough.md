# Tutorial: Setting Up a Project — DHT Target Selection

This walkthrough shows the end-to-end process of creating a Urika project, from initial setup through to the first experiment plan. We use a real dataset from the Desert Herding Task (DHT) — a multiplayer game where teams herd autonomous target agents into a containment zone.

## Prerequisites

```bash
pip install -e ".[dev]"
```

## Step 1: Start Project Creation

```bash
urika new
```

Urika displays a branded header and prompts for project details:

```
╭─ Urika ─────────────────────────────────────╮
│  Multi-agent scientific analysis platform  │
╰────────────────────────────────────────────╯

Project name: dht-target-selection-v2
```

## Step 2: Point to Your Data

The data path can be a single file, a data directory, or an entire research repository with papers, code, and data in subdirectories. Urika will scan and classify everything it finds.

```
Path to data (file or directory) []: /path/to/DHT-Target-Selection-Modelling
```

## Step 3: Describe the Project

Provide a clear description of what you're trying to analyse or predict. This seeds the agent's understanding of the research context.

```
Describe the project — what are you trying to analyse or predict []:
Model target selection decisions in the Desert Herding Task (DHT) from the
player's local perspective. Players in 2-player and 3-player teams herd
autonomous target agents into a containment zone. Predict which target a
player will pursue next based on their first-person view — field-of-view
visibility, angular deviation, and distance. Global information models
(using all target positions regardless of visibility) serve as comparison
baselines, but the primary goal is understanding decisions from what the
player can actually see.
```

## Step 4: Research Question

Frame the specific research question:

```
Research question: How do players select their next target in a multiplayer
herding task — can target choice be predicted from the player's local
first-person perspective (visible targets, angular deviation, distance),
and how does this compare to predictions using global omniscient information?
```

## Step 5: Investigation Mode

```
Investigation mode:
  1. exploratory (default, press enter)
  2. confirmatory
  3. pipeline
Choice [1]: 1
```

## Step 6: Data Scanning

Urika scans the source path and classifies what it finds — data files, documentation, research papers, and code:

```
Data files: 961
  datasets/target-selection-lam2025/data/2-player/S201/ — 24 files
  datasets/target-selection-lam2025/data/2-player/S202/ — 24 files
  ...
  datasets/target-selection-lam2025/data/3-player/S317/ — 24 files
Documentation: 3
  README.md
  datasets/target-selection-lam2025/README.md
  requirements.txt
Research papers: 7
  DH-Game-Information/Lam_2026_MRes_Thesis.pdf
  DH-Game-Information/Simpson_et_al_2026_Can_an_AI_Agent_Lead_Human_Teams.pdf
  ...
Code files: 3
  datasets/target-selection-lam2025/scripts/build_annotations.py
  datasets/target-selection-lam2025/scripts/build_trajectories.py
  datasets/target-selection-lam2025/scripts/playback_trial.py

✓ Data profile: 562 rows, 88 columns
```

## Step 7: Interactive Project Scoping

The project builder agent analyses the data profile and research description, then asks clarifying questions one at a time. You should see output similar to the following — the exact questions may vary.

### Question 1: Prediction Point

```
What is the prediction point — when exactly should the model predict the
next target?

  1. A — At transition points (end of episode), predict next target
  2. B — Every timestep, predict current/next pursued target
  3. C — At episode start, predict which target was selected
```

**Example response:** "We want to build a model that predicts both when a transition will occur and to what target. At the beginning this is just the first target, but then after that, targets are selected either after they are contained or players switch between targets corralling them back and forth. We don't need to predict at every timestep, but given the current or some small history of state content (environment states) it predicts the next target. This could also be as a function of prediction horizon, so 2 seconds from now, or 5 seconds from now."

### Question 2: Team Conditions

```
Should the 2-player and 3-player conditions be modelled separately or
combined into a single model?

  1. Separate models for each condition
  2. One combined model with team-type as a feature
  3. Start separate, then compare whether combining helps
```

**Example response:** 3

### Question 3: Data Splitting

```
How should the data be split for training and evaluation?

  1. A — Split by session (generalise to new teams)
  2. B — Split by trial within session
  3. C — Random split across all events
  4. Nested — session-level outer fold with trial-level inner fold
```

**Example response:** "A is the primary split, but the other splits could be done for comparison purposes."

### Question 4: Modelling Approach

```
What initial modelling approach would you prefer?

  1. Logistic regression / multinomial logit
  2. Conditional logit (discrete choice model)
  3. Gradient-boosted trees (XGBoost/LightGBM)
  4. Start simple and escalate
```

**Example response:** 4

### Question 5: Teammate Information

```
Should the local (first-person) model include information about teammates?

  1. A — No teammate info (pure egocentric)
  2. B — Visible teammate info only (within 102° FOV)
  3. C — Always include teammate info
  4. Build all three as nested models
```

**Example response:** "B, but also C, where we have a memory function for teammates that dissipates over time. Could have a similar memory dissipation for targets that were in view but then are not. The latter could be fast dissipation, teammates slower."

## Step 8: Suggestion and Planning Agents

After the questions, Urika runs the suggestion agent (which reads the research papers and data) followed by the planning agent. These produce a detailed experimental plan.

You should see output similar to:

```
◆ Generating suggestions…
◆ Designing method…
```

The agents will propose a structured plan — typically 2-3 experiments building on each other, with a feature extraction pipeline, heuristic baselines, and progressively more complex models.

## Step 9: Approve or Refine

```
What would you like to do?
  1. Looks good — create the project (default, press enter)
  2. Refine — I have suggestions
  3. Abort
Choice [1]: 1
```

## Step 10: Knowledge Ingestion

```
Ingest documentation and papers into the knowledge base? [Y/n]: Y
Ingested 10 files into knowledge base.
✓ Created project 'dht-target-selection-v2'
```

## What Was Created

```
~/urika-projects/dht-target-selection-v2/
├── urika.toml          # Project config (name, question, mode, data source)
├── criteria.json       # Initial criteria (exploratory, will evolve)
├── methods.json        # Method registry (empty, populated during runs)
├── data/               # For agent-generated preprocessed data
├── methods/            # For agent-created method pipelines
├── tools/              # For agent-created tools
├── knowledge/          # Ingested papers and docs
├── experiments/        # Created when you run experiments
├── projectbook/        # Project-level reports
└── suggestions/        # Initial plan from project builder
    └── initial.json
```

## Next Steps

From here you can:

```bash
# Launch the interactive REPL
urika

# Or run the first experiment directly
urika run dht-target-selection-v2 --max-turns 5

# Check project status
urika status dht-target-selection-v2

# View results after a run
urika results dht-target-selection-v2
urika report dht-target-selection-v2

# Generate a presentation
urika present dht-target-selection-v2
```
