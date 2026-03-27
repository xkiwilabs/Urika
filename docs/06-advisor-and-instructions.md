# Advisor Chat and Instructions

The advisor agent serves two roles in Urika. Inside the experiment loop, it analyzes results after each turn and proposes what to try next. Outside the loop, it is available as a conversational research partner that you can consult at any time -- before your first experiment, between runs, or whenever you want to rethink your approach.

This guide covers both roles and shows how to use instructions to steer agents effectively.


## Talking to the Advisor

You can chat with the advisor whenever a project is loaded. The advisor sees your full project context -- data profile, methods tried, run results, criteria, and knowledge base -- so it can give informed, specific guidance.

### In the REPL

Any text that does not start with `/` is sent to the advisor:

```
urika:my-project> I think the linear models have plateaued. What should I try next?

  [advisor_agent]
  Based on your results (ridge r2=0.51, lasso r2=0.48), linear models
  are likely at their ceiling for this feature set. I recommend:

  1. Gradient boosting (XGBoost/LightGBM) — handles non-linear
     interactions without explicit feature engineering
  2. Random forest with feature importance — identify which features
     drive prediction before trying more complex models
  3. Feature engineering pass — create interaction terms for the
     top-5 correlated features, then re-run ridge as a sanity check

  Would you like me to run these experiments?
```

You can also use the explicit command:

```
urika:my-project> /advisor Should I try neural networks given only 500 samples?
```

The REPL maintains a rolling conversation history (last 10 exchanges), so the advisor remembers what you discussed earlier in the session.

### From the CLI

```bash
urika advisor my-project "What methods should I try next?"
urika advisor my-project "Should I add interaction terms given the correlation structure?"
```

If you omit the text argument, you are prompted to enter it interactively.

After the advisor responds, it offers to run its suggestions immediately (see below).


## When to Use Advisor Chat

The advisor is most valuable at these key moments:

### Before the First Experiment

After creating a project with `urika new`, chat with the advisor before running anything:

```
urika:my-project> Given the data profile and my research question, what analytical
                   strategy would you recommend? Should we start with baselines or
                   go straight to the methods I described?
```

This lets you validate the initial plan and refine it before spending compute.

### Between Experiments

After an experiment completes, review the results and discuss next steps:

```
urika:my-project> /results
  ... (leaderboard shows random forest at r2=0.67) ...

urika:my-project> The random forest is doing well but I'm worried about overfitting.
                   Can we try regularized approaches and compare out-of-sample?

  [advisor_agent]
  Good instinct. The gap between training r2=0.89 and test r2=0.67 suggests
  overfitting. I recommend...
```

### To Change Research Direction

If your understanding of the problem evolves, tell the advisor:

```
urika:my-project> After looking at the feature importances, I think we should
                   reframe this as a classification problem (high/low) rather than
                   regression. The continuous outcome has a bimodal distribution.
```

The advisor will adjust its suggestions accordingly, and these carry through to subsequent runs.

### To Refine Criteria

```
urika:my-project> Our initial criteria were exploratory. Now that we have baselines,
                   I want to set a concrete target: r2 >= 0.75 with interpretable
                   features. Can you update the criteria?
```

The advisor can update project criteria directly, which changes what the evaluator checks in future runs.

### To Request Tools or Approaches

```
urika:my-project> I need the agents to use mixed-effects models for this nested data.
                   Can you make sure the next experiment uses lme4-style models via
                   statsmodels or pymer4?

urika:my-project> We should build a custom preprocessing tool for our EEG data
                   before running more experiments. Can you plan that?
```

### To Review What Has Been Tried

```
urika:my-project> Summarize what we've learned so far across all experiments.
                   Which approaches worked, which didn't, and what's left to try?
```


## Running Advisor Suggestions

When the advisor proposes experiments, Urika offers to run them immediately. This applies in both the REPL and CLI.

### In the REPL

After the advisor responds with suggestions:

