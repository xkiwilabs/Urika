# Persistent REPL Session Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the notification bus persist across runs in the REPL and enable remote commands (status, results, advisor, run, etc.) from Telegram/Slack.

**Architecture:** Bus starts on `/project X`, lives on `ReplSession`, stays alive until `/quit` or project switch. Remote commands are classified (read-only, run-control, agent) and either executed immediately or queued for the REPL to drain. A `RemoteCommandHandler` on the bus bridges Telegram/Slack to REPL actions.

**Tech Stack:** Existing notifications module, threading for command queue, existing REPL loop.

---

### Task 1: Add session fields for persistent bus and command queue

**Files:**
- Modify: `src/urika/repl_session.py:13-45`
- Test: `tests/test_repl/test_session.py`

**Step 1: Write failing tests**

```python
# In tests/test_repl/test_session.py — add to TestReplSession class

def test_notification_bus_default_none(self) -> None:
    session = ReplSession()
    assert session.notification_bus is None

def test_agent_active_default_false(self) -> None:
    session = ReplSession()
    assert session.agent_active is False
    assert session.active_command == ""

def test_set_agent_active(self) -> None:
    session = ReplSession()
    session.set_agent_active("run")
    assert session.agent_active is True
    assert session.active_command == "run"

def test_set_agent_idle(self) -> None:
    session = ReplSession()
    session.set_agent_active("advisor")
    session.set_agent_idle()
    assert session.agent_active is False
    assert session.active_command == ""

def test_remote_command_queue_empty(self) -> None:
    session = ReplSession()
    assert session.has_remote_command is False
    assert session.pop_remote_command() is None

def test_queue_remote_command(self) -> None:
    session = ReplSession()
    session.queue_remote_command("status", "")
    assert session.has_remote_command is True
    cmd, args = session.pop_remote_command()
    assert cmd == "status"
    assert args == ""
    assert session.has_remote_command is False

def test_queue_multiple_remote_commands(self) -> None:
    session = ReplSession()
    session.queue_remote_command("advisor", "what next?")
    session.queue_remote_command("results", "")
    cmd1, args1 = session.pop_remote_command()
    assert cmd1 == "advisor"
    assert args1 == "what next?"
    cmd2, args2 = session.pop_remote_command()
    assert cmd2 == "results"

def test_clear_remote_queue(self) -> None:
    session = ReplSession()
    session.queue_remote_command("advisor", "test")
    session.queue_remote_command("run", "")
    session.clear_remote_queue()
    assert session.has_remote_command is False

def test_load_project_clears_remote_queue(self, tmp_path) -> None:
    session = ReplSession()
    session.queue_remote_command("run", "")
    session.load_project(tmp_path, "test")
    assert session.has_remote_command is False
```

**Step 2:** Run tests, verify they fail.

Run: `pytest tests/test_repl/test_session.py -v`

**Step 3: Implement session fields**

Add to `ReplSession` dataclass in `src/urika/repl_session.py`:

```python
# After pending_suggestions field (line 24):

# Notification bus — persistent, lives across runs
notification_bus: object = None  # NotificationBus | None (avoid circular import)

# Agent activity — tracks if any command is running
agent_active: bool = False
active_command: str = ""

# Remote command queue — commands from Telegram/Slack
_remote_queue: list[tuple[str, str]] = field(default_factory=list)
_remote_lock: threading.Lock = field(default_factory=threading.Lock)
```

Add methods:

```python
def set_agent_active(self, command: str) -> None:
    """Mark an agent command as active."""
    self.agent_active = True
    self.active_command = command

def set_agent_idle(self) -> None:
    """Mark agent as idle."""
    self.agent_active = False
    self.active_command = ""

@property
def has_remote_command(self) -> bool:
    """Check if there are queued remote commands."""
    with self._remote_lock:
        return len(self._remote_queue) > 0

def queue_remote_command(self, command: str, args: str) -> None:
    """Queue a command from Telegram/Slack for REPL execution."""
    with self._remote_lock:
        self._remote_queue.append((command, args))

def pop_remote_command(self) -> tuple[str, str] | None:
    """Pop the next remote command, or None if empty."""
    with self._remote_lock:
        if self._remote_queue:
            return self._remote_queue.pop(0)
        return None

def clear_remote_queue(self) -> None:
    """Clear all queued remote commands."""
    with self._remote_lock:
        self._remote_queue.clear()
```

