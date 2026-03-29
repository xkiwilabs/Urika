# Unified Terminal Interface Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign Urika's terminal experience into a scriptable CLI (with `--json` and proper interactive prompts) and a unified always-on-input interface.

**Architecture:** CLI commands stay Click-based but use prompt_toolkit for interactive inputs and support `--json` output. The REPL is rewritten into a unified three-zone interface (output stream / input line / status bar) where the user can type while agents run. No changes to the agentic pipeline.

**Tech Stack:** Click (CLI framework), prompt_toolkit (interactive input + unified interface), existing cli_display.py (ANSI rendering)

---

### Task 1: Create shared CLI helpers

**Files:**
- Create: `src/urika/cli_helpers.py`
- Test: `tests/test_cli_helpers.py`

**Step 1: Write the failing tests**

```python
"""Tests for CLI helper functions."""

import json
import io
import sys
from unittest.mock import patch

import pytest


def test_output_json_writes_to_stdout(capsys):
    from urika.cli_helpers import output_json

    output_json({"key": "value"})
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == {"key": "value"}


def test_output_json_pretty_prints(capsys):
    from urika.cli_helpers import output_json

    output_json({"a": 1})
    captured = capsys.readouterr()
    assert "\n" in captured.out  # indented


def test_output_json_error_to_stderr(capsys):
    from urika.cli_helpers import output_json_error

    output_json_error("something broke")
    captured = capsys.readouterr()
    data = json.loads(captured.err)
    assert data == {"error": "something broke"}


def test_is_scripted_when_not_tty():
    from urika.cli_helpers import is_scripted

    # When --json is passed, always scripted
    assert is_scripted(json_flag=True) is True


def test_interactive_prompt_returns_input():
    from urika.cli_helpers import interactive_prompt

    with patch("urika.cli_helpers._pt_prompt", return_value="hello"):
        result = interactive_prompt("Enter value")
        assert result == "hello"


def test_interactive_prompt_default():
    from urika.cli_helpers import interactive_prompt

    with patch("urika.cli_helpers._pt_prompt", return_value=""):
        result = interactive_prompt("Enter", default="fallback")
        assert result == "fallback"


def test_interactive_confirm_yes():
    from urika.cli_helpers import interactive_confirm

    with patch("urika.cli_helpers._pt_prompt", return_value="y"):
        assert interactive_confirm("Continue?") is True


def test_interactive_confirm_no():
    from urika.cli_helpers import interactive_confirm

    with patch("urika.cli_helpers._pt_prompt", return_value="n"):
        assert interactive_confirm("Continue?") is False
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_helpers.py -v`
Expected: FAIL (module not found)

**Step 3: Write the implementation**

```python
"""Shared CLI helpers — JSON output, interactive prompts, pipe detection."""

from __future__ import annotations

import json
import sys
from typing import Any

import click


def output_json(data: Any) -> None:
    """Write structured JSON to stdout and exit."""
    click.echo(json.dumps(data, indent=2, default=str))


def output_json_error(message: str) -> None:
    """Write a JSON error to stderr."""
    sys.stderr.write(json.dumps({"error": message}) + "\n")


def is_scripted(*, json_flag: bool = False) -> bool:
    """Check if running in scripted/piped mode.

    Returns True when output should be machine-readable:
    - --json flag is set
    - stdout is not a TTY (piped)
    """
    if json_flag:
        return True
    return not sys.stdout.isatty()


# --- prompt_toolkit interactive prompts ---

def _pt_prompt(message: str, **kwargs: Any) -> str:
    """Wrapper around prompt_toolkit.prompt for mocking."""
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.history import InMemoryHistory

    # Shared history across prompts in a session
    if not hasattr(_pt_prompt, "_history"):
        _pt_prompt._history = InMemoryHistory()

    return pt_prompt(
        message,
        history=_pt_prompt._history,
        **kwargs,
    )


def interactive_prompt(
    message: str,
    *,
    default: str = "",
    required: bool = False,
) -> str:
    """Prompt for text input using prompt_toolkit.

    Supports arrow keys, history, multi-line paste.
    Falls back to click.prompt if prompt_toolkit unavailable.
    """
    suffix = f" [{default}]" if default else ""
    display = f"  {message}{suffix}: "

    try:
        result = _pt_prompt(display).strip()
        if not result and default:
            return default
        if not result and required:
            click.echo("  Value required.")
            return interactive_prompt(
                message, default=default, required=required
            )
        return result
    except (EOFError, KeyboardInterrupt):
        if default:
            return default
        raise click.Abort()


def interactive_confirm(
    message: str,
    *,
    default: bool = True,
) -> bool:
    """Yes/no confirmation using prompt_toolkit."""
    hint = "Y/n" if default else "y/N"
    display = f"  {message} [{hint}]: "

    try:
        result = _pt_prompt(display).strip().lower()
        if not result:
            return default
        return result in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return default


def interactive_numbered(
    prompt_text: str,
    options: list[str],
    *,
    default: int = 1,
) -> str:
    """Prompt with numbered options using prompt_toolkit.

    Returns the selected option text.
    """
    click.echo(prompt_text)
    for i, opt in enumerate(options, 1):
        marker = " (default)" if i == default else ""
        click.echo(f"    {i}. {opt}{marker}")

    while True:
        try:
            raw = _pt_prompt(f"  Choice [{default}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return options[default - 1]
        if not raw:
            return options[default - 1]
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass
        click.echo(
            f"  Enter a number between 1 and {len(options)}."
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_helpers.py -v`
Expected: PASS (all 8 tests)