```
  The advisor suggests 3 experiments:
    1. gradient-boosting-exploration — Try XGBoost and LightGBM with default params
    2. feature-interaction-models — Add polynomial and interaction features
    3. ensemble-stacking — Stack top-3 models with a meta-learner

  Run the first suggestion? [Y/n]
```

Choosing **Y** creates the experiment and starts the run immediately. After it completes, you can run the next suggestion by typing `/run` -- the remaining suggestions are queued.

### From the CLI

```bash
urika advisor my-project "What should I try next?"
```

After the advisor responds:

```
  Run suggested experiments? [Y/n]
```

Choosing **Y** creates and runs the first suggested experiment.


## Providing Instructions

Instructions are free-text guidance that steer what agents do. They can be provided at several points and flow through to different parts of the system.

### Commands That Accept Instructions

| Command / Input | How instructions are provided | What they steer |
|-----------------|-------------------------------|-----------------|
| `urika run --instructions TEXT` | `--instructions` flag | The planning agent's method design for the next experiment |
| `urika finalize --instructions TEXT` | `--instructions` flag | Which methods the finalizer emphasizes and how it structures deliverables |
| `/run` in the REPL | Custom settings prompt, or automatically from conversation context | The planning agent, carried through the full experiment loop |
| Free text in the REPL | Type naturally | The advisor's suggestions, which feed into the next `/run` |
| `urika advisor PROJECT TEXT` | The text argument | The advisor's analysis and suggestions |
| `/build-tool TEXT` | The text argument | What tool the tool builder creates |
| `/advisor TEXT` | The text argument | The advisor's response |

### How Instructions Flow Through Experiments

