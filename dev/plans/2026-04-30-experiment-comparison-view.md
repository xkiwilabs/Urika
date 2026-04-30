# Experiment Comparison View — v0.4

**Status:** active (design)
**Date:** 2026-04-30
**Track:** 4
**Effort:** 1-2 dev-days

## Goal

Side-by-side comparison of N experiments × M metrics on the dashboard.
Today users have to open separate experiment-detail pages and compare
mentally. Every experiment-tracking competitor (W&B, MLflow, Comet)
ships this. Table-stakes feature for the audience Urika targets.

## Data is already on disk

- `experiments/<id>/progress.jsonl` per-experiment append-only log
- `methods.json` per-project method registry
- `leaderboard.json` per-project ranking output
  (`evaluation/leaderboard.py` already handles cross-experiment
  ranking — comparison view is just a UI consumer)

No new model code needed.

## API + UI

**Route:** `GET /projects/<n>/compare?experiments=exp-002,exp-005`

Renders a table with:
- **Columns:** experiments (N selected via query string; checkbox UI
  on the experiments-list page to multi-select).
- **Rows:** metrics from `leaderboard.json` ∪ progress entries.
- **Cells:** best-run value, delta vs project leader, and a small
  inline spark from progress entries.
- **Optional section:** hyperparameter diff reading from
  `methods.json` — per-experiment best-run hyperparameters with diff
  highlighting.

**UI entry point:** experiments-list page gains a "Compare selected"
button enabled when 2+ checkboxes are ticked. Single-experiment
detail page gains "Compare against..." dropdown.

## Implementation

1. New route in `dashboard/routers/pages.py` (~30 lines): parse
   `experiments` query string, load each experiment's progress +
   methods, pivot into `{metric: {exp_id: {best, delta, spark}}}`.
2. New template `dashboard/templates/experiment_compare.html`: render
   the table.
3. Small render helper in `dashboard/render.py` (or inline in the
   route handler): compute the delta + render the inline SVG spark.
4. Tiny JS on the experiments-list page (Alpine, mirror existing
   patterns) for multi-select + button.

## Tests

Extend `tests/test_dashboard/test_pages_*.py`:
- Multi-experiment compare URL renders with the right metrics.
- Single-experiment compare renders without a delta column.
- Bad `experiments=` query string (unknown id) returns 404.
- Dashboard auth gate still applies.

## Files

- `src/urika/dashboard/routers/pages.py` (new route)
- `src/urika/dashboard/templates/experiment_compare.html` (new)
- `src/urika/dashboard/templates/experiments.html` (multi-select +
  Compare button)
- `src/urika/evaluation/leaderboard.py` (no change expected, but
  reusing its sort logic)
- `tests/test_dashboard/test_pages_compare.py` (new)
