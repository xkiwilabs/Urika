# Cookbook: long-running training and slow methods

This page covers projects where individual methods take **minutes to
hours** to run — gradient-boosted ensembles with full hyperparameter
search, deep-learning training, simulation-heavy statistical models,
or anything that's not "fit a regression and return". The default
Urika settings assume each method finishes in seconds; once you
cross into multi-minute territory a few knobs need adjusting.

## Symptoms that bring you here

| You're seeing | Likely cause |
|---|---|
| Task agent dies partway through training with no clear error | The `claude` CLI's per-call timeout cut the Bash tool mid-execution |
| Experiment hits `--max-turns` after only 2–3 methods | Each method takes ~one turn; a budget of 5 turns means you only get to try 5 things |
| Run aborts with "budget reached" before the model finishes | `[preferences].budget_usd` is too low for the wall-time × token rate |
| Dashboard shows "stopped" instead of "completed" after a long finalize | (Fixed in v0.4.1 — `stop_session` no longer downgrades a completed status) |

## Tuning checklist

### 1. `max_turns_per_experiment`

One method execution ≈ one turn. If your methods take 30 minutes each
and you set `--max-turns 5`, the experiment runs for ~2.5 hours and
explores 5 methods. That's usually too few for an exploratory pass.

Reasonable starting points:

| Method wall-time | Recommended `max_turns` |
|---|---|
| < 1 min | 5–10 (the default is fine) |
| 1–10 min | 10–20 |
| 10–60 min | 5–8 (you're trading breadth for depth) |
| > 1 hour | 3–5 + use `--max-experiments` to chain multiple narrow experiments |

Set the project default in `urika.toml`:

```toml
[preferences]
max_turns_per_experiment = 10
```

Override per-run with `urika run <project> --max-turns 8`.

### 2. Budget ceiling

The orchestrator pauses when total cost crosses
`[preferences].budget_usd`. For long-training experiments the **input
tokens accumulate quickly** (system prompt + history per turn) even
when each agent call is short, so the budget should account for both
the agent overhead *and* the wall-clock.

Rule of thumb: budget ≈ `max_turns × $0.50 × cost_multiplier`, where
`cost_multiplier` is ~1 for Sonnet and ~5 for Opus. For a 10-turn
Opus-on-reasoning + Sonnet-on-execution split, $5–$10 is a safe
starting budget; raise to $20+ for full Opus runs.

```toml
[preferences]
budget_usd = 10.0
```

When the budget is hit Urika **pauses**, doesn't fail. Resume with
`urika run --resume` after raising the cap.

### 3. Stop and resume safely

Long runs *will* be interrupted — laptop sleep, network blip, the
dashboard's Stop button. Three things make this safe:

* **Lockfile cleanup** runs on SIGINT and SIGTERM. The dashboard's
  Stop button signals the spawned `urika run` and the cleanup hook
  marks the session correctly.
* **Resume** picks up from the last completed turn:
  ```bash
  urika run my-project --resume
  ```
* **A SIGTERM after criteria are met** (e.g. you click Stop while
  the per-experiment narrative is being generated) is treated as
  "abandon the cosmetic pass, keep the success". The experiment
  stays marked completed; only the report is missing. Re-run
  `urika report` to retry.

### 4. Diagnose where time goes

When a run takes longer than expected, the prompt-trace
instrumentation (v0.4.1+) records one JSONL record per agent call
with prompt sizes, cache-hit ratios, and wall-clock duration.

```bash
URIKA_PROMPT_TRACE_FILE=/tmp/urika-trace.jsonl \
  urika run my-project --max-turns 5

# After (or during) the run:
python dev/scripts/analyze_prompt_trace.py /tmp/urika-trace.jsonl
```

Output:

```
agent           n  sys_KB  prompt_KB_avg  in_avg  cache_read_avg  cache_hit%  out_avg  sec_avg
---------------------------------------------------------------------------------------------
advisor_agent   3     7.1           3.50      21          218788       80.8%     4812    134.6
evaluator       2     7.5           6.08      26           63386       74.6%    10228    215.3
planning_agent  2     6.2           2.63      13          501900       88.8%     6446    166.8
task_agent      2     8.2          13.46     149          759756       93.0%    21904    362.2

Overall:
  cache hit ratio:    88.4%
  fresh input tokens:        439
  total wall seconds:    1,892.4
```

Interpretation guide:

* **`task_agent` `sec_avg`** — if this is in the 5+ minute range, the
  agent is genuinely slow (training, not waiting on the API).
* **`cache_hit%` < 50%** — the system prompt isn't being cached
  effectively, often because something in the system prompt is
  changing between calls (e.g. memory growing, advisor history
  rolling). Cost per call is then much higher than the headline
  token count suggests.
* **`out_avg` > 20K** — agent is producing very long responses;
  consider whether the system prompt is encouraging verbosity or
  whether a more focused task prompt would help.

The trace is opt-in (env var only) and writes append-only JSONL with
zero overhead when off.

## Built-in tools to prefer

Urika ships with seed tools that handle long-running training
efficiently — use these instead of letting the agent re-implement:

| Tool | When |
|---|---|
| `gradient_boosting`, `random_forest` | Tree-based ensembles with sane CV defaults |
| `regularized_regression` | Ridge / Lasso / ElasticNet with internal CV |
| `cross_validation` | Wraps any sklearn estimator with proper CV folds |
| `train_val_test_split`, `group_split` | Avoids leakage in time-series + grouped data |

When the agent picks one of these, runtime is bounded and the metric
is recorded directly to the run record — no chance of the model
training "off-piste" and the result not making it back to disk.

For genuinely custom training, the `task_agent` writes the script
and runs it via Bash. That's where the next two pitfalls show up:

### Bash tool timeout

The bundled `claude` CLI applies a default per-tool-call wall-clock
timeout to Bash invocations. For training scripts that legitimately
run for tens of minutes, this can be hit. v0.4.1 introduces
`[preferences].max_method_seconds` to surface a clean per-method
cap and a clearer error when it fires; until then, prefer the
built-in tools above for anything > 5 minutes.

### Method runs that produce no metric

If the training script crashes silently or doesn't write a
`metrics` block to its run record, the evaluator can't grade the
turn and the advisor has nothing to plan against. Always guard the
final write:

```python
import json, sys, traceback
try:
    metrics = train_and_evaluate(...)
    print(json.dumps({"metrics": metrics}))
except Exception as e:
    # The evaluator treats a turn with no metrics as inconclusive
    # rather than failed — surface the failure explicitly.
    print(json.dumps({"error": str(e), "trace": traceback.format_exc()}),
          file=sys.stderr)
    sys.exit(1)
```

## Recommended settings template

For a project where each method takes ~10 minutes:

```toml
[project]
name = "long-training-example"
mode = "exploratory"

[preferences]
max_turns_per_experiment = 8
budget_usd = 10.0
audience = "expert"
```

Run with the trace on for the first session so you have data to
calibrate from:

```bash
URIKA_PROMPT_TRACE_FILE=/tmp/urika-trace.jsonl \
  urika run long-training-example --max-turns 8 --auto
```

After the first experiment completes, run the analyzer and decide
whether to raise `max_turns`, raise `budget_usd`, or move expensive
methods into a built-in tool. The trace removes the guesswork.