Update `load_project()` to clear the remote queue (add after line 77):

```python
self._remote_queue = []
```

**Step 4:** Run tests, verify they pass.

Run: `pytest tests/test_repl/test_session.py -v`

**Step 5: Commit**

```bash
git add src/urika/repl_session.py tests/test_repl/test_session.py
git commit -m "feat: add persistent bus, agent_active, and remote command queue to ReplSession"
```

---

### Task 2: Start/stop bus on project load in REPL

**Files:**
- Modify: `src/urika/repl_commands.py` (cmd_project, around line 64-100)
- Modify: `src/urika/repl.py` (quit handler, line 218-224)

**Step 1: Modify cmd_project to start bus**

In `src/urika/repl_commands.py`, in `cmd_project()`, after `session.load_project(path, name)` (line 90):

```python
# Stop old bus if switching projects
if session.notification_bus is not None:
    try:
        session.notification_bus.stop()
    except Exception:
        pass
    session.notification_bus = None

session.load_project(path, name)

# Start notification bus for this project
try:
    from urika.notifications import build_bus
    bus = build_bus(path)
    if bus is not None:
        bus.start()
        session.notification_bus = bus
except Exception:
    pass  # Notifications are best-effort
```

**Step 2: Stop bus on quit**

In `src/urika/repl.py`, before `session.save_usage()` in the exit handlers (lines 219, 223):

```python
if session.notification_bus is not None:
    try:
        session.notification_bus.stop()
    except Exception:
        pass
```

**Step 3: Stop bus on project switch (in load_project)**

In `src/urika/repl_session.py`, at the start of `load_project()`:

```python
def load_project(self, path: Path, name: str) -> None:
    # Stop existing notification bus
    if self.notification_bus is not None:
        try:
            self.notification_bus.stop()
        except Exception:
            pass
        self.notification_bus = None
    self.save_usage()  # save current project's usage first
    # ... rest unchanged
```

**Step 4: Run tests**

Run: `pytest tests/ -x -q`

**Step 5: Commit**

```bash
git add src/urika/repl_commands.py src/urika/repl.py src/urika/repl_session.py
git commit -m "feat: start notification bus on /project, stop on /quit and project switch"
```

---

### Task 3: Drain remote command queue in REPL loop

**Files:**
- Modify: `src/urika/repl.py` (main loop, lines 197-225)

**Step 1: Add queue drain function**

In `src/urika/repl.py`, add a helper before the main loop:

```python
def _drain_remote_queue(session: ReplSession) -> None:
    """Execute any queued remote commands from Telegram/Slack."""
    while session.has_remote_command:
        item = session.pop_remote_command()
        if item is None:
            break
        cmd, args = item
        cmd_text = f"/{cmd} {args}".strip()
        click.echo(f"\n  [Remote] {cmd_text}")
        _handle_command(session, cmd_text)
```

**Step 2: Call drain in the main loop**

In the REPL main loop, add two drain points:

1. Before the prompt (catches commands that arrived while idle):
```python
# Before user_input = prompt_session.prompt(...)
_drain_remote_queue(session)
```

2. After every command returns:
```python
# After _handle_command() or _handle_free_text()
_drain_remote_queue(session)
```

**Step 3: Run tests**

Run: `pytest tests/ -x -q`

**Step 4: Commit**

```bash
git add src/urika/repl.py
git commit -m "feat: drain remote command queue in REPL loop"
```

---

### Task 4: Wrap agent commands with agent_active flag

**Files:**
- Modify: `src/urika/repl_commands.py`

**Step 1: Wrap all agent commands**

For each of these commands, add `session.set_agent_active("X")` before the agent call and `session.set_agent_idle()` after (in a try/finally):

- `cmd_run` (line ~319) — active_command = "run"
- `cmd_resume` (line ~572) — active_command = "run"
- `_handle_free_text` in repl.py (advisor) — active_command = "advisor"
- `cmd_evaluate` if it exists in REPL — active_command = "evaluate"
- `cmd_plan` — active_command = "plan"
- `cmd_report` — active_command = "report"
- `cmd_present` — active_command = "present"
- `cmd_finalize` — active_command = "finalize"
- `cmd_build_tool` — active_command = "build-tool"

