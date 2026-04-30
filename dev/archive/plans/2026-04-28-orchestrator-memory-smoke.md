# Orchestrator Memory Polish — Smoke Checklist

> Run after Phase C lands. Verifies end-to-end: persistence on save,
> auto-prune, sessions list page, dashboard delete, advisor pre-load,
> project-switch hint.

## Pre-reqs

- Working Urika install on `dev` branch.
- One throwaway project with at least 25 historical sessions (or run a
  quick loop to generate them — see appendix).
- Dashboard running (`urika dashboard`).

## Checks

### Persistence + auto-prune

- [ ] Have a chat with the orchestrator (any free-text question).
- [ ] Quit Urika.
- [ ] Inspect `<project>/.urika/sessions/`. Confirm a fresh JSON file is present, named `<timestamp>-<n>.json`.
- [ ] If you previously had >20 sessions, after the latest save only 20 should remain on disk (oldest auto-pruned).

### TUI/REPL resume

- [ ] Re-launch Urika.
- [ ] `/project <name>` → expect: `Previous session from <relative time>: "<preview snippet>". Type /resume-session to continue.`
- [ ] Type `/resume-session` → previous transcript loads; ask a follow-up; the new exchange continues into the same session file.

### Dashboard sessions list

- [ ] Open dashboard → project sidebar → click **Sessions**.
- [ ] List shows up to 20 sessions, newest first, with preview text + turn count + timestamp.
- [ ] Empty state shows when no sessions exist (try a fresh project).

### Dashboard advisor pre-load

- [ ] On Sessions list, click **Resume** on any session.
- [ ] Browser navigates to `/projects/<n>/advisor?session_id=<id>`.
- [ ] Page renders a "Prior session" panel above the advisor transcript with the session's messages.
- [ ] Compose a new advisor question, submit. New exchange appears in advisor transcript (not back in the orchestrator session — confirm by checking session file on disk hasn't grown).

### Dashboard delete

- [ ] On Sessions list, click **Delete** on a session row.
- [ ] Browser confirm dialog appears; click OK.
- [ ] Row disappears from the list (HTMX swap).
- [ ] Confirm `<project>/.urika/sessions/<id>.json` is gone.

### Edge cases

- [ ] Visit `/projects/<n>/advisor?session_id=does-not-exist` → page renders with a "Session not found" notice (no 500).
- [ ] Visit Sessions page on a non-existent project → 404.
- [ ] Switch into a project with no sessions → no "Previous session" hint printed.

## Appendix: bulk-generate sessions

```python
from pathlib import Path
from urika.core.orchestrator_sessions import OrchestratorSession, save_session

project = Path("/path/to/your/project")
for i in range(25):
    s = OrchestratorSession(
        session_id=f"smoke-{i:04d}",
        started=f"2026-04-{(i % 28) + 1:02d}T00:00:00Z",
        updated=f"2026-04-{(i % 28) + 1:02d}T00:00:00Z",
        preview=f"Smoke test session {i}",
        recent_messages=[
            {"role": "user", "content": f"Question {i}"},
            {"role": "assistant", "content": f"Answer {i}"},
        ],
    )
    save_session(project, s)
```

After running, check that only 20 files remain on disk (the newest 20).
