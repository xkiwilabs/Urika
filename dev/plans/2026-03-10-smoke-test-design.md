# CLI Smoke Test Design

**Date**: 2026-03-10
**Status**: Approved
**Context**: Add end-to-end CLI smoke test exercising all commands.

---

## Design

Add `test_cli_smoke_test` to `tests/test_integration.py`. Exercises the full CLI pipeline in one test:

1. `urika new` — create project
2. `urika experiment create` — create experiment via CLI
3. `urika experiment list` — verify it appears
4. `urika run` — mocked orchestrator, verify "completed"
5. Seed run data via `append_run` (orchestrator is mocked)
6. `urika results` — verify shows data
7. `urika report` — verify generates labbook files
8. `urika run --continue` — mocked resume, verify "Resuming"
9. `urika knowledge ingest` — ingest a text file
10. `urika knowledge search` — finds it
11. `urika knowledge list` — lists it
12. `urika status` — final check

## Mocking

Only `run_experiment` and `ClaudeSDKRunner` are mocked (can't run real agents in tests). All other commands exercise real code paths.

## File Changes

| Action | File |
|--------|------|
| Modify | `tests/test_integration.py` |

No new files.
