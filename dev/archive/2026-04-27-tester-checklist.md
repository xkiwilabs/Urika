# Urika Tester Checklist — 2026-04-27 release point

Thanks for helping test! This walks you through every recent change. Tick each item off as you go — flag anything that doesn't behave as described.

**Setup:**

```bash
git checkout dev
git pull
pip install -e ".[dev]"
```

**Before you start:** create a fresh project to use as your testbed. Use a small dataset (a 1–10MB CSV is fine) so experiments finish in a few minutes.

---

## 1. CLI

### 1.1 Project creation + listing

- [ ] `urika new my-test` → walks you through interactive setup (name, dataset, question, mode, audience).
- [ ] `urika list` → shows the new project with its path. New projects default to **standard** audience (not novice / expert — let me know if you see something different).
- [ ] `urika status my-test` → shows research question, mode, experiment count, last activity.

### 1.2 Project deletion (trash)

- [ ] Create a throwaway project: `urika new disposable-test`.
- [ ] `urika delete disposable-test` → prompts for confirmation. Type `n` first → "Aborted." nothing changes.
- [ ] `urika delete disposable-test --force` → no prompt; "Moved 'disposable-test' to ~/.urika/trash/disposable-test-…". Files moved, NOT deleted. Confirm by `ls ~/.urika/trash/`.
- [ ] `urika list --prune` → unregisters any registry entries whose folders are missing on disk. Reports "Pruned N stale entries: …" or "No stale entries."

### 1.3 Running experiments

For these tests, use a project where you can let an experiment run for ~5 minutes.

- [ ] `urika run my-test` (no flags) → consults advisor first to suggest the next experiment, creates it with a meaningful name, runs through Planning → Task → Evaluator → Advisor turns. Watch the agent headers in the terminal — they should be color-coded (planning green, task cyan, evaluator yellow, advisor magenta, etc.).
- [ ] `urika run my-test --auto --max-experiments 3` → autonomous mode caps at 3 experiments; meta-loop alternates between Advisor (proposing next) and turn loop.
- [ ] `urika run my-test --auto` (without `--max-experiments`) → unlimited mode; runs until advisor says done.

### 1.4 Stop / pause during a run

- [ ] During an active run, press **ESC** → "Pause requested. Waiting for current step to finish…" appears. Run completes the current turn then exits with status `paused`.
- [ ] During an active run, press **Ctrl+C** → run stops; status becomes `stopped` or `failed`.
- [ ] After a paused run: `urika run my-test --resume` → picks up where it left off.

### 1.5 Experiment delete

- [ ] `urika experiment delete my-test exp-001` → prompts; on `y` moves to `<project>/trash/exp-001-<timestamp>/`. Files preserved.
- [ ] `urika experiment delete my-test exp-001 --force --json` → emits structured JSON.

### 1.6 Other agents

- [ ] `urika summarize my-test --instructions "focus on the high-income gap"` → runs project summarizer, writes `projectbook/summary.md`. Output streams in real-time (you should see Read/Bash/Write tool calls as the agent works — no silence followed by a final dump).
- [ ] `urika report my-test --experiment exp-001` → writes `experiments/exp-001/labbook/narrative.md` (NOT `report.md` — that's the finalize flow's name).
- [ ] `urika present my-test --experiment exp-001` → reveal.js deck at `experiments/exp-001/presentation/index.html`. Open in browser, press **S** → speaker-notes window opens. Title slide should show small footer: "Press S for speaker notes · F fullscreen · ? help".
- [ ] `urika finalize my-test` → produces `projectbook/findings.json`, `report.md`, `presentation/`. Status flips to "Finalized" on the dashboard.
- [ ] `urika build-tool my-test "create a heatmap tool using seaborn"` → writes a new tool under `<project>/tools/`.

### 1.7 Other CLI surfaces

- [ ] `urika dashboard my-test` → opens browser at the project home.
- [ ] `urika config show` → shows global + project-level config. `urika config global show` for global only.
- [ ] `urika usage my-test` → token / cost totals.

---

## 2. TUI / REPL

`urika` (no command) launches the TUI.

### 2.1 Slash commands

