# Future Feature Priorities — Status Review (2026-04-27)

Captured during smoke testing of the Phase B running-ops + log streaming
work. Ranks four candidate features by `value × (1 / cost)` and pins
where the code stands today so we can come back to plan each one fully
without re-doing the audit.

Order to pick up later:

1. **Notifications polish** — smallest, validates work already shipped
2. **Orchestrator memory polish** — small, finishes an 80%-built feature
3. **Secrets handling** — three-tier secrets store (process env → project `.env` → global keyring/file). Unblocks UI-based key setup, gates clean multi-SDK adoption. Plan: `2026-04-27-secrets-handling-proposal.md`. Folds in task #115 (round-trip test prompt).
4. **Project memory + agent instructions** — biggest scope, biggest unlocked value, needs its own plan first
5. **Agent runtime abstraction** — defer; no current user pain

---

## 1. Orchestrator memory + `/resume` — mostly built, edges remain

**What's there:**

- `src/urika/core/orchestrator_sessions.py` — full save/load/list/prune/get_most_recent/delete/create_new_session API (~150 lines).
- Sessions persist to `<project>/.urika/orchestrator-sessions/<id>.json`.
- `/resume` and `/resume-session` slash commands in `src/urika/repl/commands_session.py`.
- `cmd_project` in `commands.py:200` already detects recent sessions on project switch and tells the user `Type /resume-session to reload`.
- `src/urika/repl/main.py:545` calls `save_session()` after orchestrator turns.

**What's missing or thin:**

- **Dashboard surface:** zero. No `/projects/<n>/sessions` page, no session list, no resume button. CLI/TUI only.
- **Auto-save granularity:** saves at certain main-loop checkpoints; could miss a turn if REPL exits between save points.
- **Pruning:** `prune_old_sessions(keep=20)` exists but isn't called automatically — sessions accumulate forever until someone calls it.
- **Session previews:** `list_sessions` returns metadata only; no "what did we last talk about" preview.
- **No tests** for the dashboard side because there's no dashboard side.

**Effort to done:** ~1–2 days. Add a session-list page + Resume button to the dashboard (mirror the advisor history page). Hook auto-prune into `save_session`. Add a 1–2 line preview to `list_sessions`.

---

## 2. Project memory + agent instructions — basically not started

**What's there:**

- `src/urika/core/advisor_memory.py` — narrow scope, advisor-only rolling history.
- The instructions textarea in modals is passed at spawn time only, never persisted.

**What's missing (almost everything):**