Pattern for each:

```python
def cmd_X(session, args):
    session.set_agent_active("X")
    try:
        # ... existing command logic ...
    finally:
        session.set_agent_idle()
```

For `_handle_free_text` in `repl.py` (advisor call):

```python
def _handle_free_text(session, text):
    # ... existing setup ...
    session.set_agent_active("advisor")
    try:
        # ... existing agent call ...
    finally:
        session.set_agent_idle()
```

**Step 2: Run tests**

Run: `pytest tests/ -x -q`

**Step 3: Commit**

```bash
git add src/urika/repl_commands.py src/urika/repl.py
git commit -m "feat: track agent_active state for all REPL agent commands"
```

---

### Task 5: Add read-only query functions

**Files:**
- Modify: `src/urika/notifications/queries.py`
- Test: `tests/test_notifications/test_queries.py` (new)

**Step 1: Write failing tests**

```python
# tests/test_notifications/test_queries.py
"""Tests for read-only project queries."""

from __future__ import annotations
from pathlib import Path

from urika.notifications.queries import (
    get_status_text,
    get_results_text,
    get_methods_text,
    get_criteria_text,
    get_experiments_text,
    get_usage_text,
)


class TestQueries:
    def test_status_no_project(self, tmp_path):
        assert "not found" in get_status_text(tmp_path).lower()

    def test_results_no_leaderboard(self, tmp_path):
        assert "no results" in get_results_text(tmp_path).lower()

    def test_methods_no_file(self, tmp_path):
        assert "no methods" in get_methods_text(tmp_path).lower()

    def test_criteria_no_file(self, tmp_path):
        assert "no criteria" in get_criteria_text(tmp_path).lower()

    def test_experiments_no_dir(self, tmp_path):
        text = get_experiments_text(tmp_path)
        assert "0" in text or "no experiments" in text.lower()

    def test_usage_no_file(self, tmp_path):
        text = get_usage_text(tmp_path)
        assert "no usage" in text.lower() or "0" in text
```

