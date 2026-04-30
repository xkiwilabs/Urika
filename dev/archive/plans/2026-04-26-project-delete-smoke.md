# Project Delete + Trash — Smoke Test Results

Companion to `dev/plans/2026-04-26-project-delete-and-trash.md`.
Captures the state of automated and manual verification on 2026-04-26
after the project trash feature shipped end-to-end.

## Automated verification

```
pytest -q
2007 passed, 177 warnings in 54.90s
```

Baseline at start of the trash feature: 1974 passing.
Net change: **+33 tests** across the six commits.

Breakdown by phase:

- **Phase 1** (`feat(core): trash_project helper`): +8 tests in
  `test_core/test_project_delete.py` — happy path, missing-folder,
  active-lock guard, unknown name, same-name-twice, manifest, deletion
  log, collision-within-same-second.
- **Phase 2.1** (`feat(cli): urika delete`): +7 tests in
  `test_cli_project.py` — confirm flow, `--force`, `--json`,
  unknown-name, active-lock, missing-folder.
- **Phase 2.2** (`feat(cli): urika list --prune`): +3 tests in
  `test_cli_project.py` — prune removes missing entries, no-stale
  message, list-without-prune unchanged.
- **Phase 3** (`feat(repl): /delete slash command`): +7 tests in
  `test_repl/test_commands.py` — usage, confirm, abort,
  unknown-project, active-lock, clears session on loaded-project
  delete, registry-only message.
- **Phase 4.1** (`feat(dashboard): DELETE endpoint`): +5 tests in
  `test_dashboard/test_api_delete_project.py` — 404, 422 + lock path,
  success payload, registry-only, HX-Redirect.
- **Phase 4.2** (`feat(dashboard): danger zone + unregister`): +3
  tests across `test_pages_settings.py` and `test_pages_projects.py`
  — danger zone renders, disables on active lock, missing-card
  unregister button.

## Commit log (dev branch)

```
511dc075 feat(dashboard): danger zone in settings + unregister missing projects
a955f68f feat(dashboard): DELETE /api/projects/<name> trashes the project
eb250443 feat(repl): /delete <name> slash command moves project to trash
a9934b42 feat(cli): urika list --prune unregisters missing-folder entries
92e9eba1 feat(cli): urika delete moves project to trash and unregisters
b3052a11 docs(plan): project delete + trash
b9a3c432 feat(core): trash_project helper moves projects to ~/.urika/trash/
```

## Manual checklist — pending

These verify the end-to-end flow against a real registered project on
disk. Walk through them with a project you don't mind losing access to
(or recreate one for the purpose).

### CLI

- [ ] `urika delete foo` (registered, valid folder): shows confirm
      prompt → `y` → prints "Moved 'foo' to <path>" with a path under
      `~/.urika/trash/foo-<timestamp>/`.
- [ ] Open `~/.urika/trash/foo-<timestamp>/`: original tree intact,
      `.urika-trash-manifest.json` present at the root with the right
      keys (`registered_name`, `original_path`, `trashed_at`,
      `urika_version`).
- [ ] `urika list` no longer shows `foo`.
- [ ] `urika delete foo` with stdin `n`: prints "Aborted.", folder
      still exists, registry still has the entry.
- [ ] `urika delete foo --force`: skips prompt, trashes immediately.
- [ ] `urika delete foo --force --json`: stdout is valid JSON with the
      four expected keys.
- [ ] `urika delete missing-name`: exit 1, message "Project 'missing-name'
      is not registered."
- [ ] Drop `.lock` somewhere under a project, run `urika delete foo
      --force`: exit 1, error mentions the lock path. Folder + registry
      untouched.
- [ ] Manually `rm -rf` a project's folder, then `urika delete foo`:
      prints "Unregistered 'foo' (folder at <path> was already
      missing)." No trash dir created (nothing to move).
- [ ] `urika list --prune` after manually deleting two project
      folders: prints "Pruned 2 stale entries: <a>, <b>" then the
      cleaned list.
- [ ] `urika list --prune` with no stale entries: prints "No stale
      entries." then the list.
- [ ] Trash a project, recreate one with the same name, trash again:
      `~/.urika/trash/` contains two distinct timestamped dirs.
- [ ] `~/.urika/deletion-log.jsonl` accumulates one JSON line per
      operation (including registry-only ops).

### TUI / REPL

- [ ] Inside a TUI session with no project loaded, run `/delete foo`
      with stdin `y`: trashes, prints "Moved 'foo' to <path>".
- [ ] `/delete` with no args: prints "Usage: /delete <name>".
- [ ] `/delete <name>` with stdin `n`: prints "Aborted." Registry
      untouched.
- [ ] Load a project (`/project foo`), then `/delete foo`: trashes
      AND clears session — status bar drops the project name, no more
      project-scoped commands listed in `/help`.
- [ ] `/delete <unknown>`: prints "Project '<unknown>' is not
      registered." (no traceback).
- [ ] `/delete foo` while a `.lock` exists under `foo/experiments/...`:
      prints the active-run error inline (no traceback).

### Dashboard

- [ ] Visit `/projects/foo/settings`. Scroll to the bottom: "Danger
      zone" section visible with red border and dim red-tinted
      background.
- [ ] Type input is empty → "Move to trash" button is disabled.
- [ ] Type `foo` exactly into the input → button enables.
- [ ] Drop a `.lock` file under the project, reload settings: danger
      zone shows the disabled state with the lock path instead of the
      type-input + button.
- [ ] Click "Move to trash" → browser navigates to `/projects` (no
      404, no JSON dump). Project no longer in the list.
- [ ] Folder gone from the original path; trash dir present at
      `~/.urika/trash/foo-<timestamp>/` with manifest.
- [ ] Manually `rm -rf` a project's folder → `/projects` page shows
      that project tagged as missing with an inline **Unregister**
      button.
- [ ] Click Unregister → confirm dialog → entry disappears from the
      list. No trash dir created (nothing to move).
- [ ] DELETE on an unknown project name (curl) → 404 JSON `{"detail":
      "Unknown project"}`.
- [ ] DELETE while a `.lock` is active (curl) → 422 with the lock path
      in `detail`.
- [ ] DELETE with `hx-request: true` header (curl) → 200 with
      `HX-Redirect: /projects` response header.

### Cross-surface

- [ ] Trash a project from the CLI; refresh dashboard: project no
      longer in the list.
- [ ] Trash a project from the dashboard; reload TUI: project gone
      from `/list`, slash-command tab-completion no longer suggests
      it.
- [ ] Inspect `~/.urika/deletion-log.jsonl` after a mix of CLI / TUI /
      dashboard ops: every operation captured, one JSON object per
      line, all parse cleanly.

### Negative / safety

- [ ] No `--path` argument exists on `urika delete` (registry-only
      lookup is the sole way to specify a target).
- [ ] `urika delete /etc/passwd` (or any unregistered path-like
      string) → "Project '/etc/passwd' is not registered." Nothing
      touched on disk.
- [ ] Trash dir uses a timestamped suffix: deleting and recreating
      `foo` then deleting again does NOT overwrite the first trash
      dir.