**Step 5: Commit**

```bash
git add src/urika/cli_helpers.py tests/test_cli_helpers.py
git commit -m "feat: add CLI helpers — JSON output, prompt_toolkit prompts, pipe detection"
```

---

### Task 2: Replace click.prompt in `_prompt_numbered` and `_prompt_path`

**Files:**
- Modify: `src/urika/cli.py`
- Test: `tests/test_cli.py` (existing tests must still pass)

**Step 1: Replace `_prompt_numbered` to use `interactive_numbered`**

In `src/urika/cli.py`, find `_prompt_numbered` (around line 141) and replace the body to delegate to the new helper:

```python
def _prompt_numbered(prompt_text: str, options: list[str], default: int = 1) -> str:
    """Prompt user with numbered options. Returns the selected option text."""
    from urika.cli_helpers import interactive_numbered

    return interactive_numbered(prompt_text, options, default=default)
```

**Step 2: Replace `_prompt_path` to use `interactive_prompt`**

In `src/urika/cli.py`, find `_prompt_path` (around line 158) and replace `click.prompt` with `interactive_prompt`:

```python
def _prompt_path(prompt_text: str, must_exist: bool = True) -> str | None:
    """Prompt for a path, re-asking if it doesn't exist. Empty = skip."""
    from urika.cli_helpers import interactive_prompt

    while True:
        raw = interactive_prompt(prompt_text).strip()
        if not raw:
            return None
        resolved = Path(raw).resolve()
        if not must_exist or resolved.exists():
            return str(resolved)
        click.echo(f"  Path not found: {raw}")
        click.echo("  Please check the path and try again.")
```

**Step 3: Run existing tests**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (all existing tests)

**Step 4: Commit**

```bash
git add src/urika/cli.py
git commit -m "refactor: replace click.prompt with prompt_toolkit in shared helpers"
```

---

### Task 3: Replace click.prompt in `urika new`

**Files:**
- Modify: `src/urika/cli.py` (the `new` command, ~lines 185-580)

**Step 1: Replace all `click.prompt()` calls in the `new` function**

Find every `click.prompt(...)` and `click.confirm(...)` in the `new` command and replace with `interactive_prompt(...)` and `interactive_confirm(...)` from `cli_helpers`.

Key replacements:
- `click.prompt("Project name")` → `interactive_prompt("Project name", required=True)`
- `click.prompt("  Private endpoint URL", default=...)` → `interactive_prompt("Private endpoint URL", default=...)`
- `click.prompt("Research question")` → `interactive_prompt("Research question", required=True)`
- `click.confirm("...", default=True)` → `interactive_confirm("...", default=True)`
- `click.prompt("Describe...", default="")` → `interactive_prompt("Describe the project")`

Also replace the prompts in `_run_builder_agent_loop` (around line 771) where the agent asks questions and the user answers.

**Step 2: Run existing tests**

Run: `pytest tests/test_cli.py -v`
Expected: PASS — tests that supply input via `click.testing.CliRunner` may need the mock patched to `cli_helpers._pt_prompt` instead. Update test fixtures as needed.

**Step 3: Manual test**

Run: `urika new` — verify arrow keys work, multi-line paste doesn't skip prompts, Ctrl+C aborts cleanly.

**Step 4: Commit**

```bash
git add src/urika/cli.py tests/test_cli.py
git commit -m "refactor: replace click.prompt with prompt_toolkit in urika new"
```

---

### Task 4: Replace click.prompt in remaining CLI commands