When you provide instructions (via `--instructions`, REPL conversation, or the advisor's suggestions), they flow through the full experiment loop:

```
Your instructions
       |
       v
  Advisor Agent -----> proposes experiment with your guidance baked in
       |
       v
  Planning Agent ----> designs method incorporating your instructions
       |
       v
  Task Agent ---------> implements the plan (instructions visible in context)
       |
       v
  Evaluator ----------> scores against criteria (unchanged by instructions)
       |
       v
  Advisor Agent -----> considers your instructions when proposing next steps
```

Instructions do **not** change the evaluation criteria. They steer *what* is tried, not *what counts as success*. To change criteria, chat with the advisor and ask it to update them.

### REPL Conversation as Instructions

In the REPL, your conversation with the advisor automatically becomes context for the next `/run`. This is one of the most powerful features:

```
urika:my-project> I think we should focus on tree-based models and avoid
                   neural networks -- the sample size is too small.

  [advisor_agent]
  Agreed. With N=500, tree-based models are a better fit...

urika:my-project> Also, make sure to use stratified k-fold since the
                   outcome classes are imbalanced (15% positive).

  [advisor_agent]
  Good point. I'll ensure all experiments use stratified 5-fold CV...

urika:my-project> /run
```

When you type `/run`, the REPL passes your conversation history as context to the orchestrator. The planning agent sees "focus on tree-based models, avoid neural networks, use stratified k-fold" without you needing to repeat it.

### Instructions for Autonomous Runs

When running multiple experiments autonomously, instructions set the overall research strategy:

```bash
# CLI: set strategy for the full autonomous run
urika run my-project --max-experiments 5 --instructions "focus on interpretable models, report feature importances for every method, use nested cross-validation"
```

```
# REPL: discuss strategy first, then launch autonomous run
urika:my-project> For the next batch of experiments, I want to focus on
                   ensemble methods. Try bagging, boosting, and stacking.
                   Use 10-fold CV and report both RMSE and R-squared.

  [advisor_agent]
  Understood. I'll plan a systematic comparison...

urika:my-project> /run
  Run settings:
    Max turns: 5
    Auto mode: checkpoint
    Instructions: (from conversation — focus on ensemble methods...)

  Proceed?
    1. Run with defaults
    2. Custom settings
    3. Skip
```

Choosing **Custom settings** lets you switch to capped or unlimited autonomous mode while keeping your conversational instructions.


## Advisor Chat vs Advisor in the Loop

It is important to understand that chatting with the advisor and the advisor's role inside the experiment loop are independent:

| | Standalone chat | Inside the loop |
|---|---|---|
| **When** | Any time (before, between, or after experiments) | Automatically at the end of each turn |
| **Trigger** | You type a message or use `urika advisor` | The orchestrator calls it after the evaluator |
| **Input** | Your question + project context + conversation history | Evaluator output + full run history + criteria |
| **Output** | Conversational response + optional experiment suggestions | Structured suggestions for the next turn + optional criteria updates |
| **Affects runs** | Only if you then `/run` (suggestions become context) | Directly -- suggestions become the next turn's task prompt |

Chatting with the advisor **never** disrupts or interferes with running experiments. The standalone advisor is a separate invocation. If an experiment is running (or has been paused), chatting with the advisor will not change the experiment's state.


## Workflow Examples

### Example 1: Iterative Refinement

```bash
# Create project
urika new sleep-quality --data ~/data/sleep.csv \
  --question "What predicts sleep quality from wearable data?"

# Chat before first run
urika advisor sleep-quality "Given the data profile, what baseline should we start with?"

# Run the suggestion
# (advisor offers to run -- accept)

# Check results
urika results sleep-quality

# Chat again
urika advisor sleep-quality "The linear model only got r2=0.35. Should I try feature engineering or jump to non-linear models?"

# Run next suggestion
# (advisor offers to run -- accept)
```

### Example 2: REPL Session with Strategy Discussion

```
urika> /project eeg-analysis

urika:eeg-analysis> Before we run anything, I want to discuss the approach.
                     We have 32-channel EEG data with an oddball paradigm.
                     The P300 should be at Pz, 300-500ms. But I also want to
                     check if there's a lateralized effect at P3/P4.

  [advisor_agent]
  Good plan. I suggest we structure this in two experiments...

urika:eeg-analysis> Agreed. Also, make sure the agents use MNE for preprocessing
                     and cluster-based permutation tests for statistics. Don't use
                     simple t-tests -- the temporal autocorrelation violates
                     independence assumptions.

  [advisor_agent]
  Noted. I'll ensure MNE preprocessing and cluster-based permutation tests...

urika:eeg-analysis> /run
  (runs with all the conversational context as instructions)
```

### Example 3: Mid-Project Course Correction

```
urika:customer-churn> /results
  ... leaderboard shows best F1=0.62, below target of 0.70 ...

urika:customer-churn> We're stuck at F1=0.62. I think the problem is that
                       we haven't addressed the class imbalance properly.
                       Let's try SMOTE, ADASYN, and class weighting on the
                       best model (gradient boosting).

  [advisor_agent]
  You're right -- all experiments so far used raw class distributions...

urika:customer-churn> Also update the criteria to require reporting the
                       precision-recall AUC, not just F1.

  [advisor_agent]
  Updated criteria to include PR-AUC >= 0.65 alongside F1 >= 0.70...

urika:customer-churn> /run
```


## Tips

- **Be specific.** "Try random forest" is fine; "Try random forest with max_depth=5-15, min_samples_leaf=10, and 100-500 trees, using stratified 5-fold CV" is better.
- **Reference your data.** The advisor sees the data profile, but mentioning specific columns or distributions helps it give targeted advice.
- **Build incrementally.** Start with a broad conversation, then narrow focus based on results. Your conversation history carries through.
- **Use the advisor to explain results.** Ask "why did the lasso perform worse than ridge?" -- the advisor can analyze the specific run records and offer explanations.
- **Combine with knowledge.** Ingest a paper, then ask the advisor to incorporate its methodology: "Use the cross-validation strategy from Smith 2024 that I just ingested."
- **Instructions persist for one run.** Instructions from `--instructions` or conversation context apply to the next experiment. For ongoing strategy changes, discuss with the advisor before each run or update the project description with `/update`.

---

**Next:** [Viewing Results](07-viewing-results.md)
