# REPL Async Upgrade — Background Orchestration + Chat Agent

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the REPL so users can type during experiment runs (text injection, questions, steering) and add a chat orchestrator for natural language interaction.

**Architecture:** Convert the REPL main loop from synchronous `prompt()` to async `prompt_async()` with `patch_stdout()`. Agent commands run in background threads. User input during runs goes into `session._input_queue` (already exists). Add `OrchestratorChat` (already built in `src/urika/orchestrator/chat.py`) as the free-text handler.

**Tech Stack:** Python 3.11+, prompt_toolkit (async), threading, asyncio, Claude Agent SDK

---

## Task 1: Convert REPL main loop to async

**Files:**
- Modify: `src/urika/repl/main.py`

**What to change:**

The current main loop (line 209-246) uses `prompt_session.prompt()` (synchronous, blocking). Convert to:

```python
# Before:
def run_repl() -> None:
    # ...setup...
    while True:
        user_input = prompt_session.prompt(prompt_text).strip()
        # ...handle input...

# After:
def run_repl() -> None:
    # ...setup...
    asyncio.run(_async_repl_loop(session, prompt_session, ...))

async def _async_repl_loop(session, prompt_session, ...):
    from prompt_toolkit.patch_stdout import patch_stdout
    
    with patch_stdout():
        while True:
            user_input = (await prompt_session.prompt_async(prompt_text)).strip()
            # ...handle input...
```

Key changes:
1. Import `patch_stdout` from `prompt_toolkit.patch_stdout`
2. Wrap the main loop in `async def _async_repl_loop()`
3. Replace `prompt_session.prompt()` with `await prompt_session.prompt_async()`
4. Wrap with `patch_stdout()` context manager
5. Call via `asyncio.run(_async_repl_loop(...))`

The `patch_stdout()` context manager ensures that `print()` calls from background threads don't corrupt the prompt display. This is the standard prompt_toolkit pattern.

**Step 1: Make the change**

Modify `run_repl()` to extract the main loop into `_async_repl_loop()`, change `prompt()` to `prompt_async()`, add `patch_stdout`.

**Step 2: Test**

