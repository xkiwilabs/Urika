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

These fixtures are READ-ONLY and should not be modified during
tests — copy them into `tmp_path` first.