- No persistent store for "instructions ever given to this project".
- No agent has memory they read at run start — every run begins cold with system prompt + project files.
- No summarization of long histories beyond what `advisor_memory.py` does locally.
- No cross-agent memory (planning agent can't see what the user told the task agent last week).
- No "this project has these standing instructions" file that all agents read.

**Why this is the biggest gap:** Every other feature works around it. Users repeat instructions; agents make contradictory recommendations across runs; "what did the advisor say last time" is lost. The model is the global Claude Code memory directory — Urika needs the project-scoped equivalent.

**Effort to done:** ~1 week for v1. Design needed first:
- Where memory lives (`<project>/memory/MEMORY.md` mirroring CLAUDE.md? `memory/*.md` per topic?)
- How agents read it (system-prompt injection? tool call? both?)
- Categories (`user`, `feedback`, `instructions`, `decisions`)
- Lifecycle (who writes? when does it auto-summarize? who curates?)

This is its own plan. Recommend writing `dev/plans/2026-XX-XX-project-memory.md` before any code.

---

## 3. Agent runtime abstraction — scaffold in, only one backend

**What's there:**

- `src/urika/agents/runner.py` — `AgentRunner` ABC + `get_runner(backend="claude")` factory.
- `src/urika/agents/adapters/claude_sdk.py` — the only implemented adapter.
- The factory accepts a `backend` arg, so the interface is positioned for swap-in.

**What's missing:**

- **No second adapter exists.** Codex / Google ADK / Pi adapters are theoretical. Without a second backend, the abstraction's correctness is untested — the first port typically reveals what's hardcoded in the supposedly-abstract base class.
- No config plumbing for "pick a backend" in `urika config` or `~/.urika/settings.toml`.
- No per-agent backend override.
- The Anthropic OAuth block (Feb 2026) referenced in `project_agent_runtime_abstraction.md` makes the "spawn `claude` CLI" path the practical default — but that's already what `claude_sdk.py` does, so the constraint isn't binding right now.

**Why deprioritize:** No immediate user pain. Not blocked by the Claude SDK today. The abstraction's value is *future optionality*, not a feature you can demo. Doing it now is over-investment unless a specific second-backend need emerges.

**Effort to done:** ~2 weeks. Write a Pi-runtime or Codex adapter (forces the abstraction to be actually abstract), add backend selection to `urika config`, plumb through. Skip if no real need.

---

## 4. Pause / notifications polish — built but unverified

**What's there:**

- `src/urika/orchestrator/pause.py` — full ESC-to-pause keypress listener, daemon thread, cross-platform (Unix `cbreak` + Windows `msvcrt`).
- `src/urika/notifications/` — bus + 3 channels (email, slack, telegram) + events + queries.
- `KeyboardInterrupt` handling in REPL main loop.

**What's missing or unverified:**

- Per `project_pause_notifications.md`: dev-branch-only until user has fully tested. Feature exists; trust isn't validated.
- No automated test of the actual ESC-press → pause-acknowledgment flow (hard to test cross-platform daemon-thread keypress listeners).
- Notification channels likely need real-world send tests (do Slack webhooks actually fire? does email handle SMTP auth correctly under different relay configs?).
- No dashboard surface for notifications status / test-send button — would catch config issues without firing a real run.

**Effort to done:** ~3 days. (a) Add a "Send test" button on the dashboard Settings → Notifications tab (POST endpoint fires one test notification through each enabled channel, reports success/failure inline). (b) Manual smoke pass: run an experiment, hit ESC, verify graceful pause; configure each channel with real creds, fire a test send, fix anything broken. (c) Document the pause UX in `docs/17-notifications.md`. Then graduate from dev-only.

---

## Secrets handling — full review

See `dev/plans/2026-04-27-secrets-handling-proposal.md` for the full design. TL;DR:

**Today:** Urika reads keys from `os.environ` only. Users `export` in their shell or `.bashrc` before `urika dashboard`. No `.env` loading anywhere. The `api_key_env` field in TOML stores the env var **name**, never the value. Urika never sees the actual key.

**Proposed:** three-tier resolution `process env → project .env → global secrets store`. Global store is OS keyring (preferred) with `~/.urika/secrets.toml` (chmod 600) fallback. New Settings → Secrets tab in the dashboard with masked input + eye-toggle for set/update/clear.

**Why now (well, soon):**
- Dashboard has no path to "configure my private model end-to-end" — must drop to terminal.
- Multi-SDK migration multiplies the env vars needed (Anthropic / OpenAI / Google / per-endpoint). Telling every user to export N variables doesn't scale.
- Subscription-vs-API-key choice for Claude becomes UI-toggleable: unset `ANTHROPIC_API_KEY` → spawn `claude` CLI; set it → direct API.

**Folds in:**
- Task #115 (round-trip test prompt) — once secrets are settable from the UI, the Test button actually fires a chat request with the configured key.

**Effort:** ~1 week.

## Small fixes — pick up opportunistically

These are sub-day items that don't warrant a full feature slot but
should land before the priorities below ship for real.

| ID | Item | Effort | Why |
|----|------|--------|-----|
| #115 | Test-endpoint round-trip prompt | ~½ day | Folds into secrets handling (#3) when that ships, but useful standalone too. After reachability passes, fire a real chat-completion request with the configured key so users know the key works end-to-end. |
| #117 | Detach spawned subprocesses from dashboard lifetime | ~½ day | Today, Ctrl+C-ing the dashboard kills any running experiment via SIGPIPE on next stdout write (subprocess stdout is piped through the dashboard). Fix: `subprocess.Popen(..., start_new_session=True)` + redirect stdout straight to `<exp>/run.log` instead of through a pipe. The SSE tailer reads the file directly, which it already does. Then dashboard restart is safe — experiments keep running, log keeps growing, next dashboard pickup works seamlessly. Adds operational robustness for long autonomous runs. |
| #119 | Advisor-first option in dashboard new-experiment modal | ~½–1 day | Dashboard always skips the advisor today (pre-creates dir → spawns `urika run --experiment <id>` which bypasses `_determine_next_experiment`). The CLI's normal `urika run` flow IS advisor-first. Add a checkbox at the top of the modal — "Ask advisor for next-experiment suggestion (recommended)". When checked, sync-call a new `/suggest-experiment` endpoint, show the suggestion in editable fields, user confirms or overrides, then spawn with the agreed name + hypothesis. When unchecked, current behaviour (orchestrator backfills name from first method). Also add `--no-advisor` CLI flag for parity. |
| #120 | Advisor: full subprocess refactor + banner + planner reads history | ~1 day | Refactor advisor to match the other agents' subprocess shape so it's consistent end-to-end: (1) New `spawn_advisor` helper writes `projectbook/.advisor.lock` (PID) + `projectbook/advisor.log`; (2) POST `/api/projects/<n>/advisor` HX-Redirects to a new live-stream advisor log page (mirrors `finalize_log.html`); (3) `/advisor` page becomes a transcript viewer that auto-streams the in-flight exchange + persists via `append_exchange`; (4) `_PROJECT_LEVEL_LOCKS` gains the advisor entry so the running-ops banner shows an "advisor" chip while thinking; (5) `planning_agent_system.md` updated to read `projectbook/advisor-history.json` so per-turn planners see user discussions (closes the gap where only the meta-loop consumed advisor context). Replaces the earlier asyncio.shield() option — full subprocess is the right shape for consistency. |

## Priority rationale

| Priority | Feature | Effort | Confidence | Gates |
|----------|---------|--------|------------|-------|
| 1 | Notifications polish | ~3 days | high | removes "dev-only" flag from existing code |
| 2 | Orchestrator memory polish | ~1–2 days | high | finishes 80%-built feature |
| 3 | Secrets handling | ~1 week | high | gates UI-based key setup + multi-SDK adoption |
| 4 | Project memory + instructions | ~1 week (after plan) | medium | unlocks cross-run continuity |
| 5 | Runtime abstraction | ~2 weeks | low | depends on #3 (each adapter needs a key) |

Picking #1 next gives a quick win that retires a feature flag. #2 follows naturally and tightens loose ends. #3 unblocks the dashboard "set up private model" flow end-to-end and is a hard prerequisite for #5 (every new adapter needs a secret). #4 deserves a dedicated planning phase before any code lands. #5 stays parked behind #3.
