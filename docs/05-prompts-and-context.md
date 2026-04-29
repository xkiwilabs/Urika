# Prompts and Context Engineering

The quality of Urika's analysis depends heavily on the context you provide. This guide shows how to write effective project descriptions, instructions, and build useful knowledge bases.


## Why Context Matters

Urika's agents make decisions based on what they know about your project. At every stage -- planning, task execution, evaluation, advising -- agents read the project description, data profile, criteria, and knowledge base to decide what to do next. More specific context produces better analytical choices.

Consider the difference:

- **Vague description:** "Analyse this dataset." The planning agent has no basis for choosing between dozens of possible approaches. It falls back to generic methods, tries a scatter-gun of techniques, and may waste experiments on irrelevant approaches.
- **Detailed description:** "Predict student exam performance from study habits. 500 students, repeated measures, expect conscientiousness r≈0.25. Use hierarchical regression, check multicollinearity." The planning agent immediately designs a targeted pipeline. The task agent writes appropriate code. The evaluator knows what metrics matter.

The project description, your answers during the interactive setup, the `--instructions` flag, and ingested knowledge documents all feed into this context. Everything you provide becomes available to every agent in the loop.


## Writing Project Descriptions

The project description (set via `--description` or during `urika new`) is the single most important input you provide. It shapes every analytical decision the agents make.

### Structure

The best descriptions include four components:

1. **What the data IS** -- source, collection method, sample size, key variables, known issues
2. **What you're trying to FIND** -- specific research question, target metric if applicable
3. **What you already KNOW** -- prior findings, expected relationships, relevant literature
4. **Any CONSTRAINTS** -- methods to use or avoid, assumptions to check, evaluation strategy

You don't need to write an essay. A few well-chosen sentences covering these four points will outperform a page of vague prose.

### Examples by Domain

**Statistical Analysis Example:**

```
Data: Survey responses from 450 undergraduate students measuring Big Five
personality traits (NEO-FFI, 60 items, 5-point Likert) and academic performance
(GPA, course grades). Collected at University of X, 2024. Some missing data
(~8% MCAR). Demographics: age, gender, major.

Question: Which personality traits predict academic performance, controlling
for demographics? Is conscientiousness the strongest predictor as prior
literature suggests?

Context: Previous studies (Roberts et al., 2007) show conscientiousness
r≈0.25 with GPA. We expect similar but want to test if openness adds
incremental validity for STEM vs humanities majors.

Constraints: Use hierarchical regression (demographics first, then traits).
Check multicollinearity. Report effect sizes (Cohen's f²). Must use proper
train/test split or cross-validation for any predictive models.
```

**Machine Learning Example:**

```
Data: 12,000 customer records with 45 features (demographics, purchase
history, engagement metrics, support tickets). Binary outcome: churned
within 6 months (yes/no). Class imbalance: ~15% churned. From internal
CRM, Jan 2023 - Dec 2024.

Question: Build a churn prediction model with F1 ≥ 0.70 on the minority
class. Identify top 10 predictive features for business actionability.

Context: Current rule-based system catches ~40% of churners. We need a
model that can be deployed for weekly batch scoring.

Constraints: Must handle class imbalance (SMOTE, class weights, or
undersampling). Use stratified k-fold cross-validation. Compare at least
3 model families (logistic, tree-based, gradient boosting). Report
precision-recall curves, not just accuracy.
```

**Deep Learning Example:**

```
Data: 8,500 labeled chest X-ray images (256x256 PNG), 3 classes: normal,
pneumonia, COVID-19. From public dataset (COVID-Chestxray). Train/val/test
split already provided in directory structure.

Question: Classify images with ≥85% macro F1. Compare transfer learning
approaches (ResNet, EfficientNet, ViT).

Context: Previous work on this dataset achieves ~90% with ResNet-50
fine-tuning. We want to test if vision transformers improve on this.

Constraints: GPU available (RTX 3090, 24GB VRAM). Use data augmentation
(rotation, flip, brightness). Report per-class metrics, not just overall.
Save confusion matrices as artifacts.
```

**Neuroscience Example:**

```
Data: 32-channel EEG recordings (BioSemi, 512 Hz) from 24 participants
performing an oddball task. Each participant has ~200 standard and ~50
deviant trials. Data in EDF format with event markers.

Question: Is the P300 ERP component larger for deviant vs standard stimuli?
Does this effect correlate with behavioral accuracy?

Context: Classic P300 effect expected at Pz electrode, 300-500ms window.
Previous studies show ~5μV difference.

Constraints: Must preprocess: bandpass filter 0.1-30 Hz, re-reference to
average, reject artifacts >100μV, epoch -200 to 800ms. Use cluster-based
permutation tests for statistical comparison. pip install mne for EEG
processing.
```


## Writing Instructions for Agents

Beyond the project description, you can guide agents at runtime using instructions. These can be passed via the `--instructions` flag on `urika run`, typed into the TUI, or provided during the interactive setup.

### Steering the Advisor Agent

The advisor agent proposes what to try next between experiments. Steer it with specific guidance:

- "Focus on non-parametric methods -- the data violates normality assumptions"
- "Prioritize interpretability over raw performance"
- "We already tried random forest -- explore boosting methods next"
- "Review the ingested papers on DHT target selection and use their methodology as a starting point"

