# Criteria System Design

**Date:** 2026-03-21
**Status:** Approved

## Problem

The evaluator has no structured criteria to evaluate against. It prematurely stops experiments (e.g., declaring baselines as "criteria met"). Different analysis types need different kinds of criteria — prediction tasks have numeric thresholds, statistical analyses need method validity checks, time series work needs parameter adequacy. Criteria should evolve as the project progresses (exploratory → predictive).

## Design

### Criteria as a Living Document

Criteria live in `project_dir/criteria.json` — a versioned, append-only file. Each version captures the full criteria state at a point in time. The evaluator always reads the latest version. History is preserved for the labbook and for auditing how thinking evolved.

### Data Model

```python
@dataclass
class CriteriaVersion:
    version: int
    set_by: str          # "project_builder", "suggestion_agent", "user"
    turn: int            # 0 for project setup
    rationale: str       # why this update was made
    criteria: dict       # the actual criteria
```

The `criteria` dict supports these keys (all optional — use what's relevant):

```json
{
  "type": "exploratory",
  "method_validity": {
    "appropriate_test": true,
    "assumptions_checked": ["normality", "homoscedasticity"]
  },
  "parameter_adequacy": {
    "parameters_justified": true,
    "convergence_required": false
  },
  "quality": {
    "cross_validation": "leave_session_out",
    "min_approaches": 3,
    "effect_sizes_required": true,
    "robustness_check": false
  },
  "completeness": [
    "establish baselines",
    "test nonlinear models",
    "analyze teammate effects"
  ],
  "threshold": {
    "primary": {
      "metric": "top1_accuracy",
      "target": 0.75,
      "direction": "higher"
    },
    "secondary": {
      "metric": "f1_macro",
      "target": 0.65,
      "direction": "higher"
    },
    "other": [
      {"metric": "rmse", "target": 10.0, "direction": "lower"},
      {"metric": "p_value", "target": 0.05, "direction": "lower"}
    ]
  },
  "comparative": {
    "baseline_metric": "top1_accuracy",
    "baseline_value": 0.60,
    "improvement": "significant"
  }
}
```

**Evaluator logic:** Primary threshold must be met for `criteria_met: true`. Secondary and other metrics are reported but don't block. If no threshold is defined (exploratory projects), `criteria_met` stays `false` and the loop runs to `max_turns`.

### Criteria Lifecycle

**Seeding (project setup):**
- Project builder agent proposes initial criteria based on research question and data profile
- User can modify before confirming
- Stored as version 1, `set_by: "project_builder"`, `turn: 0`
- Prediction tasks: likely have `threshold` from the start
- Exploratory/stats: start with `quality` + `completeness` only, no threshold yet

**Evolution (during experiment loop):**
- After each turn, suggestion agent can include `criteria_update` in its JSON output
- Typical triggers:
  - After baselines: "Best heuristic is 60%. Setting primary target to 75%."
  - After assumption check fails: "Data is non-normal. Adding non-parametric test requirement."
  - After diminishing returns: "Lowering target from 80% to 72% — ceiling for this data."
  - After exploration completes: "Shifting from exploratory to predictive. Adding threshold."
- Orchestrator appends new version to `criteria.json`

**Type evolution:**
- Projects can transition: `exploratory` → `comparative` → `predictive`
- The `type` field changes via criteria update — no special mechanism
- Evaluator behavior adapts: starts checking thresholds that didn't exist before

**Evaluation (each turn):**
- Evaluator reads latest version from `criteria.json`
- Checks all present layers (method_validity, quality, completeness, threshold, comparative)
- `criteria_met: true` only when primary threshold is met AND quality/completeness checks pass
- If no threshold defined: `criteria_met` stays `false`

**User override:**
- User can manually edit `criteria.json` between runs
- User can set criteria via project builder prompts
- `set_by: "user"` distinguishes manual from agent-proposed

### Integration

**New file: `src/urika/core/criteria.py`**
- `load_criteria(project_dir)` → returns latest CriteriaVersion
- `load_criteria_history(project_dir)` → returns all versions
- `append_criteria(project_dir, criteria, set_by, turn, rationale)` → appends new version
- `CriteriaVersion` dataclass

**Orchestrator loop changes:**
- After parsing suggestions, check for `criteria_update` field
- If present, call `append_criteria()` to write new version
- Pass current criteria to evaluator context

**Suggestion agent prompt update:**
- Add instruction to propose `criteria_update` when appropriate
- Include current criteria in context so it knows what exists
- Output format adds optional `criteria_update` field

**Evaluator prompt update:**
- Read `criteria.json` instead of `urika.toml` success_criteria
- Evaluate against all present layers in latest version
- Report per-layer status in output

**Project builder changes:**
- Seed `criteria.json` version 1 during project setup
- Ask user about criteria type and initial targets

### What Changes

| Component | Change |
|-----------|--------|
| `src/urika/core/criteria.py` | New: CriteriaVersion, load/append/history functions |
| `src/urika/orchestrator/loop.py` | Parse criteria_update from suggestions, write to file |
| `src/urika/agents/roles/prompts/evaluator_system.md` | Read criteria.json, evaluate per-layer |
| `src/urika/agents/roles/prompts/suggestion_agent_system.md` | Can propose criteria_update |
| `src/urika/core/project_builder.py` | Seed criteria.json during setup |
| `src/urika/cli.py` | Pass criteria context to builder prompts |