- [ ] `/help` → lists every command; project-specific commands only appear after `/project <name>`.
- [ ] `/list` → all projects, currently-loaded marked with `◆`.
- [ ] `/project my-test` → loads a project; status bar updates (project name, mode, model, tokens).
- [ ] `/new` → interactive project creation, same flow as `urika new`.
- [ ] `/delete <name>` → trash a project; if it's the loaded one, session context clears.
- [ ] `/delete-experiment <exp_id>` → trashes an experiment; same friction (confirm prompt) as the dashboard's Danger zone.

### 2.2 /run with advisor-first prompt

- [ ] `/run` → choose "Custom settings" → step through the prompts. The new prompt **"Ask advisor first to suggest a name and direction?"** appears alongside the existing Re-evaluate-criteria prompt. Default answer is Yes.
- [ ] Confirm the advisor runs first when you accept the default; the planner runs first if you say No.
- [ ] During the run, press **ESC** → graceful pause. **Ctrl+C** → stop.

### 2.3 Agents via slash commands

- [ ] `/advisor what should I try next?` → standalone advisor exchange. Persists to `projectbook/advisor-history.json` (visible across sessions).
- [ ] `/evaluate exp-001` → runs evaluator.
- [ ] `/report exp-001` → generates the experiment narrative.
- [ ] `/present exp-001` → generates a deck.
- [ ] `/finalize` → finalize sequence. `/finalize --draft` writes to `projectbook/draft/` instead of overwriting.
- [ ] `/build-tool create a tool that …` → spawns tool builder.
- [ ] `/summarize` (or `/usage`, `/methods`, `/tools`, `/criteria`, `/experiments`, `/results`, `/knowledge`, `/inspect`, `/logs`).
- [ ] `/resume` (paused experiment) and `/resume-session` (orchestrator chat continuation).

---

## 3. Dashboard

```bash
urika dashboard my-test
```

Browser opens. **Hard-reload (Ctrl+Shift+R)** if you've used the dashboard before in this browser — picks up the latest CSS / JS.

### 3.1 Project home + sidebar

- [ ] Sidebar order matches: Home → Experiments → Advisor → Knowledge → Methods → Tools → Data → Usage → Settings.
- [ ] Project home shows: research question + description card, Finalize button, Summarize button (label flips between "Summarize project" and "Re-summarize project" depending on whether `summary.md` exists), Final outputs cards, Recent experiments list with `+ New experiment` and `See all →` links above it.

### 3.2 Running experiments from the dashboard

