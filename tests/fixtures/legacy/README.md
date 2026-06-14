# Legacy project fixtures

Snapshots of project shapes that older Urika releases produced. Each
exercises a backwards-compat path that's caused real user pain in
the past — current releases must continue to handle them gracefully.

Tests in `tests/test_smoke/test_backwards_compat.py` drive each
fixture through the relevant CLI commands and assert the new release
recovers cleanly.

| Fixture | Bug it pins |
|---------|-------------|
| `v030-empty-lockfile/` | Pre-v0.3 `acquire_lock` used `path.touch()` (empty file). Post-v0.3 the file contains the PID. v0.4.2 Package K treats empty locks as stale unconditionally — pre-K behaviour was to refuse for 6 hours after mtime. |
| `v03x-corrupt-progress/` | A SIGTERM mid-`progress.json`-write left a truncated JSON file. v0.4.2 Package A migrated all state writes to atomic temp+rename so this can't happen anymore, but readers must still handle pre-existing corrupt files without crashing. |
| `v040-no-runtime-block/` | Older `urika.toml` shapes without `[runtime]` or `[privacy]` sections. The loader must fall back to defaults instead of raising. |
| `v080-old-leaderboard-entries/` | `leaderboard.json` using the pre-canonical `entries` key and a project with no `schema_version`. `urika upgrade` rewrites `entries` → `ranking` on disk and stamps the version. |
| `v050-pre-labbook/` | A v0.4-era project: no `schema_version`, no research-intent fields, one completed experiment. `urika upgrade` stamps the version and regenerates labbook notes without data loss. |
| `v090-pre-uncertainty/` | Runs predating `metrics_with_uncertainty` (already load-tolerant). Proves `urika upgrade` leaves run records untouched and only stamps the version. |

These fixtures are READ-ONLY and should not be modified during
tests — copy them into `tmp_path` first.
