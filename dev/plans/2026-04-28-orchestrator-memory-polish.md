# Orchestrator Memory Polish — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Finish the 80%-built orchestrator-session memory + `/resume` work. Add a dashboard surface for it, hook auto-prune, surface preview text in session lists, and test the cross-surface flow end to end.

**Architecture:** Orchestrator sessions are already persisted to `<project>/.urika/orchestrator-sessions/<id>.json` via `urika.core.orchestrator_sessions`. The CLI/TUI can list and resume them via `/resume` and `/resume-session`. The dashboard has no surface for any of this. Plus the auto-prune helper exists but is never called. This plan closes those gaps.

**Tech stack:** Existing FastAPI + HTMX + Alpine. Reuses the `urika.core.orchestrator_sessions` API. No new dependencies.

**Out of scope (decided):** rewriting how sessions are saved, changing the JSON shape, multi-user concurrency, session search.

---

## Phase A — Plumbing

### Task A.1: Auto-prune on save

**Files:**
- Modify: `src/urika/core/orchestrator_sessions.py` — call `prune_old_sessions(project_dir, keep=20)` at the end of every `save_session()` call.
- Test: `tests/test_core/test_orchestrator_sessions.py` (extend) — `test_save_auto_prunes_when_over_keep_limit`.

**Step 1: Failing test**

```python
def test_save_auto_prunes_when_over_keep_limit(tmp_path):
    project_dir = tmp_path / "p"
    (project_dir / ".urika" / "orchestrator-sessions").mkdir(parents=True)
    # Pre-seed 25 session files
    for i in range(25):
        save_session(project_dir, OrchestratorSession(...))
    # After the 25th save, only 20 should remain
    sessions = list_sessions(project_dir)
    assert len(sessions) == 20
```

**Step 2: Implement**

Add a single line at the end of `save_session()`:
```python
def save_session(project_dir, session):
    # ... existing write logic ...
    prune_old_sessions(project_dir, keep=20)
```

Make sure `prune_old_sessions` is robust to the file you JUST wrote (don't accidentally prune the freshest). Sort by mtime or by ID prefix and keep the most recent N.

**Step 3: Tests pass.**

**Step 4: Commit** — `feat(core): auto-prune orchestrator sessions on save`

### Task A.2: Session previews

**Files:**
- Modify: `src/urika/core/orchestrator_sessions.py` — `list_sessions` now returns a `preview` field with the first user message of the session (truncated to 80 chars).
- Test: extend `test_list_sessions_includes_preview`.

**Step 1: Test** — assert `list_sessions` returns dicts with a `preview` key set to the first user message text.

**Step 2: Implement**

In `list_sessions`, after loading each session JSON, scan its `messages` list for the first `{"role": "user", ...}` entry, pull the text, truncate. If no user message yet, use `""`.

**Step 3: Commit** — `feat(core): list_sessions returns preview text from first user message`

---

## Phase B — Dashboard surface

### Task B.1: GET `/projects/<n>/sessions` page

**Files:**
- Modify: `src/urika/dashboard/routers/pages.py` — new `project_sessions` view.
- Create: `src/urika/dashboard/templates/sessions_list.html` — list of recent sessions with timestamp, preview, message-count, "Resume" and "Delete" buttons per row.
- Modify: `src/urika/dashboard/templates/_sidebar.html` — add `Sessions` link between `Advisor` and `Knowledge`.
- Test: `tests/test_dashboard/test_pages_sessions.py` (new).

**Layout** (mirrors `experiments.html`):

```
Sessions
[+ New session]                                  [Sort: Newest first]

┌──────────────────────────────────────────────────────┐
│ session-20260428-101530                              │
│ "I'm wondering if we should try mixed-effects..."    │
│ 12 messages · 2026-04-28T10:15:30Z      [Resume] [×]│
└──────────────────────────────────────────────────────┘
```

Routes:
- `GET /projects/<n>/sessions` → list page.
- `POST /api/projects/<n>/sessions/<id>/resume` → loads the session into the active TUI/REPL state via a session-resume token. **Caveat:** dashboard can't directly "resume" the way the TUI can — sessions are TUI/REPL chat state, not dashboard state. So Resume on the dashboard launches the dashboard's existing chat-style /advisor page with the session's messages pre-loaded as context. (Or marks the session as "active" in a way the next REPL launch picks up.) **Decision needed before implementation.**
- `DELETE /api/projects/<n>/sessions/<id>` → trash via the existing `delete_session` helper.

### Task B.2: Decide what "Resume" means on the dashboard

**Discussion required.** Three options:

1. **Read-only viewer:** dashboard shows the session transcript as a read-only page; user must launch TUI/REPL with `urika --resume <id>` to actually continue.
2. **Pre-fill advisor:** dashboard's `/advisor` accepts an optional `?session_id=...` query that pre-loads the session's messages as context for the next advisor exchange.
3. **Full chat surface in dashboard:** new `/projects/<n>/sessions/<id>` page that's a full chat view, with a composer that POSTs to a new endpoint preserving session state. Bigger build.

Recommend **Option 2 for v1.** Keep TUI/REPL as the canonical chat surface; dashboard's role is to surface the history and let the user kick a fresh advisor conversation that's aware of the prior session. Option 3 is a future expansion.

### Task B.3: Tests

- `test_sessions_list_404_unknown_project`
- `test_sessions_list_empty_state`
- `test_sessions_list_renders_recent_sessions_with_previews`
- `test_session_delete_endpoint`
- `test_session_resume_redirects_to_advisor_with_context` (per Option 2)

---

## Phase C — On project switch / `/project <name>`

### Task C.1: Cleaner UX for "previous session available"

`commands.py:200` already detects recent sessions on `/project` switch and prints `Type /resume-session to reload`. This is fine but spartan. Improvements:

- Show the preview text of the most recent session inline.
- Add the timestamp ("from 2 hours ago" via a small relative-time helper).
- If the session was paused (vs. just exited), say "Paused session available — type /resume to continue."

**Files:**
- Modify: `src/urika/repl/commands.py:200-220` (the project-switch hook).
- Test: extend `tests/test_repl/test_commands.py`.

---

## Phase D — Smoke + docs

### Task D.1: Smoke checklist

Create `dev/plans/2026-04-28-orchestrator-memory-smoke.md` with manual checks:
- Have a TUI conversation with the advisor → exit → relaunch → see "Previous session available" prompt → `/resume-session` → conversation continues with full context.
- Same test on the dashboard sessions page.
- Trash a session via dashboard → confirm gone from list, gone from disk.
- Run 25 sessions → confirm only 20 remain (auto-prune).
- Delete a project → confirm sessions trash with the project (per existing project-trash).

### Task D.2: Update `docs/16-interactive-tui.md`

Add a "Session memory" section explaining persistence + `/resume` + `/resume-session`. Single page.

---

## Effort

- Phase A (auto-prune + previews + tests): ~2 hours
- Phase B (dashboard surface, decision-gated): ~half day, depending on Option chosen
- Phase C (project-switch UX): ~1 hour
- Phase D (smoke + docs): ~1 hour

**Total: ~1 day** (1.5 if Option 3 is chosen for B).

## Open questions for you to decide

1. Resume semantics on dashboard — Option 1 / 2 / 3?
2. Auto-prune `keep=20` — fine, or different?
3. Sidebar position for Sessions link — between Advisor and Knowledge OK?
4. Should sessions also persist orchestrator activity beyond chat (e.g. experiment proposals) or stay chat-only?