**Files:**
- Modify: `src/urika/cli.py` (commands: `update`, `run`, `setup`, `advisor`, `build_tool`, `present`, `report`)

**Step 1: Find and replace remaining click.prompt/click.confirm calls**

Search for all remaining `click.prompt` and `click.confirm` in `cli.py` outside of the `new` command. Replace with the prompt_toolkit equivalents.

Commands affected:
- `update_project` — field selection, value input, reason
- `run` — settings dialog, experiment selection, instructions
- `setup_command` — DL install choice
- `advisor` — instructions prompt
- `build_tool` — instructions prompt
- `present` / `report` — experiment selection prompts

**Step 2: Run tests**

Run: `pytest tests/ -x --tb=short`
Expected: PASS

**Step 3: Commit**

```bash
git add src/urika/cli.py
git commit -m "refactor: replace all click.prompt with prompt_toolkit across CLI"
```

---

### Task 5: Add `--json` flag to read-only commands

**Files:**
- Modify: `src/urika/cli.py`
- Test: `tests/test_cli_json.py` (new file)

**Step 1: Write failing tests for JSON output**

```python
"""Tests for --json flag on CLI commands."""

import json

from click.testing import CliRunner

from urika.cli import cli


def test_list_json(tmp_path, monkeypatch):
    """urika list --json returns JSON array of projects."""
    runner = CliRunner()
    result = runner.invoke(cli, ["list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "projects" in data


def test_tools_json():
    """urika tools --json returns JSON with tools array."""
    runner = CliRunner()
    result = runner.invoke(cli, ["tools", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "tools" in data
    assert len(data["tools"]) == 18


def test_config_json():
    """urika config --json returns settings."""
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "--show", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, dict)


def test_setup_json():
    """urika setup --json returns packages and hardware."""
    runner = CliRunner()
    result = runner.invoke(cli, ["setup", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "packages" in data
    assert "hardware" in data
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_json.py -v`
Expected: FAIL (no --json flag exists yet)

**Step 3: Add `--json` to read-only commands**

For each command, add `@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")` and wrap the output logic:

```python
# Pattern for each command:
@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def list_cmd(json_output: bool) -> None:
    # ... existing logic to build data ...
    if json_output:
        from urika.cli_helpers import output_json
        output_json({"projects": projects_data})
        return
    # ... existing human-readable output ...
```

Apply this pattern to: `list_cmd`, `status`, `results`, `methods`, `tools`, `usage`, `criteria`, `inspect`, `logs`, `config_command`, `setup_command`.

**Step 4: Run tests**

Run: `pytest tests/test_cli_json.py tests/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/urika/cli.py tests/test_cli_json.py
git commit -m "feat: add --json flag to read-only CLI commands"
```

---

### Task 6: Add `--json` flag to action commands

**Files:**
- Modify: `src/urika/cli.py`
- Modify: `tests/test_cli_json.py`

**Step 1: Add `--json` to action commands**

Apply the same pattern to: `new`, `run`, `finalize`, `evaluate`, `report`, `present`, `update_project`, `knowledge` subcommands.

For action commands, `--json` suppresses all visual output (spinners, ThinkingPanel) and outputs the result on completion:

```python
@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def finalize(project, instructions, json_output):
    if json_output:
        # Suppress all visual output
        on_progress = lambda e, d="": None
        on_message = lambda m: None
    else:
        # ... existing visual output setup ...

    result = asyncio.run(finalize_project(...))

    if json_output:
        from urika.cli_helpers import output_json
        output_json(result)
        return
    # ... existing human-readable output ...
```

**Step 2: Run tests**

Run: `pytest tests/ -x --tb=short`
Expected: PASS

**Step 3: Commit**

```bash
git add src/urika/cli.py tests/test_cli_json.py
git commit -m "feat: add --json flag to action CLI commands"
```

---

### Task 7: Auto-quiet when piped

**Files:**
- Modify: `src/urika/cli_display.py`
- Modify: `src/urika/cli.py`

**Step 1: Ensure cli_display already handles non-TTY**

Verify that `_IS_TTY` check in `cli_display.py` already gates all visual output. The Spinner `__enter__` (line ~597) already checks `_IS_TTY`. ThinkingPanel `activate()` already checks `_IS_TTY`. Colors already disabled when not TTY.

**Step 2: Ensure CLI commands skip ThinkingPanel when piped**

In the `run` command and other commands that create a ThinkingPanel, the `activate()` call already no-ops when not TTY. Verify this is sufficient — no additional changes should be needed.

**Step 3: Test piped output**