- [ ] Click `+ New experiment` (either button — on home or experiments list). Modal opens.
- [ ] Modal layout (top to bottom): max turns input → Auto checkbox (with capped/unlimited radios when checked) → Review-criteria checkbox → Audience select (pre-selects the project's default) → Instructions textarea (clearly labelled optional) → "Ask advisor to suggest the next experiment first" checkbox at the **top**, default checked.
- [ ] Default submit (just click "Run experiment" with nothing else changed) → redirects to the live log page → log streams immediately (no long delay).

### 3.3 Live log page

While an experiment is running, observe the log page:

- [ ] **Color-coded agent headers** — `─── Planning Agent ───` is green, `─── Task Agent ───` cyan, `─── Evaluator ───` yellow, `─── Advisor Agent ───` magenta, `─── Report Agent ───` orange, `─── Presentation Agent ───` pink. URIKA banner is in the urika-blue accent.
- [ ] **Sticky thinking spinner** below the log box — urika-blue braille spinner with rotating words ("Thinking", "Reasoning", "Analyzing", "Processing", "Exploring", "Evaluating", "Considering", "Reviewing"). Words change at irregular intervals (not every 3s exactly — should feel natural).
- [ ] **Log footer** below the spinner — single monospace line showing `model · agent · tokens · cost · elapsed`. Elapsed ticks every second. Tokens / cost update every ~5s. Agent name updates as the orchestrator moves through agents. Model field shows `—` until a model name appears in the log (acceptable).
- [ ] **Pause** button — click → "Pause requested. Waiting for current step to finish…". Run completes current turn then exits paused.
- [ ] **Stop now** button (red) → SIGTERMs the subprocess immediately; status text says "Stop signaled — terminating now."
- [ ] **Verbose output** — you should see tool calls (Read, Bash, Write, Grep, etc.) streaming as the agent works. NOT silence followed by a final dump.

### 3.4 Banner + auto-dismiss

- [ ] While an experiment is running, navigate to any other page in the project (Knowledge, Methods, Settings, etc.). At the top, a **"Running:" banner** with a clickable chip shows the active op. Click the chip → returns to the live log.
- [ ] The banner has a small **"Clear stale"** button on the right edge — only relevant if a previous run crashed and left a dead-PID lock; click then reload to remove stale entries.
- [ ] When the run completes, the banner disappears within ~5s automatically (no manual reload needed).

### 3.5 Resume + Delete on experiment list / detail

- [ ] On the experiments list page: every experiment row has the same 3-row layout (title, exp-id, "N runs · timestamp"), status tag on the right.
- [ ] If an experiment status is `failed` / `paused` / `stopped`, a **Resume** button (blue) appears on the right edge of that row.
- [ ] Open the experiment detail page → at the bottom there's a **Danger zone** card with type-name confirmation to move the experiment to `<project>/trash/`. Active-lock guard: if a lock is present, the button is disabled and the lock path is shown.

### 3.6 Outputs section (per-experiment)

- [ ] Generate report, Generate presentation, Evaluate buttons all open modals with instructions textarea + audience select.
- [ ] After an agent finishes, View Report / Open Presentation ↗ links appear (the latter opens in a new tab).
- [ ] **View Report** route: works whether the file is `report.md` (finalize) or `labbook/narrative.md` (report agent). Earlier this was broken — the dashboard only checked for `report.md`.

### 3.7 Subprocess survives dashboard restart

- [ ] Start an experiment, watch the log for a few seconds, then **Ctrl+C** the dashboard in the terminal.
- [ ] Restart `urika dashboard my-test`.
- [ ] Reload the browser. The "Running:" banner should still show the active op (the subprocess kept running). Click the chip → log page shows continuing output. The lock is preserved across restart.

### 3.8 Advisor

- [ ] Click `Advisor` in the sidebar. Existing transcript renders.
- [ ] Submit a question → redirects to the live advisor log page → SSE-streams the agent's work.
- [ ] **Navigate away mid-thought** (click another sidebar link), then click `Advisor` again. The "View running advisor →" link appears (because there's a live `.advisor.lock`). Click → returns to the streaming log.
- [ ] When the advisor finishes, reload `Advisor` → the new exchange is in the transcript.
- [ ] Banner shows an "advisor" chip while it's running.

### 3.9 Settings / privacy / test endpoint

- [ ] `Settings → Privacy` tab. Radio buttons (open / private / hybrid) and checkbox lists are LEFT-aligned, not centered or full-width.
- [ ] Configure a private endpoint with a base URL. Click the **Test endpoint** button (blue, primary). Result line shows either `✓ Reachable: OK` (or `reachable (HTTP 401)` for an auth-protected endpoint) OR `✗ Unreachable: <reason>` (DNS error, connection refused, etc.).
- [ ] Inline help text on the API-key-env-var field clearly says to enter the **NAME** of an env var, not the key value.

### 3.10 Notifications tab

- [ ] Notifications tab — checkboxes per channel (email / slack / telegram), left-aligned, not full-width.
- [ ] Per-channel override fields (extra_to for email, override_chat_id for telegram).

### 3.11 Misc

- [ ] Theme toggle (sidebar footer) → light/dark switches; persists across reloads via `localStorage`.
- [ ] Trashing a project from the dashboard's `Settings → Danger zone` requires typing the project name to confirm.
- [ ] On `/projects`, projects whose folders were deleted manually show a missing tag with an inline `Unregister` button.

---

## 4. Edge cases / smoke

- [ ] Run a full experiment cycle from the dashboard with advisor-first checked. Verify the run doesn't auto-stop after the advisor finishes — should continue to Planning Agent automatically.
- [ ] Have multiple browser tabs open on the same project page while an experiment runs. They should all show the same banner state and update within ~5s.
- [ ] Trash an experiment, recreate one with the same name, trash again. `<project>/trash/` should contain two distinct timestamped entries (no collision).
- [ ] Manually `rm -rf ~/.urika/.advisor.lock` (or any other lock file) while a real agent is running — the running-ops detector should still pick it up via PID liveness on the `.lock` file (locks contain the subprocess PID; deleting them by hand would break the indicator but not kill the agent).

---

## What to flag back

For each broken item, please send:

- The step number (e.g., 3.3)
- What you expected vs. what happened
- The browser console output (F12 → Console tab) if it's a dashboard issue
- The terminal output if it's a CLI / TUI issue
- Your OS + browser version

You can email or Slack me, whichever works.

Thanks!