```bash
urika run my-project --instructions "focus on non-parametric methods, the data violates normality"
```

### Steering Experiment Runs

Within the TUI or via `--instructions`, you can guide specific aspects of analysis:

- "Use leave-one-subject-out cross-validation since we have repeated measures"
- "Try both frequentist and Bayesian approaches for the hypothesis test"
- "Start with feature selection -- 45 features is too many for 200 samples"

```bash
urika run my-project --instructions "start with feature selection, we have too many features for the sample size"
```

### Requesting Custom Tools

The tool builder agent creates project-specific tools on demand. You can request tools explicitly:

- "Build a tool that computes inter-rater reliability (Cohen's kappa, ICC) using pingouin"
- "Create a data loader for our custom HDF5 format -- each file has 'signals' (32x1024 array) and 'events' (DataFrame)"

```bash
urika build-tool my-project "Create a tool that loads our custom HDF5 format with 'signals' and 'events' groups"
```


## Using the Knowledge Pipeline

### Why Ingest Papers?

Papers give agents domain expertise they wouldn't otherwise have. When you ingest a methodology paper, the planning agent can reference specific techniques, the advisor can suggest approaches from the literature, and the task agent can implement published algorithms.

Without domain knowledge, agents rely on generic analytical patterns. With even one or two relevant papers, they can:

- Choose methods that are established in your field rather than generic approaches
- Understand domain-specific terminology in your data
- Reference prior work when designing experiments
- Avoid reinventing approaches that have already been tried

### What to Ingest

1. **Methodology papers** -- Papers describing analytical approaches for your type of data
2. **Data description documents** -- Codebooks, data dictionaries, collection protocols
3. **Previous analyses** -- Prior results on similar data, benchmark studies
4. **Domain guides** -- Best practice guides for your field

### Examples

```bash
# Ingest a paper that describes the analytical approach you want to try
urika knowledge ingest my-project ~/papers/smith-2024-random-forests-for-clinical-prediction.pdf

# Ingest a data codebook so agents understand variable meanings
urika knowledge ingest my-project ~/data/codebook.md

# Ingest from a URL
urika knowledge ingest my-project https://example.com/eeg-analysis-best-practices

# Then tell the advisor to use it
urika run my-project --instructions "Review the ingested papers, especially Smith 2024, and use their cross-validation strategy"
```

### Building Knowledge Iteratively

You don't need to ingest everything upfront. Add knowledge as you discover what the agents need:

```
# During an experiment run, in the TUI:
urika:my-project> The results look strange for the interaction effect.
                   Can you look at the Smith 2024 paper methodology?

# Add more knowledge as you learn what's needed:
/knowledge ingest ~/papers/additional-reference.pdf

# The advisor will incorporate new knowledge in the next experiment
/run
```

See [Knowledge Pipeline](10-knowledge-pipeline.md) for full details on ingestion, search, and storage.


## How Context Flows Through the System

Understanding where your context ends up helps you write more effective descriptions and instructions.

### What the Planning Agent Sees

The planning agent reads the project configuration (`urika.toml`), the data profile, previous run results, the method registry, and success criteria. It uses all of this to design analytical pipelines. When you mention specific methods or evaluation strategies in your description, the planning agent picks them up directly.

### What the Task Agent Sees

The task agent receives the planning agent's method plan plus the full project context. It reads the project directory, data files, and any artifacts from previous runs. Domain-specific details in your description (library names, preprocessing steps, data format notes) help the task agent write correct code on the first try.

### What the Advisor Sees

The advisor reviews all run results, the evaluator's scores, and the full project context when proposing next steps. Instructions you provide via `--instructions` or the TUI are incorporated into the advisor's prompt. Referencing specific papers or methods by name lets the advisor make targeted suggestions.

### Knowledge Context

When the knowledge store contains entries, the literature agent summarizes relevant knowledge before the first turn. This summary is prepended to the task prompt, making domain knowledge available to all agents in the loop.


## Context Tips

### Do

- Be specific about expected effect sizes and prior results
- Mention statistical assumptions that need checking
- Specify the evaluation strategy (cross-validation type, metrics)
- Reference specific papers or methods by name
- Describe variable types (ordinal, nominal, continuous) and measurement scales
- Mention data collection procedures and potential confounds
- Describe non-tabular data formats and structure explicitly
- Include library suggestions for domain-specific data (`mne` for EEG, `librosa` for audio)

### Don't

- Use vague descriptions like "analyse this data"
- Assume agents know your field's conventions
- Skip mentioning the train/test evaluation strategy for ML
- Forget to mention class imbalance, missing data, or nested structure
- Leave out constraints (these prevent wasted experiments)
- Assume agents will figure out complex data formats without guidance


## Quick Reference: Description Template

```
Data: [source, format, N rows/files, key variables, collection method, known issues]

Question: [specific, measurable research question with target metric if applicable]

Context: [prior findings, expected results, relevant literature]

Constraints: [evaluation strategy, methods to use/avoid, assumptions to check,
domain requirements]
```

Copy this template and fill it in when creating a new project. Even a few sentences per section will dramatically improve your results.

---

**Next:** [Running Experiments](06-running-experiments.md)