Run: `pytest tests/ -q --tb=short` — all existing tests should pass (REPL tests don't test the interactive loop).

**Step 3: Manual test**

Launch `urika` and verify:
- Basic slash commands work (`/help`, `/list`, `/project`)
- Free text works (advisor responses)
- Exit with `/quit` or Ctrl+C works cleanly

**Step 4: Commit**

```bash
git commit -m "refactor(repl): convert main loop to async — prompt_async + patch_stdout"
```

---

## Task 2: Run agent commands in background threads

**Files:**
- Modify: `src/urika/repl/main.py` (the `_handle_command` and `_handle_free_text` functions)

**What to change:**

Currently, agent commands (like `/run`, `/advisor`, `/evaluate`) block the main loop. The user can't type until they finish.

For commands that run agents, execute them in a background thread:

```python
async def _handle_command_async(session, text):
    parts = text[1:].split(" ", 1)
    cmd_name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    
    all_cmds = get_all_commands(session)
    if cmd_name not in all_cmds:
        # error handling...
        return
    
    handler = all_cmds[cmd_name]["func"]
    
    # Agent commands run in background — user can keep typing
    AGENT_COMMANDS = {"run", "evaluate", "plan", "advisor", "report",
                      "present", "finalize", "build-tool", "resume"}
    
    if cmd_name in AGENT_COMMANDS:
        if session.agent_active:
            click.echo("  An agent is already running. Use /stop to stop it.")
            return
        # Run in background thread
        def _run_in_background():
            try:
                handler(session, args)
            except Exception as exc:
                print_error(f"Error: {exc}")
            finally:
                session.set_agent_inactive()
        
        session.set_agent_active(cmd_name)
        thread = threading.Thread(target=_run_in_background, daemon=True)
        thread.start()
    else:
        # Instant commands run on main thread
        try:
            handler(session, args)
        except SystemExit as exc:
            if exc.code == 0:
                raise
            click.echo("\n  Cancelled.")
        except click.Abort:
            click.echo("\n  Cancelled.")
        except Exception as exc:
            print_error(f"Error: {exc}")
```

Also handle free text input during an active agent:

```python
async def _handle_free_text_async(session, text):
    if session.agent_active:
        # Agent is running — inject as steering input
        session.queue_input(text)
        click.echo(f"  {_C.DIM}> {text} (queued for {session.active_command}){_C.RESET}")
        return
    
    # No agent running — send to chat orchestrator or advisor
    _handle_free_text(session, text)
```

**Step 1: Implement the async wrappers**

**Step 2: Test**

Run: `pytest tests/ -q --tb=short`

**Step 3: Manual test**

- Start an experiment: `/run`
- While it's running, type: `try a different approach` — should queue
- Verify the ThinkingPanel shows activity
- Type `/status` — should work instantly (not an agent command)
- Type `/stop` — should stop the experiment

**Step 4: Commit**

```bash
git commit -m "feat(repl): run agent commands in background threads — user can type during runs"
```

---

## Task 3: Wire OrchestratorChat as free-text handler

**Files:**
- Modify: `src/urika/repl/main.py` (`_handle_free_text`)
- Modify: `src/urika/orchestrator/chat.py` (may need adjustments)

**What to change:**

Currently, free text goes directly to the advisor agent. Replace with the `OrchestratorChat` agent which:
- Maintains conversation history
- Can read project state (Read, Glob, Grep tools)
- Decides whether to answer directly or call another agent
- Runs via Claude SDK with full tools

```python
# In main.py, add module-level orchestrator:
from urika.orchestrator.chat import OrchestratorChat

_orchestrator: OrchestratorChat | None = None

def _get_orchestrator(session: ReplSession) -> OrchestratorChat:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OrchestratorChat(project_dir=session.project_path)
    elif session.project_path and _orchestrator.project_dir != session.project_path:
        _orchestrator.set_project(session.project_path)
    return _orchestrator

# Replace _handle_free_text:
def _handle_free_text(session: ReplSession, text: str) -> None:
    """Send free text to the chat orchestrator."""
    if not session._private_endpoint_ok:
        click.echo("  Agent commands disabled — local model unreachable.")
        return
    
    orchestrator = _get_orchestrator(session)
    
    from urika.cli_display import Spinner
    spinner = Spinner("Thinking")
    spinner.start()
    
    try:
        response = asyncio.run(orchestrator.chat(text))
        spinner.stop()
        click.echo()
        click.echo(format_agent_output(response))
        click.echo()
        
        # Update session conversation
        session.add_to_conversation("user", text)
        session.add_to_conversation("assistant", response)
    except Exception as exc:
        spinner.stop()
        print_error(f"Error: {exc}")
```

Note: The chat orchestrator works at BOTH global and project level. Without a project, it can still answer questions ("list my projects", "help me create a new one"). With a project, it has full context.

Update `_handle_free_text` to NOT require a project:

```python
def _handle_free_text(session: ReplSession, text: str) -> None:
    """Send free text to the chat orchestrator."""
    orchestrator = _get_orchestrator(session)
    # ... run orchestrator.chat(text) with spinner
```

**Step 1: Wire the orchestrator**

**Step 2: Test**

Run: `pytest tests/ -q --tb=short`

**Step 3: Manual test**

- Type `hello` without a project → should respond conversationally
- Type `/project dht-target-selection-v2` → switch project
- Type `where are we at?` → should read project state and respond
- Type `run experiment 035` → should orchestrator decides to run it

**Step 4: Commit**

```bash
git commit -m "feat(repl): wire OrchestratorChat as free-text handler — conversational AI"
```

---

## Task 4: Add /stop and /pause during background runs

**Files:**
- Modify: `src/urika/repl/commands.py`

**What to change:**

Add `/stop` and `/pause` commands that work during background experiment runs. These should be in GLOBAL_COMMANDS (not project commands) so they work any time.

```python
@command("stop", description="Stop the running agent/experiment")
def cmd_stop(session: ReplSession, args: str) -> None:
    if not session.agent_active:
        click.echo("  No agent is currently running.")
        return
    
    # Write the pause flag for run_experiment's PauseController
    if session.project_path:
        flag = session.project_path / ".urika" / "pause_requested"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("stop", encoding="utf-8")
    
    session.set_agent_inactive()
    click.echo(f"  Stopped {session.active_command}.")

@command("pause", description="Pause experiment after current subagent")
def cmd_pause(session: ReplSession, args: str) -> None:
    if not session.agent_active:
        click.echo("  No agent is currently running.")
        return
    
    if session.project_path:
        flag = session.project_path / ".urika" / "pause_requested"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("pause", encoding="utf-8")
    
    click.echo("  Pausing after current subagent finishes...")
```

**Step 1: Add the commands**

**Step 2: Test**

Run: `pytest tests/ -q --tb=short`

**Step 3: Commit**

```bash
git commit -m "feat(repl): add /stop and /pause commands for background runs"
```

---

## Task 5: Session persistence for orchestrator chat

**Files:**
- Modify: `src/urika/repl/main.py` or `src/urika/repl/commands.py`

**What to change:**

Wire the `OrchestratorChat` conversation history to `orchestrator_sessions.py` (already built). Save after each chat turn, load on project switch.

```python
# After orchestrator.chat() completes:
from urika.core.orchestrator_sessions import save_session, create_new_session

session_data = create_new_session() if not hasattr(session, '_orch_session') else session._orch_session
session_data.recent_messages = orchestrator.get_messages()
session_data.preview = text[:80]
save_session(session.project_path, session_data)
session._orch_session = session_data

# On project switch (/project command):
from urika.core.orchestrator_sessions import get_most_recent

recent = get_most_recent(session.project_path)
if recent:
    click.echo(f"  Previous session from {recent.updated} available. Type /resume to reload.")

# /resume command:
@command("resume", requires_project=True, description="Resume previous orchestrator session")
def cmd_resume_session(session: ReplSession, args: str) -> None:
    from urika.core.orchestrator_sessions import list_sessions, load_session
    
    sessions = list_sessions(session.project_path)
    if not sessions:
        click.echo("  No saved sessions.")
        return
    
    # Show list or resume by number
    # ... (same pattern as the TUI version)
```

**Step 1: Wire session save/load**

**Step 2: Test**

Run: `pytest tests/ -q --tb=short`

**Step 3: Commit**

```bash
git commit -m "feat(repl): orchestrator session persistence — save/resume conversations"
```

---

## Task 6: Clean up TypeScript packages

**Files:**
- Delete: `packages/agent-runtime/` (entire directory)
- Delete: `packages/urika-tui/` (entire directory)
- Delete: `tui/` (if still present)
- Modify: `src/urika/cli/tui.py` — remove or simplify
- Modify: `src/urika/cli/_base.py` — remove TUI launch, REPL is the default

**Step 1: Remove the TS directories**

```bash
rm -rf packages/ tui/
```

**Step 2: Update CLI**

The `urika` command (no args) should launch the REPL directly. Remove the TUI binary search in `_base.py`.

**Step 3: Run tests**

```bash
pytest -q --tb=short
```

All Python tests should pass — they never depended on the TS code.

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove TypeScript TUI packages — REPL is the primary interface"
```

---

## Task 7: Full end-to-end test

Manual testing checklist:

1. `urika` → launches REPL with header
2. `hello` → chat orchestrator responds (no project needed)
3. `/project dht-target-selection-v2` → switches project
4. `where are we at?` → orchestrator reads state, responds
5. `/run` → experiment starts in background
6. Type while running → input queued, injected at next turn
7. `/status` → works during run (instant command)
8. `/pause` → experiment pauses at turn boundary
9. `/stop` → experiment stops
10. `/resume` → resume orchestrator session
11. `/quit` → clean exit

---

## Summary

| Task | What it does | Lines changed |
|------|-------------|---------------|
| 1 | Async main loop | ~30 lines in main.py |
| 2 | Background threads for agents | ~40 lines in main.py |
| 3 | OrchestratorChat as free-text | ~30 lines in main.py |
| 4 | /stop and /pause | ~20 lines in commands.py |
| 5 | Session persistence | ~30 lines |
| 6 | Remove TS packages | delete dirs |
| 7 | End-to-end test | manual |

Total: ~150 lines of Python changes. No new packages, no new languages.
