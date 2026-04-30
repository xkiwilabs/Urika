# Dataset Hash + Drift Detection — v0.4

**Status:** active (design)
**Date:** 2026-04-30
**Track:** 4
**Effort:** 2 dev-days

## Goal

Critical reproducibility gap: `urika new` profiles the data file but
never records its content hash. If the user re-runs an experiment
after the data has been edited (a real risk during analysis), there's
no record. Storing `sha256` of every registered dataset and checking
on each run is small (<100 LOC) and sets Urika apart on its real
strength (full audit trail).

## Behavior

1. **At project creation** (`urika new`, `POST /api/projects`,
   `ProjectBuilder.write_project`): compute `sha256` per data file and
   store under `[dataset.<name>].sha256` in `urika.toml`.
2. **At each `urika run`**: re-hash registered files. If any differ,
   write the divergence into the run's `progress.jsonl` entry under
   `data_drift: {old_hash, new_hash, file}` and `print_warning` a
   yellow line to stdout/log.
3. **`urika status <project>`**: surface "data has changed since
   exp-003" if the project's current hash differs from any completed
   experiment's recorded hash.
4. **`urika inspect <project>`**: include the per-file hash table in
   the JSON output so external tooling can verify.

## Why it matters

- Sets Urika apart from MLflow et al on its real strength: full audit
  trail.
- Makes the "Reproducibility" claim in `finalize` defensible.
- Closes a class of "I re-ran the experiment with edited data and
  got different numbers" frustrations that's invisible today.

## Implementation

`src/urika/data/loader.py` (new helper):

```python
def hash_data_file(path: Path, *, chunk_size: int = 65536) -> str:
    """Streaming SHA-256 of a data file. Empty string if missing."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()
```

`core/models.ProjectConfig` gains a `data_files: dict[str, str]`
mapping `{relative_path: sha256}`. `urika.toml` `[dataset]` block
stores it.

Hook into `ProjectBuilder.write_project` (after data scan completes)
and `core/registry.py` registration. Re-hash hook in
`orchestrator/loop.py` at experiment start (before turn 1 runs).

Drift detection: when a hash mismatch fires, append a `data_drift`
entry to `progress.jsonl` (the file is already append-only). Don't
block the run — research workflows often involve intentional data
edits — but flag prominently.

## Tests

Extend `tests/test_data/`:
- `hash_data_file` returns a stable sha256.
- Round-trip: write a project, edit a registered data file, run
  `urika status` → reports drift with old vs new hash.
- Backward compat: a project from before this change (no `[dataset]`
  hashes in `urika.toml`) silently skips drift detection without
  erroring.

## Files

- `src/urika/data/loader.py` (`hash_data_file` helper)
- `src/urika/core/models.py` (`ProjectConfig.data_files`)
- `src/urika/core/project_builder.py` (compute on `write_project`)
- `src/urika/core/registry.py` (persist alongside other project meta)
- `src/urika/orchestrator/loop.py` (re-hash + write drift entry)
- `src/urika/cli/data.py:status` (surface drift)
- `tests/test_data/test_hash.py` (new)
