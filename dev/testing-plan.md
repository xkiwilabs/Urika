# Comprehensive Testing Plan

## Test Datasets (6 projects, simple → complex)

### 1. Simple Statistics — Stroop Task (Cognitive Psychology)
**Source:** [Lakens/Stroop on GitHub](https://github.com/Lakens/Stroop) (CSV)
**Data:** ~200 participants, congruent vs incongruent reaction times
**Question:** "Is there a significant Stroop effect — do incongruent trials produce slower reaction times than congruent trials?"
**Mode:** Confirmatory
**Tests:** Paired t-test, effect sizes, basic stats. Simplest possible project — validates the core workflow.
**Privacy mode:** Open

### 2. Clinical/Survey — Depression Assessment
**Source:** [The Depression Dataset on Kaggle](https://www.kaggle.com/datasets/arashnic/the-depression-dataset) (CSV)
**Data:** Survey responses, demographics, depression indicators
**Question:** "Which demographic and lifestyle factors best predict depression severity?"
**Mode:** Exploratory
**Tests:** Regression, feature importance, mixed methods. Tests multi-method exploration and criteria evolution.
**Privacy mode:** Hybrid (sensitive health data — test the Data Agent flow)

### 3. Marketing Analytics — Customer Segmentation
**Source:** [Customer Segmentation Dataset on Kaggle](https://www.kaggle.com/datasets/yasserh/customer-segmentation-dataset) (CSV)
**Data:** Customer demographics, spending scores, income
**Question:** "What distinct customer segments exist and what characterises each group?"
**Mode:** Exploratory
**Tests:** Clustering (unsupervised), tool builder creating new tools, non-prediction task. Tests Urika beyond supervised learning.
**Privacy mode:** Open

### 4. Modelling — Boston Housing (Regression)
**Source:** scikit-learn `fetch_openml("boston")` or Kaggle alternatives (CSV)
**Data:** ~500 rows, housing features, median value target
**Question:** "Which features most strongly predict housing prices and what is the best achievable prediction accuracy?"
**Mode:** Pipeline
**Tests:** Linear regression → random forest → XGBoost progression. Tests leaderboard, method comparison, criteria thresholds. Classic ML benchmark.
**Privacy mode:** Open

### 5. Text Analysis — Sentiment/NLP
**Source:** [IMDB Reviews](https://www.kaggle.com/datasets/lakshmi25npathi/imdb-dataset-of-50k-movie-reviews) or similar (CSV with text)
**Data:** 50K movie reviews with sentiment labels
**Question:** "Can review text predict sentiment, and which text features are most discriminative?"
**Mode:** Exploratory
**Tests:** Tool builder creating NLP tools (TF-IDF, embeddings), non-tabular data handling, pip installing NLP packages. Tests the build-tool command.
**Privacy mode:** Open

### 6. Image Data — Basic Classification
**Source:** [CIFAR-10](https://www.kaggle.com/datasets/pankajkumar2002/cifar10) or a smaller set like [Flowers Recognition](https://www.kaggle.com/datasets/alxmamaev/flowers-recognition) (image files)
**Data:** Labelled images in subdirectories
**Question:** "Can we classify images into categories using extracted features?"
**Mode:** Pipeline
**Tests:** Non-tabular data detection, image profiling, tool builder creating feature extractor, multidisciplinary data handling. Tests the expanded scanner and data format support.
**Privacy mode:** Open


## Testing Checklist

### Phase 1: Core Workflow (use Dataset 1 — Stroop)

- [ ] `urika new stroop-study --data <path>`
  - [ ] Scanner detects CSV files
  - [ ] Profiler shows row/column count
  - [ ] Project builder asks about data collection methods
  - [ ] Project builder asks up to 10 questions, stops when ready
  - [ ] Web search prompt appears (say No)
  - [ ] Venv prompt appears (say No)
  - [ ] Knowledge guidance appears (no papers in data path)
  - [ ] Project created successfully
- [ ] `urika` (launch REPL)
  - [ ] Header displays correctly (centered, blue)
  - [ ] `/help` shows all commands
  - [ ] `/project stroop-study` loads project
  - [ ] `/status` shows project info
  - [ ] `/tools` lists 16 built-in tools
  - [ ] Tab completion works for commands and project names
- [ ] `/run`
  - [ ] Settings review shows max_turns from urika.toml
  - [ ] Spinner shows during agent calls with session info on right
  - [ ] Tool streaming shows (Read, Write, Bash events)
  - [ ] ThinkingPanel displays during orchestrator
  - [ ] Experiment completes
- [ ] `/results` — shows leaderboard or runs
- [ ] `/methods` — shows agent-created methods
- [ ] `/logs` — experiment selection, then run details
- [ ] `/report` — experiment selection (specific/all/project)
- [ ] `/present` — generates reveal.js presentation
- [ ] `/criteria` — shows current criteria
- [ ] `/usage` — shows session stats
- [ ] `/knowledge` — lists entries (empty initially)
- [ ] Free text input: "what should I try next?" — advisor responds
- [ ] `/quit` — saves usage, exits cleanly

### Phase 2: CLI Parity (use Dataset 1)

- [ ] `urika status stroop-study`
- [ ] `urika results stroop-study`
- [ ] `urika methods stroop-study`
- [ ] `urika report stroop-study` — experiment selection prompt
- [ ] `urika present stroop-study` — experiment selection + spinner
- [ ] `urika logs stroop-study` — experiment selection
- [ ] `urika advisor stroop-study "what methods work best for RT data?"`
- [ ] `urika evaluate stroop-study`
- [ ] `urika plan stroop-study`
- [ ] `urika criteria stroop-study`
- [ ] `urika usage stroop-study`
- [ ] `urika build-tool stroop-study "create a Cohen's d effect size tool"`

### Phase 3: Privacy/Hybrid (use Dataset 2 — Depression)

- [ ] Create project with hybrid mode manually in urika.toml:
  ```toml
  [privacy]
  mode = "hybrid"

  [privacy.endpoints.private]
  base_url = "http://localhost:11434"
  ```
- [ ] Install Ollama and pull `gpt-oss:20b` (or smallest available model)
- [ ] Run experiment — verify Data Agent runs on local model
- [ ] Verify other agents run on cloud Claude
- [ ] Check that raw data values don't appear in cloud agent outputs

### Phase 4: Venv (use Dataset 3 — Marketing)

- [ ] `urika new marketing-segments --data <path>` — say Yes to venv
- [ ] Verify `.venv/` created in project directory
- [ ] `urika venv status marketing-segments` — shows enabled
- [ ] Run experiment — agents pip install into project venv
- [ ] `urika venv status marketing-segments` — still shows enabled

### Phase 5: Tool Builder (use Dataset 5 — Text)

- [ ] `urika build-tool text-analysis "install scikit-learn and create a TF-IDF vectorizer tool"`
- [ ] Verify tool created in project's `tools/` directory
- [ ] `/tools` shows the new tool alongside built-ins
- [ ] Run experiment — agent uses the custom tool

### Phase 6: Non-Tabular Data (use Dataset 6 — Images)

- [ ] `urika new image-classify --data <path to images>`
- [ ] Scanner detects image files with count and formats
- [ ] Image profiler shows dimensions
- [ ] Project builder asks about image-specific details
- [ ] Agent builds image feature extraction tool during experiment

### Phase 7: Meta-Orchestrator (use Dataset 4 — Housing)

- [ ] `urika run housing-prices --max-experiments 3 --auto`
- [ ] Verify multiple experiments run in sequence
- [ ] Each experiment builds on previous results
- [ ] Leaderboard tracks methods across experiments

### Phase 8: Knowledge Pipeline (use Dataset 2 — Depression)

- [ ] Add a relevant PDF paper to `knowledge/papers/`
- [ ] `urika knowledge ingest depression-study <path to paper>`
- [ ] `urika knowledge list depression-study` — shows ingested paper
- [ ] `urika knowledge search depression-study "BDI assessment"` — finds content
- [ ] Run experiment — literature agent references the paper


## Expected Outcomes

After testing all 6 datasets, you should have:
- 6 projects in `~/urika-projects/`
- Each with experiments, methods, reports, and presentations
- Confidence that CLI and REPL produce consistent results
- Verified privacy/hybrid mode works
- Verified venv isolation works
- Verified non-tabular data detection works
- A collection of real outputs suitable for tutorials and documentation
