# Cost-Aware Budget — v0.4

**Status:** active (design)
**Date:** 2026-04-30
**Track:** 4 (defer to v0.5 if Track 5 GitHub goes thick)
**Effort:** 2-3 dev-days

## Goal

Multi-experiment autonomous runs are the most popular use of Urika
and the biggest financial foot-gun. Anthropic's spend-cap is the only
safety net today. Add:

1. A `--budget USD` flag on `urika run` that pauses (resumable) at the
   next turn boundary when accumulated cost crosses the limit.
2. A cost-estimate line in `urika run --dry-run` based on N turns ×
   per-agent historical mean tokens × per-model price.

## Foundation

- `core/usage.py:estimate_cost()` already exists with per-model
  pricing.
- `usage.json` per-project tracks accumulated cost and per-session
  history.
- `cli/run_planning.py:_print_dry_run_plan` already lists pipeline
  stages — just needs the cost row.
- `orchestrator/loop.py` already has clean turn boundaries.

## Behavior

### Dry-run cost estimate

```
$ urika run my-project --dry-run --max-turns 10
  Pipeline: planning → task → evaluator → advisor (each turn)
  Max turns: 10
  Estimated cost: $0.12 - $0.45  (based on 7 prior runs in this project)
```

The range is `[10th-percentile, 90th-percentile]` of prior runs'
cost-per-turn × max-turns. Falls back to a static `$0.10 / turn`
estimate when no historical data exists.

### Runtime budget gate

```
$ urika run my-project --budget 2.50 --auto --max-experiments 5
```

At each turn boundary, the orchestrator checks
`load_usage(project).cost_usd_total - run_start_cost`. When that
exceeds `--budget`, the experiment pauses (resumable from the
dashboard's Resume button), `pause_session` writes the reason
("budget $2.50 exceeded after $2.63 spent in 14 turns"), and a
`cost_budget_exceeded` notification fires.

The user can then either `urika run --resume` (which respects the
flag again so they pause again immediately) or raise the budget and
resume.

### Notifications event

New event in `notifications/events.py`:
- `cost_budget_exceeded` — body includes project name, budget,
  current spend, and a link to the Resume modal.

## Implementation

`cli/run.py` adds the `--budget` Click option, threads it through
the orchestrator entry call. `orchestrator/loop.py` reads it from
the `RuntimeConfig` (or a new `RunOptions` shape) and checks at the
turn-boundary block right before the next planning agent fires.

Estimate logic in `cli/run_planning.py:_print_dry_run_plan`:

```python
from urika.core.usage import per_turn_cost_distribution
costs = per_turn_cost_distribution(project_dir, last_n=7)
if costs:
    p10, p90 = costs.percentile(10), costs.percentile(90)
    estimate = (p10 * max_turns, p90 * max_turns)
else:
    estimate = (0.10 * max_turns, 0.10 * max_turns)
```

`per_turn_cost_distribution()` is the new helper in `core/usage.py`.

## Tests

Extend `tests/test_core/test_usage.py`:
- `per_turn_cost_distribution` returns the right shape.
- Empty history → static fallback.
- Boundary case: exactly at-budget vs $0.01-over-budget.

Extend `tests/test_orchestrator/`:
- Mock the cost stream so `--budget` triggers pause at the expected
  turn.
- Resume after pause respects the new budget if updated.

## Files

- `src/urika/cli/run.py` (`--budget` flag, threading)
- `src/urika/cli/run_planning.py:_print_dry_run_plan` (estimate row)
- `src/urika/core/usage.py` (`per_turn_cost_distribution`)
- `src/urika/orchestrator/loop.py` (turn-boundary gate)
- `src/urika/orchestrator/meta.py` (apply gate across experiments
  too)
- `src/urika/notifications/events.py` (`cost_budget_exceeded`)
- `tests/test_core/test_usage.py` (extend)
- `tests/test_orchestrator/test_budget.py` (new)