**Step 2:** Run tests, verify they fail (functions don't exist yet).

**Step 3: Add query functions to queries.py**

Add `get_methods_text`, `get_criteria_text`, `get_experiments_text`, `get_usage_text` to `src/urika/notifications/queries.py`. Each reads the relevant JSON file and returns plain text. Follow the same pattern as `get_status_text` and `get_results_text`.

**Step 4:** Run tests, verify they pass.

**Step 5: Commit**

```bash
git add src/urika/notifications/queries.py tests/test_notifications/test_queries.py
git commit -m "feat: add read-only query functions for methods, criteria, experiments, usage"
```

---

### Task 6: Add RemoteCommandHandler to bus

**Files:**
- Modify: `src/urika/notifications/bus.py`
- Test: `tests/test_notifications/test_bus.py`

**Step 1: Write failing tests**

```python
# Add to tests/test_notifications/test_bus.py

class TestRemoteCommandHandler:
    def test_classify_read_only(self):
        from urika.notifications.bus import classify_remote_command
        assert classify_remote_command("status") == "read_only"
        assert classify_remote_command("results") == "read_only"
        assert classify_remote_command("methods") == "read_only"

    def test_classify_run_control(self):
        from urika.notifications.bus import classify_remote_command
        assert classify_remote_command("pause") == "run_control"
        assert classify_remote_command("stop") == "run_control"
        assert classify_remote_command("resume") == "run_control"

    def test_classify_agent(self):
        from urika.notifications.bus import classify_remote_command
        assert classify_remote_command("run") == "agent"
        assert classify_remote_command("advisor") == "agent"
        assert classify_remote_command("evaluate") == "agent"

    def test_classify_unknown(self):
        from urika.notifications.bus import classify_remote_command
        assert classify_remote_command("config") == "rejected"
        assert classify_remote_command("new") == "rejected"
```

**Step 2:** Run tests, verify they fail.

**Step 3: Implement classify_remote_command**

Add to `src/urika/notifications/bus.py`:

```python
_READ_ONLY_COMMANDS = frozenset(
    {"status", "results", "methods", "criteria", "experiments", "logs", "usage", "help"}
)
_RUN_CONTROL_COMMANDS = frozenset({"pause", "stop", "resume"})
_AGENT_COMMANDS = frozenset(
    {"run", "advisor", "evaluate", "plan", "report", "present", "finalize", "build-tool"}
)


def classify_remote_command(command: str) -> str:
    """Classify a remote command: read_only, run_control, agent, or rejected."""
    cmd = command.lower().strip()
    if cmd in _READ_ONLY_COMMANDS:
        return "read_only"
    if cmd in _RUN_CONTROL_COMMANDS:
        return "run_control"
    if cmd in _AGENT_COMMANDS:
        return "agent"
    return "rejected"
```

**Step 4: Add handle_remote_command to NotificationBus**

Add a method that receives a command from a channel listener and either executes it (read-only), delegates to PauseController (run control), or queues it (agent):

```python
def handle_remote_command(
    self, command: str, args: str = "", respond: Callable[[str], None] | None = None
) -> None:
    """Handle an inbound command from Telegram/Slack.

    - Read-only: execute immediately, send response
    - Run control: delegate to PauseController
    - Agent: queue for REPL, or reject if inappropriate
    """
    category = classify_remote_command(command)
    _respond = respond or (lambda t: None)

    if category == "rejected":
        _respond(f"Command /{command} is not available remotely.")
        return

    if category == "read_only":
        text = self._execute_read_only(command, args)
        _respond(text)
        return

    if category == "run_control":
        self._execute_run_control(command, _respond)
        return

    if category == "agent":
        self._queue_agent_command(command, args, _respond)
        return
```

`_execute_read_only` calls the query functions from `queries.py`.
`_execute_run_control` calls PauseController methods (store controller ref on bus).
`_queue_agent_command` checks `_session.agent_active`, queues or rejects.

The bus needs a reference to the `ReplSession` to check `agent_active` and to queue commands. Add `session` parameter to `start()`:

```python
def start(self, controller=None, session=None):
    self._controller = controller
    self._session = session
    # ... existing start logic
```

**Step 5:** Run tests, verify they pass.

**Step 6: Commit**

```bash
git add src/urika/notifications/bus.py tests/test_notifications/test_bus.py
git commit -m "feat: add remote command handler with classify, execute, and queue logic"
```

---

### Task 7: Wire Telegram listener to remote command handler

**Files:**
- Modify: `src/urika/notifications/telegram_channel.py`

**Step 1: Update listener to route all commands through bus**

The Telegram listener currently handles `/pause`, `/stop`, `/status`, `/results` directly. Change it to route everything through `bus.handle_remote_command()`.

The channel needs a reference to the bus (not just the controller). Update `start_listener` signature:

```python
def start_listener(self, controller, project_path=None, bus=None):
    self._bus = bus
    # ... existing code
```

Update all command handlers to use the bus:

```python
async def _handle_any_command(self, update, context):
    """Route any /command through the bus's remote command handler."""
    if self._bus is None or update.message is None:
        return
    command = update.message.text.lstrip("/").split()[0]
    args = update.message.text.lstrip("/")[len(command):].strip()

    def respond(text):
        # Send response back to Telegram (needs async bridge)
        import asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(update.message.reply_text(text))

    self._bus.handle_remote_command(command, args, respond=respond)
```

Register a catch-all handler in `_run_polling` instead of individual command handlers.

**Step 2: Update bus.start() to pass bus reference to channels**

In `bus.py`, update `start()`:

```python
def start(self, controller=None, session=None):
    self._controller = controller
    self._session = session
    # ... start thread ...
    for ch in self.channels:
        ch.start_listener(controller, project_path=self._project_path, bus=self)
```

Update `base.py` signature to accept `bus`:

```python
def start_listener(self, controller, project_path=None, bus=None):
    pass
```

**Step 3: Do the same for Slack channel**

Same pattern — route all interactions through `bus.handle_remote_command()`.

**Step 4: Run tests**

Run: `pytest tests/ -x -q`

**Step 5: Commit**

```bash
git add src/urika/notifications/telegram_channel.py src/urika/notifications/slack_channel.py src/urika/notifications/bus.py src/urika/notifications/base.py
git commit -m "feat: route all Telegram/Slack commands through bus remote command handler"
```

---

### Task 8: Pass bus from REPL to orchestrator (not create new one)

**Files:**
- Modify: `src/urika/repl_commands.py` (cmd_run)
- Modify: `src/urika/cli.py` (run command, detect REPL bus)

**Step 1: When REPL calls /run, pass the session's existing bus**

The current flow: REPL's `/run` calls `ctx.invoke(cli_run, ...)` which creates its own bus. Change it so the CLI `run()` function detects an existing REPL bus and uses it instead of creating a new one.

In `src/urika/cli.py`, where the bus is created for single experiment path:

```python
# Check if REPL already has a bus running
notif_bus = None
if os.environ.get("URIKA_REPL"):
    try:
        from urika.repl_commands import _get_repl_bus
        notif_bus = _get_repl_bus()
    except (ImportError, Exception):
        pass

if notif_bus is None:
    from urika.notifications import build_bus
    notif_bus = build_bus(project_path)
    if notif_bus is not None:
        notif_bus.start(controller=pause_ctrl)
    _owns_bus = True
else:
    _owns_bus = False
```

In the finally block, only stop if we own it:

```python
if _owns_bus and notif_bus is not None:
    notif_bus.stop()
```

In `src/urika/repl_commands.py`, add a module-level accessor:

```python
_repl_session: ReplSession | None = None

def _get_repl_bus():
    if _repl_session is not None:
        return _repl_session.notification_bus
    return None
```

Set `_repl_session` in `cmd_run` before invoking CLI.

**Step 2: Run tests**

Run: `pytest tests/ -x -q`

**Step 3: Commit**

```bash
git add src/urika/repl_commands.py src/urika/cli.py
git commit -m "feat: REPL passes existing bus to run command instead of creating new one"
```

---

### Task 9: Handle stop clearing queue, pause running queued commands

**Files:**
- Modify: `src/urika/notifications/bus.py`

**Step 1: In _execute_run_control**

```python
def _execute_run_control(self, command, respond):
    if command == "pause":
        if self._controller:
            self._controller.request_pause()
            respond("Pause requested ⏸")
        else:
            respond("No active run to pause.")
    elif command == "stop":
        if self._controller:
            self._controller.request_stop()
            # Clear queued commands on stop
            if self._session:
                self._session.clear_remote_queue()
            respond("Stopped. Queued commands cleared.")
        else:
            respond("No active run to stop.")
    elif command == "resume":
        if self._session and not self._session.agent_active:
            self._session.queue_remote_command("run", "--resume")
            respond("Resume queued.")
        else:
            respond("Cannot resume — agent is active or no session.")
```

**Step 2: Run tests, commit**

```bash
git commit -m "feat: stop clears remote queue, resume queues run --resume"
```

---

### Task 10: Integration tests and documentation update

**Files:**
- Create: `tests/test_repl/test_remote_commands.py`
- Modify: `docs/17-notifications.md`

**Step 1: Integration tests**

Test the full flow: session loads project → bus starts → remote command queued → drain executes it.

```python
class TestRemoteCommandFlow:
    def test_queue_and_drain(self, tmp_path):
        session = ReplSession()
        session.load_project(tmp_path, "test")
        session.queue_remote_command("status", "")
        assert session.has_remote_command
        cmd, args = session.pop_remote_command()
        assert cmd == "status"

    def test_stop_clears_queue(self, tmp_path):
        session = ReplSession()
        session.queue_remote_command("advisor", "what next?")
        session.queue_remote_command("run", "")
        session.clear_remote_queue()
        assert not session.has_remote_command
```

**Step 2: Update docs/17-notifications.md**

Add a section on remote commands, the REPL requirement, and the command table.

**Step 3: Run all tests**

Run: `pytest tests/ -x -q`

**Step 4: Commit**

```bash
git add tests/test_repl/test_remote_commands.py docs/17-notifications.md
git commit -m "test: integration tests for remote commands, update docs"
```

---

## Execution Order

Tasks 1-4 are the foundation (session state, bus lifecycle, queue drain, agent tracking).
Tasks 5-7 add the remote command handling (queries, classification, Telegram/Slack wiring).
Task 8 connects the persistent bus to the run command.
Task 9 handles edge cases (stop/pause queue behavior).
Task 10 is testing and docs.

Tasks are sequential — each builds on the previous.