Run: `python -m urika list 2>/dev/null | cat`
Expected: Clean output, no ANSI codes, no spinners.

Run: `python -m urika tools 2>/dev/null | cat`
Expected: Clean output.

**Step 4: Commit (if any changes needed)**

```bash
git add src/urika/cli_display.py src/urika/cli.py
git commit -m "fix: ensure clean output when stdout is piped"
```

---

### Task 8: Unified interface — input queue

**Files:**
- Modify: `src/urika/repl_session.py`
- Test: `tests/test_repl/test_session.py` (add tests)

**Step 1: Write failing tests**

```python
def test_input_queue_empty_by_default():
    from urika.repl_session import ReplSession

    session = ReplSession()
    assert session.has_queued_input is False
    assert session.pop_queued_input() == ""


def test_input_queue_stores_and_retrieves():
    from urika.repl_session import ReplSession

    session = ReplSession()
    session.queue_input("try random forest")
    assert session.has_queued_input is True
    text = session.pop_queued_input()
    assert text == "try random forest"
    assert session.has_queued_input is False


def test_input_queue_concatenates_multiple():
    from urika.repl_session import ReplSession

    session = ReplSession()
    session.queue_input("first instruction")
    session.queue_input("second instruction")
    text = session.pop_queued_input()
    assert "first instruction" in text
    assert "second instruction" in text
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_repl/test_session.py::test_input_queue_empty_by_default -v`
Expected: FAIL

**Step 3: Add input queue to ReplSession**

In `src/urika/repl_session.py`, add:

```python
class ReplSession:
    def __init__(self):
        # ... existing init ...
        self._input_queue: list[str] = []

    @property
    def has_queued_input(self) -> bool:
        return len(self._input_queue) > 0

    def queue_input(self, text: str) -> None:
        """Queue user input for injection into the next agent call."""
        if text.strip():
            self._input_queue.append(text.strip())

    def pop_queued_input(self) -> str:
        """Pop all queued input as a single string. Clears the queue."""
        if not self._input_queue:
            return ""
        combined = "\n".join(self._input_queue)
        self._input_queue.clear()
        return combined
```

**Step 4: Run tests**

Run: `pytest tests/test_repl/test_session.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/urika/repl_session.py tests/test_repl/test_session.py
git commit -m "feat: add input queue to ReplSession for async user input"
```

---

### Task 9: Unified interface — three-zone layout

**Files:**
- Modify: `src/urika/repl.py` (major rewrite of `run_repl()`)
- Modify: `src/urika/cli_display.py` (add unified status bar renderer)

**Step 1: Create the unified status bar renderer**

In `src/urika/cli_display.py`, add a `UnifiedStatusBar` class that renders the 2-line combined status bar using ANSI scroll regions (same approach as ThinkingPanel):

```python
class UnifiedStatusBar:
    """Persistent 2-line status bar for the unified interface.

    Renders below the prompt_toolkit input, using ANSI scroll regions.
    Line 1: project · privacy · turn · agent · activity
    Line 2: model · tokens · cost · elapsed
    """

    def __init__(self) -> None:
        self.project = ""
        self.privacy_mode = ""
        self.turn = ""
        self.agent = ""
        self.activity = ""
        self.model = ""
        self.tokens = 0
        self.cost = 0.0
        self.start = time.monotonic()
        self._active = False
        self._rows = 0
        self._cols = 0
        self._lock = threading.Lock()

    def activate(self) -> None:
        """Set up scroll region reserving 4 bottom lines
        (1 separator + 1 input + 2 status)."""
        # Similar to ThinkingPanel.activate()
        ...

    def render(self) -> None:
        """Render the 2 status lines."""
        ...

    def update(self, **kwargs) -> None:
        """Update fields and re-render."""
        ...

    def cleanup(self) -> None:
        """Reset scroll region."""
        ...
```

**Step 2: Rewrite the REPL main loop**

In `src/urika/repl.py`, restructure `run_repl()` to use the three-zone layout:

```python
def run_repl() -> None:
    session = ReplSession()
    status_bar = UnifiedStatusBar()

    # Show header
    print_header()
    # ... stats, update check ...

    status_bar.activate()

    # Use prompt_toolkit with bottom_toolbar replaced by
    # the UnifiedStatusBar rendered via scroll regions.
    # The prompt_toolkit session provides the input line.

    prompt_session = PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
        # No bottom_toolbar — we use UnifiedStatusBar instead
    )

    while True:
        # Input is always available
        user_input = prompt_session.prompt(prompt_text)

        if _is_agent_running:
            # Queue for next agent
            session.queue_input(user_input)
        else:
            # Process immediately
            _handle_input(user_input, session, status_bar)
```

