# Method Registry Design

**Date:** 2026-03-21
**Status:** Approved

## Problem

The task agent writes analysis scripts to `artifacts/` mixed with their outputs (plots, result JSONs, data files). Methods aren't tracked, discoverable, or reusable across experiments. The `methods/` directories and `leaderboard.json` exist but are empty. There's no record of which methods were tried, what they do, or how effective they are.

## Design

### Method Registry

A project-level `methods.json` tracks every method the agent creates. It serves as both a method catalog and a leaderboard.

```json
{
  "methods": [
    {
      "name": "conditional_logit_full_features",
      "description": "Conditional logistic regression with 12 features",
      "script": "experiments/exp-002/methods/conditional_logit.py",
      "created_by": "task_agent",
      "experiment": "exp-002-baselines-v2",
      "turn": 1,
      "metrics": {"top1_accuracy": 0.6489},
      "status": "superseded",
      "superseded_by": "lightgbm_lambdarank_enriched18"
    }
  ]
}
```

Fields:
- `name`: Agent-chosen descriptive name
- `description`: What the method does
- `script`: Relative path to the Python script
- `created_by`: Which agent wrote it
- `experiment`: Which experiment it belongs to
- `turn`: Which turn it was created in
- `metrics`: Whatever metrics the method produced (flexible dict)
- `status`: `"active"`, `"best"`, `"superseded"`, `"failed"`
- `superseded_by`: Name of the method that replaced it (if superseded)

### Artifact Separation

The task agent prompt is updated to separate scripts from outputs:
- **`methods/`** — analysis pipeline scripts (the code)
- **`artifacts/`** — outputs (plots, result JSONs, intermediate data, SHAP values)

### Orchestrator Integration

After `parse_run_records` extracts runs from the task agent output, the orchestrator registers each run's method in `methods.json`. The `RunRecord.method` field is the method name, and the script path is inferred from the experiment's `methods/` directory.

### Agent Access

- **Planning agent** reads `methods.json` to know what's been tried
- **Suggestion agent** reads it to propose refinements or new directions
- **Evaluator** reads it to assess which methods meet criteria
- **Task agent** reads it to avoid duplicating work

### Replaces leaderboard.json

`methods.json` replaces `leaderboard.json`. No separate leaderboard needed — the method registry IS the ranked list of approaches.

### Workspace Cleanup

- Remove `skills/` from workspace template (unused, "method" is the right concept)
- Remove `config/` from workspace template (unused, config is in `urika.toml`)
- Remove `leaderboard.json` creation from workspace template
- Keep `data/` (agents may generate preprocessed data there)

### What Changes

| Component | Change |
|-----------|--------|
| `src/urika/core/method_registry.py` | New: load/register/update methods |
| `src/urika/core/workspace.py` | Remove skills/, config/, leaderboard.json from template |
| `src/urika/orchestrator/loop.py` | Register methods after parsing run records |
| `src/urika/agents/roles/prompts/task_agent_system.md` | Scripts → methods/, outputs → artifacts/ |
| `src/urika/evaluation/leaderboard.py` | Update to read from methods.json instead |
| `CLAUDE.md`, `current-status.md` | Update docs |