**Step 3: Wire agent runs to accept queued input**

In the REPL command handlers that run agents (cmd_run, cmd_finalize, etc.), check for queued input and prepend it to the agent prompt:

```python
# In the on_progress callback for agent runs:
def _on_progress(event, detail=""):
    queued = session.pop_queued_input()
    if queued:
        # Inject into next agent's instructions
        ...
```

**Step 4: Test manually**

Run: `urika`
- Verify three-zone layout renders correctly
- Type while an agent runs — verify text is queued
- Verify `/commands` still work
- Verify free text goes to advisor
- Verify Ctrl+C stops agent, returns to input
- Verify Ctrl+D exits

**Step 5: Commit**

```bash
git add src/urika/repl.py src/urika/cli_display.py
git commit -m "feat: unified three-zone interface with always-on input"
```

---

### Task 10: Wire queued input into orchestrator

**Files:**
- Modify: `src/urika/repl_commands.py` (the `cmd_run` handler)
- Modify: `src/urika/orchestrator/loop.py` (accept injected instructions)

**Step 1: Pass queued input callback to orchestrator**

The orchestrator's `on_progress` callback is called between agents. Add a new callback `get_user_input` that the orchestrator calls before each agent to check for queued input:

```python
# In repl_commands.py cmd_run:
def _get_user_input() -> str:
    return session.pop_queued_input()

result = asyncio.run(
    run_experiment(
        ...,
        get_user_input=_get_user_input,
    )
)
```

In `orchestrator/loop.py`, before each agent call, check for user input:

```python
# Before advisor agent call:
user_inject = ""
if get_user_input is not None:
    user_inject = get_user_input()
if user_inject:
    suggest_prompt = user_inject + "\n\n" + suggest_prompt
```

**Step 2: Test manually**

Run: `urika`, then `/run`, then type instructions while the task agent is running. Verify the advisor receives them.

**Step 3: Commit**

```bash
git add src/urika/repl_commands.py src/urika/orchestrator/loop.py
git commit -m "feat: wire queued user input into orchestrator loop"
```

---

### Task 11: Make `/new` fully inline in unified interface

**Files:**
- Modify: `src/urika/repl_commands.py` (the `cmd_new` handler)

**Step 1: Replace ctx.invoke with inline flow**

The current `cmd_new` uses `ctx.invoke(cli_new, ...)` which launches the CLI command. Instead, rewrite it to run the project creation flow inline using the prompt_toolkit input that's already active in the unified interface.

The questions appear in the output stream (above the input line). The user answers in the input line. This is natural because `interactive_prompt()` from `cli_helpers.py` uses prompt_toolkit which integrates with the existing session.

**Step 2: Auto-load the created project**

After project creation, automatically call `session.load_project(name)` so the user is immediately in the new project context.

**Step 3: Test manually**

Run: `urika`, then `/new`. Verify the full project creation flow works inline — questions stream above, answers in the input line, project is loaded when done.

**Step 4: Commit**

```bash
git add src/urika/repl_commands.py
git commit -m "feat: inline /new flow in unified interface"
```

---

### Task 12: Final integration test and cleanup

**Files:**
- Run: all tests
- Modify: any files with issues found

**Step 1: Run full test suite**

Run: `pytest tests/ -x --tb=short -v`
Expected: All tests pass (906+)

**Step 2: Run linter**

Run: `ruff check src/ --select F,W`
Expected: No errors

**Step 3: Manual integration test checklist**

- [ ] `urika new` from CLI — arrow keys work, multi-line paste works
- [ ] `urika new --data ./d.csv --question "..." --json` — returns JSON, no prompts
- [ ] `urika list --json` — valid JSON
- [ ] `urika results my-study --json` — valid JSON
- [ ] `urika tools --json` — 18 tools in JSON
- [ ] `urika run my-study --auto --quiet` — no visual noise
- [ ] `urika list | cat` — no ANSI codes
- [ ] `urika` — unified interface launches, three zones visible
- [ ] Type while agent runs — input queued, injected into next agent
- [ ] `/new` in unified interface — inline flow works
- [ ] Ctrl+C during agent — stops gracefully
- [ ] Ctrl+D — exits cleanly

**Step 4: Commit any remaining fixes**

```bash
git add -A
git commit -m "fix: integration test fixes for unified interface"
```

**Step 5: Push and release**

```bash
git push origin dev
bash dev/scripts/release-to-main.sh
```
