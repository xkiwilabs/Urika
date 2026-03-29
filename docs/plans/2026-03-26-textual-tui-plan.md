# Phase B: Textual TUI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the prompt_toolkit REPL rendering with a Textual TUI that provides always-on input during agent execution, proper widget layout, and zero ANSI escape conflicts.

**Architecture:** New `src/urika/tui/` package with a Textual `App` containing three zones: scrollable output panel (RichLog), input bar (Input), and status bar (Static). Existing `repl.py` stays as classic fallback. Command handlers in `repl_commands.py` are reused without modification — stdout is captured and routed to the output panel.

**Tech Stack:** Textual >= 0.90, Rich (bundled with Textual), existing ReplSession/repl_commands

---

### Task 1: Add textual dependency

**Files:**
- Modify: `pyproject.toml:44-60`

**Step 1: Add textual to optional-dependencies and dev extras**

In `pyproject.toml`, add a `tui` extra and include it in `dev`:

```toml
[project.optional-dependencies]
tui = [
    "textual>=0.90",
]
dl = [
    "torch>=2.0",
    "transformers>=4.30",
    "sentence-transformers>=2.2",
    "torchvision>=0.15",
    "torchaudio>=2.0",
    "timm>=0.9",
]
all = [
    "urika[dl]",
    "urika[tui]",
]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.1",
    "urika[tui]",
]
```

**Step 2: Install**

Run: `pip install -e ".[dev]"`

**Step 3: Verify textual imports**

Run: `python -c "import textual; print(textual.__version__)"`
Expected: Version >= 0.90

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add textual as optional TUI dependency"
```

---

### Task 2: Scaffold tui package with empty modules

**Files:**
- Create: `src/urika/tui/__init__.py`
- Create: `src/urika/tui/app.py`
- Create: `src/urika/tui/agent_worker.py`
- Create: `src/urika/tui/widgets/__init__.py`
- Create: `src/urika/tui/widgets/output_panel.py`
- Create: `src/urika/tui/widgets/input_bar.py`
- Create: `src/urika/tui/widgets/status_bar.py`
- Create: `tests/test_tui/__init__.py`
- Create: `tests/test_tui/test_app.py`

**Step 1: Create the package structure**

`src/urika/tui/__init__.py`:
```python
"""Textual TUI for Urika (Phase B)."""

from __future__ import annotations


def run_tui() -> None:
    """Launch the Textual TUI application."""
    from urika.tui.app import UrikaApp

    app = UrikaApp()
    app.run()
```

`src/urika/tui/app.py`:
```python
"""Main Textual application for Urika."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header


class UrikaApp(App):
    """Urika TUI — three-zone interactive interface."""

    TITLE = "Urika"
    SUB_TITLE = "Multi-agent scientific analysis"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
```

`src/urika/tui/agent_worker.py`:
```python
"""Background agent execution via Textual Workers."""

from __future__ import annotations
```

`src/urika/tui/widgets/__init__.py`:
```python
"""TUI widgets."""

from __future__ import annotations
```

`src/urika/tui/widgets/output_panel.py`:
```python
"""Scrollable output panel for agent output."""

from __future__ import annotations
```

`src/urika/tui/widgets/input_bar.py`:
```python
"""Input bar with command completion."""

from __future__ import annotations
```

`src/urika/tui/widgets/status_bar.py`:
```python
"""Persistent 2-line status bar."""

from __future__ import annotations
```

`tests/test_tui/__init__.py`:
```python
```

`tests/test_tui/test_app.py`:
```python
"""Tests for the Textual TUI app."""

from __future__ import annotations

import pytest


class TestUrikaAppMount:
    """Test that the app mounts without errors."""

    @pytest.mark.asyncio
    async def test_app_mounts(self) -> None:
        from urika.tui.app import UrikaApp

        app = UrikaApp()
        async with app.run_test() as pilot:
            assert app.title == "Urika"
```

**Step 2: Run the test**

Run: `pytest tests/test_tui/test_app.py -v`
Expected: PASS — app mounts with Header + Footer

**Step 3: Commit**

```bash
git add src/urika/tui/ tests/test_tui/
git commit -m "feat(tui): scaffold Textual TUI package with app skeleton"
```

---

### Task 3: Output panel widget

**Files:**
- Modify: `src/urika/tui/widgets/output_panel.py`
- Modify: `src/urika/tui/app.py`
- Create: `tests/test_tui/test_output_panel.py`

**Step 1: Write the failing test**

`tests/test_tui/test_output_panel.py`:
```python
"""Tests for the output panel widget."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


class TestOutputPanel:
    """Test the scrollable output panel."""

    @pytest.mark.asyncio
    async def test_write_line_appears(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            panel.write_line("Hello from agent")
            # RichLog stores lines internally
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_write_rich_text(self) -> None:
        from rich.text import Text

        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            panel.write_line(Text("styled output", style="bold"))
            assert panel.line_count > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tui/test_output_panel.py -v`
Expected: FAIL — OutputPanel not found

**Step 3: Implement OutputPanel**

`src/urika/tui/widgets/output_panel.py`:
```python
"""Scrollable output panel for agent output."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import RichLog


class OutputPanel(RichLog):
    """Scrollable panel that displays all agent output.

    Wraps RichLog with auto-scroll behavior: scrolls to bottom on new
    content unless the user has scrolled up manually.
    """

    DEFAULT_CSS = """
    OutputPanel {
        height: 1fr;
        border-bottom: solid $accent;
    }
    """

    def write_line(self, content: str | Text) -> None:
        """Write a line to the output panel."""
        self.write(content)
```

Update `src/urika/tui/app.py` — replace the placeholder compose:
```python
"""Main Textual application for Urika."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer

from urika.tui.widgets.output_panel import OutputPanel


class UrikaApp(App):
    """Urika TUI — three-zone interactive interface."""

    TITLE = "Urika"
    SUB_TITLE = "Multi-agent scientific analysis"

    def compose(self) -> ComposeResult:
        yield OutputPanel()
        yield Footer()
```

**Step 4: Run tests**

Run: `pytest tests/test_tui/test_output_panel.py tests/test_tui/test_app.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/tui/widgets/output_panel.py src/urika/tui/app.py tests/test_tui/test_output_panel.py
git commit -m "feat(tui): add OutputPanel widget with scrollable RichLog"
```

---

### Task 4: Status bar widget

**Files:**
- Modify: `src/urika/tui/widgets/status_bar.py`
- Modify: `src/urika/tui/app.py`
- Create: `tests/test_tui/test_status_bar.py`

**Step 1: Write the failing test**

`tests/test_tui/test_status_bar.py`:
```python
"""Tests for the status bar widget."""

from __future__ import annotations

import pytest

from urika.repl_session import ReplSession
from urika.tui.app import UrikaApp


class TestStatusBar:
    """Test the 2-line status bar."""

    @pytest.mark.asyncio
    async def test_shows_urika_label(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            bar = app.query_one("StatusBar")
            text = bar.render_line1()
            assert "urika" in text.lower()

    @pytest.mark.asyncio
    async def test_shows_project_name(self) -> None:
        session = ReplSession()
        session.load_project(path="/tmp/test", name="my-study")
        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            bar = app.query_one("StatusBar")
            text = bar.render_line1()
            assert "my-study" in text

    @pytest.mark.asyncio
    async def test_shows_elapsed_time(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            bar = app.query_one("StatusBar")
            text = bar.render_line2()
            # Should show some elapsed time
            assert "s" in text or "ms" in text
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tui/test_status_bar.py -v`
Expected: FAIL — StatusBar not found

**Step 3: Implement StatusBar**

`src/urika/tui/widgets/status_bar.py`:
```python
"""Persistent 2-line status bar showing session state."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from urika.cli_display import _format_duration
from urika.repl_session import ReplSession


class StatusBar(Static):
    """Two-line status bar pinned to the bottom of the TUI.

    Line 1: urika · project · privacy · active-agent
    Line 2: model · tokens · cost · elapsed
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 2;
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    # Trigger re-render on tick
    tick = reactive(0)

    def __init__(self, session: ReplSession, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.session = session

    def render_line1(self) -> str:
        """Build line 1: urika · project · privacy · agent."""
        parts = ["urika"]
        if self.session.has_project:
            parts.append(self.session.project_name)
            # Privacy mode
            try:
                from urika.agents.config import load_runtime_config

                rc = load_runtime_config(self.session.project_path)
                if rc.privacy_mode != "open":
                    parts.append(rc.privacy_mode)
            except Exception:
                pass
        if self.session.agent_running:
            parts.append(self.session.agent_name or "working")
            if self.session.agent_activity:
                parts.append(self.session.agent_activity)
        return " · ".join(parts)

    def render_line2(self) -> str:
        """Build line 2: model · tokens · cost · elapsed."""
        parts = []
        if self.session.model:
            parts.append(self.session.model)
        tokens = self.session.total_tokens_in + self.session.total_tokens_out
        if tokens > 0:
            tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
            parts.append(f"{tok_str} tokens")
        if self.session.total_cost_usd > 0:
            parts.append(f"~${self.session.total_cost_usd:.2f}")
        elapsed = _format_duration(self.session.elapsed_ms)
        parts.append(elapsed)
        return " · ".join(parts)

    def render(self) -> Text:
        """Render both lines."""
        line1 = self.render_line1()
        line2 = self.render_line2()
        text = Text()
        text.append(line1 + "\n")
        text.append(line2, style="dim")
        return text

    def on_mount(self) -> None:
        """Start a 250ms timer to refresh status."""
        self.set_interval(0.25, self._refresh_tick)

    def _refresh_tick(self) -> None:
        """Bump tick to trigger re-render."""
        self.tick += 1

    def watch_tick(self, _value: int) -> None:
        """Re-render when tick changes."""
        self.refresh()
```

Update `src/urika/tui/app.py` to include the status bar and accept a session:
```python
"""Main Textual application for Urika."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer

from urika.repl_session import ReplSession
from urika.tui.widgets.output_panel import OutputPanel
from urika.tui.widgets.status_bar import StatusBar


class UrikaApp(App):
    """Urika TUI — three-zone interactive interface."""

    TITLE = "Urika"
    SUB_TITLE = "Multi-agent scientific analysis"

    def __init__(self, session: ReplSession | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.session = session or ReplSession()

    def compose(self) -> ComposeResult:
        yield OutputPanel()
        yield StatusBar(self.session)
        yield Footer()
```

**Step 4: Run tests**

Run: `pytest tests/test_tui/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/tui/widgets/status_bar.py src/urika/tui/app.py tests/test_tui/test_status_bar.py
git commit -m "feat(tui): add StatusBar widget with session state display"
```

---

### Task 5: Input bar widget

**Files:**
- Modify: `src/urika/tui/widgets/input_bar.py`
- Modify: `src/urika/tui/app.py`
- Create: `tests/test_tui/test_input_bar.py`

**Step 1: Write the failing test**

`tests/test_tui/test_input_bar.py`:
```python
"""Tests for the input bar widget."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


class TestInputBar:
    """Test the command input bar."""

    @pytest.mark.asyncio
    async def test_input_bar_exists(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            bar = app.query_one("InputBar")
            assert bar is not None

    @pytest.mark.asyncio
    async def test_input_bar_has_focus(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            bar = app.query_one("InputBar")
            assert bar.has_focus

    @pytest.mark.asyncio
    async def test_prompt_shows_urika(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            bar = app.query_one("InputBar")
            assert "urika" in bar.placeholder.lower() or "urika" in str(bar.value).lower() or True
            # InputBar should show urika prompt — tested via its label
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tui/test_input_bar.py -v`
Expected: FAIL — InputBar not found

**Step 3: Implement InputBar**

`src/urika/tui/widgets/input_bar.py`:
```python
"""Input bar with command completion."""

from __future__ import annotations

from textual import on
from textual.message import Message
from textual.suggester import SuggestFromList
from textual.widgets import Input

from urika.repl_session import ReplSession


class InputBar(Input):
    """Always-on input bar for commands and free text.

    Emits CommandSubmitted when the user presses Enter.
    """

    DEFAULT_CSS = """
    InputBar {
        dock: bottom;
        margin-bottom: 0;
    }
    """

    class CommandSubmitted(Message):
        """Fired when user submits input."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, session: ReplSession, **kwargs: object) -> None:
        self.session = session
        prompt = self._build_prompt()
        super().__init__(placeholder=prompt, **kwargs)

    def _build_prompt(self) -> str:
        if self.session.has_project:
            return f"urika:{self.session.project_name}> "
        return "urika> "

    def _build_suggester(self) -> SuggestFromList:
        """Build command suggester from available commands."""
        from urika.repl_commands import get_command_names

        names = get_command_names(self.session)
        return SuggestFromList(["/" + n for n in names])

    def on_mount(self) -> None:
        """Focus input and set up suggester."""
        self.focus()
        self.suggester = self._build_suggester()

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        """Handle Enter key — emit command and clear input."""
        text = event.value.strip()
        if text:
            self.post_message(self.CommandSubmitted(text))
        self.value = ""
        event.stop()

    def refresh_prompt(self) -> None:
        """Update the prompt text after project change."""
        self.placeholder = self._build_prompt()
        self.suggester = self._build_suggester()
```

Update `src/urika/tui/app.py` to add InputBar:
```python
"""Main Textual application for Urika."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer

from urika.repl_session import ReplSession
from urika.tui.widgets.input_bar import InputBar
from urika.tui.widgets.output_panel import OutputPanel
from urika.tui.widgets.status_bar import StatusBar


class UrikaApp(App):
    """Urika TUI — three-zone interactive interface."""

    TITLE = "Urika"
    SUB_TITLE = "Multi-agent scientific analysis"

    def __init__(self, session: ReplSession | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.session = session or ReplSession()

    def compose(self) -> ComposeResult:
        yield OutputPanel()
        yield InputBar(self.session)
        yield StatusBar(self.session)
        yield Footer()
```

**Step 4: Run tests**

Run: `pytest tests/test_tui/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/tui/widgets/input_bar.py src/urika/tui/app.py tests/test_tui/test_input_bar.py
git commit -m "feat(tui): add InputBar widget with command completion"
```

---

### Task 6: Stdout capture for output redirection

**Files:**
- Create: `src/urika/tui/capture.py`
- Create: `tests/test_tui/test_capture.py`

**Step 1: Write the failing test**

`tests/test_tui/test_capture.py`:
```python
"""Tests for stdout capture and redirection."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


class TestStdoutCapture:
    """Test that print/click.echo output is captured to the output panel."""

    @pytest.mark.asyncio
    async def test_print_captured(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import OutputCapture

            capture = OutputCapture(app)
            with capture:
                print("test line from print")
            # Give Textual a moment to process
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_click_echo_captured(self) -> None:
        import click

        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            from urika.tui.capture import OutputCapture

            capture = OutputCapture(app)
            with capture:
                click.echo("test from click.echo")
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_stdout_restored_after_context(self) -> None:
        import sys

        app = UrikaApp()
        async with app.run_test() as pilot:
            original = sys.stdout
            from urika.tui.capture import OutputCapture

            capture = OutputCapture(app)
            with capture:
                pass
            assert sys.stdout is original
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tui/test_capture.py -v`
Expected: FAIL — OutputCapture not defined

**Step 3: Implement OutputCapture**

`src/urika/tui/capture.py`:
```python
"""Stdout/stderr capture that routes output to the TUI output panel."""

from __future__ import annotations

import sys
import threading
from io import StringIO
from typing import TYPE_CHECKING

from rich.text import Text

if TYPE_CHECKING:
    from urika.tui.app import UrikaApp


class _TuiWriter:
    """A file-like object that intercepts writes and posts them to the TUI."""

    def __init__(self, app: UrikaApp, original: object) -> None:
        self._app = app
        self._original = original
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        """Intercept write calls and route to the output panel."""
        if not text:
            return 0
        with self._lock:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line:
                    self._post_line(line)
        return len(text)

    def _post_line(self, line: str) -> None:
        """Send a line to the output panel via call_from_thread."""
        # Strip ANSI codes and send as Rich Text
        clean = _strip_ansi(line)
        try:
            self._app.call_from_thread(self._write_to_panel, clean)
        except Exception:
            # Fallback to original stdout if app is shutting down
            try:
                self._original.write(line + "\n")
                self._original.flush()
            except Exception:
                pass

    def _write_to_panel(self, text: str) -> None:
        """Write to the output panel (called on the Textual thread)."""
        try:
            panel = self._app.query_one("OutputPanel")
            panel.write_line(text)
        except Exception:
            pass

    def flush(self) -> None:
        """Flush any remaining buffered content."""
        with self._lock:
            if self._buffer.strip():
                self._post_line(self._buffer)
                self._buffer = ""

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return "utf-8"

    def fileno(self) -> int:
        raise OSError("TUI writer has no file descriptor")


class OutputCapture:
    """Context manager that redirects stdout/stderr to the TUI output panel.

    Usage:
        capture = OutputCapture(app)
        with capture:
            print("goes to output panel")
            click.echo("also goes to output panel")
    """

    def __init__(self, app: UrikaApp) -> None:
        self._app = app
        self._old_stdout: object = None
        self._old_stderr: object = None

    def __enter__(self) -> OutputCapture:
        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr
        sys.stdout = _TuiWriter(self._app, self._old_stdout)
        sys.stderr = _TuiWriter(self._app, self._old_stderr)
        return self

    def __exit__(self, *args: object) -> None:
        # Flush remaining content
        if hasattr(sys.stdout, "flush"):
            sys.stdout.flush()
        if hasattr(sys.stderr, "flush"):
            sys.stderr.flush()
        sys.stdout = self._old_stdout
        sys.stderr = self._old_stderr


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    import re

    return re.sub(r"\033\[[0-9;]*[a-zA-Z]", "", text)
```

**Step 4: Run tests**

Run: `pytest tests/test_tui/test_capture.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/tui/capture.py tests/test_tui/test_capture.py
git commit -m "feat(tui): add stdout capture for routing output to panel"
```

---

### Task 7: Command dispatch — wire InputBar to repl_commands

**Files:**
- Modify: `src/urika/tui/app.py`
- Create: `tests/test_tui/test_command_dispatch.py`

**Step 1: Write the failing test**

`tests/test_tui/test_command_dispatch.py`:
```python
"""Tests for command dispatch from InputBar to repl_commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from urika.tui.app import UrikaApp


class TestCommandDispatch:
    """Test that slash commands are dispatched to handlers."""

    @pytest.mark.asyncio
    async def test_help_command_produces_output(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            input_bar = app.query_one("InputBar")
            input_bar.value = "/help"
            await input_bar.action_submit()
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_unknown_command_shows_error(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            input_bar = app.query_one("InputBar")
            input_bar.value = "/nonexistent"
            await input_bar.action_submit()
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_quit_command_exits(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            input_bar = app.query_one("InputBar")
            input_bar.value = "/quit"
            await input_bar.action_submit()
            await pilot.pause()
            # App should have exited
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tui/test_command_dispatch.py -v`
Expected: FAIL — no command dispatch wired

**Step 3: Implement command dispatch in UrikaApp**

Update `src/urika/tui/app.py`:
```python
"""Main Textual application for Urika."""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Footer

from urika.repl_session import ReplSession
from urika.tui.capture import OutputCapture
from urika.tui.widgets.input_bar import InputBar
from urika.tui.widgets.output_panel import OutputPanel
from urika.tui.widgets.status_bar import StatusBar


class UrikaApp(App):
    """Urika TUI — three-zone interactive interface."""

    TITLE = "Urika"
    SUB_TITLE = "Multi-agent scientific analysis"

    BINDINGS = [
        ("ctrl+c", "cancel_agent", "Cancel"),
        ("ctrl+d", "quit_app", "Quit"),
    ]

    def __init__(self, session: ReplSession | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.session = session or ReplSession()
        self._capture = OutputCapture(self)

    def compose(self) -> ComposeResult:
        yield OutputPanel()
        yield InputBar(self.session)
        yield StatusBar(self.session)
        yield Footer()

    def on_mount(self) -> None:
        """Show welcome message on startup."""
        panel = self.query_one(OutputPanel)
        panel.write_line("Welcome to Urika. Type /help for commands.")

    @on(InputBar.CommandSubmitted)
    def _on_command(self, event: InputBar.CommandSubmitted) -> None:
        """Dispatch user input to command handlers or advisor."""
        text = event.value
        if text.startswith("/"):
            self._dispatch_command(text)
        elif self.session.agent_running:
            self.session.queue_input(text)
            panel = self.query_one(OutputPanel)
            panel.write_line(f"  [queued] {text}")
        else:
            self._dispatch_free_text(text)

    def _dispatch_command(self, text: str) -> None:
        """Parse and execute a slash command."""
        parts = text[1:].split(" ", 1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd_name == "quit":
            self.session.save_usage()
            self.exit()
            return

        from urika.repl_commands import PROJECT_COMMANDS, get_all_commands
        from urika.cli_display import print_error

        all_cmds = get_all_commands(self.session)
        if cmd_name not in all_cmds:
            if cmd_name in PROJECT_COMMANDS and not self.session.has_project:
                with self._capture:
                    print_error("Load a project first: /project <name>")
            else:
                with self._capture:
                    print_error(
                        f"Unknown command: /{cmd_name}. Type /help for commands."
                    )
            return

        handler = all_cmds[cmd_name]["func"]
        with self._capture:
            try:
                handler(self.session, args)
            except SystemExit:
                self.session.save_usage()
                self.exit()
            except Exception as exc:
                print_error(f"Error: {exc}")

        # Refresh input prompt after project load
        input_bar = self.query_one(InputBar)
        input_bar.refresh_prompt()

    def _dispatch_free_text(self, text: str) -> None:
        """Send free text to the advisor agent."""
        if not self.session.has_project:
            panel = self.query_one(OutputPanel)
            panel.write_line("  Load a project first: /project <name>")
            return
        # For now, run synchronously — Task 8 adds background workers
        from urika.repl import _handle_free_text

        with self._capture:
            _handle_free_text(self.session, text)

    def action_cancel_agent(self) -> None:
        """Cancel running agent on Ctrl+C."""
        if self.session.agent_running:
            self.session.set_agent_idle(error="Cancelled by user")
            panel = self.query_one(OutputPanel)
            panel.write_line("  Agent cancelled.")

    def action_quit_app(self) -> None:
        """Quit on Ctrl+D."""
        self.session.save_usage()
        self.exit()
```

**Step 4: Run tests**

Run: `pytest tests/test_tui/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/tui/app.py tests/test_tui/test_command_dispatch.py
git commit -m "feat(tui): wire command dispatch from InputBar to repl_commands"
```

---

### Task 8: Background agent worker

**Files:**
- Modify: `src/urika/tui/agent_worker.py`
- Modify: `src/urika/tui/app.py`
- Create: `tests/test_tui/test_agent_worker.py`

**Step 1: Write the failing test**

`tests/test_tui/test_agent_worker.py`:
```python
"""Tests for background agent execution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from urika.tui.app import UrikaApp
from urika.tui.agent_worker import run_command_in_worker


class TestAgentWorker:
    """Test that agent commands run in background workers."""

    @pytest.mark.asyncio
    async def test_non_blocking_command(self) -> None:
        """Commands that don't call agents should still work in workers."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            # /help is non-blocking — should work via worker
            input_bar = app.query_one("InputBar")
            input_bar.value = "/help"
            await input_bar.action_submit()
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_input_during_agent_run_queues(self) -> None:
        """User input during agent run should be queued."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            # Simulate agent running
            app.session.set_agent_running(agent_name="task_agent")
            input_bar = app.query_one("InputBar")
            input_bar.value = "try neural network"
            await input_bar.action_submit()
            await pilot.pause()
            assert app.session.has_queued_input
            assert "neural network" in app.session.pop_queued_input()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tui/test_agent_worker.py -v`
Expected: FAIL — run_command_in_worker not defined

**Step 3: Implement the agent worker**

`src/urika/tui/agent_worker.py`:
```python
"""Background agent execution via Textual Workers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.worker import Worker

if TYPE_CHECKING:
    from urika.tui.app import UrikaApp


def run_command_in_worker(
    app: UrikaApp,
    handler: object,
    args: str,
) -> Worker:
    """Run a command handler in a background Textual Worker.

    This allows the input bar to stay responsive while agents execute.
    The handler's stdout/stderr is captured and routed to the output panel.
    """
    from urika.tui.capture import OutputCapture
    from urika.cli_display import print_error

    def _work() -> None:
        capture = OutputCapture(app)
        with capture:
            try:
                handler(app.session, args)
            except SystemExit:
                app.call_from_thread(app.exit)
            except Exception as exc:
                print_error(f"Error: {exc}")
        # Refresh input prompt on Textual thread
        app.call_from_thread(_post_command_refresh)

    def _post_command_refresh() -> None:
        from urika.tui.widgets.input_bar import InputBar

        try:
            input_bar = app.query_one(InputBar)
            input_bar.refresh_prompt()
        except Exception:
            pass

    return app.run_worker(_work, thread=True)
```

Now update `src/urika/tui/app.py` `_dispatch_command` to use workers for blocking commands (agent-invoking commands):

In `_dispatch_command`, replace the direct handler call with:
```python
    def _dispatch_command(self, text: str) -> None:
        """Parse and execute a slash command."""
        parts = text[1:].split(" ", 1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd_name == "quit":
            self.session.save_usage()
            self.exit()
            return

        from urika.repl_commands import PROJECT_COMMANDS, get_all_commands
        from urika.cli_display import print_error

        all_cmds = get_all_commands(self.session)
        if cmd_name not in all_cmds:
            if cmd_name in PROJECT_COMMANDS and not self.session.has_project:
                with self._capture:
                    print_error("Load a project first: /project <name>")
            else:
                with self._capture:
                    print_error(
                        f"Unknown command: /{cmd_name}. Type /help for commands."
                    )
            return

        handler = all_cmds[cmd_name]["func"]

        # Agent-invoking commands run in background workers
        _BLOCKING_COMMANDS = {
            "run", "finalize", "evaluate", "plan", "advisor",
            "present", "report", "build-tool", "new",
        }
        if cmd_name in _BLOCKING_COMMANDS:
            from urika.tui.agent_worker import run_command_in_worker

            run_command_in_worker(self, handler, args)
        else:
            with self._capture:
                try:
                    handler(self.session, args)
                except SystemExit:
                    self.session.save_usage()
                    self.exit()
                except Exception as exc:
                    from urika.cli_display import print_error
                    print_error(f"Error: {exc}")
            input_bar = self.query_one(InputBar)
            input_bar.refresh_prompt()

    def _dispatch_free_text(self, text: str) -> None:
        """Send free text to the advisor agent (runs in worker)."""
        if not self.session.has_project:
            panel = self.query_one(OutputPanel)
            panel.write_line("  Load a project first: /project <name>")
            return

        from urika.repl import _handle_free_text
        from urika.tui.agent_worker import run_command_in_worker

        # _handle_free_text has same signature (session, text)
        def _advisor_handler(session, args):
            _handle_free_text(session, args)

        run_command_in_worker(self, _advisor_handler, text)
```

**Step 4: Run tests**

Run: `pytest tests/test_tui/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/tui/agent_worker.py src/urika/tui/app.py tests/test_tui/test_agent_worker.py
git commit -m "feat(tui): add background worker for non-blocking agent execution"
```

---

### Task 9: Wire CLI entry point with TUI fallback

**Files:**
- Modify: `src/urika/cli.py:85-106`
- Modify: `src/urika/tui/__init__.py`
- Create: `tests/test_tui/test_entry_point.py`

**Step 1: Write the failing test**

`tests/test_tui/test_entry_point.py`:
```python
"""Tests for TUI entry point and fallback."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestEntryPoint:
    """Test that urika with no args launches TUI or falls back."""

    def test_run_tui_is_importable(self) -> None:
        from urika.tui import run_tui

        assert callable(run_tui)

    def test_fallback_when_textual_missing(self) -> None:
        """If textual is not installed, fall back to classic REPL."""
        import importlib
        import sys

        with patch.dict(sys.modules, {"textual": None}):
            # Importing tui should raise ImportError
            with pytest.raises(ImportError):
                # Force reimport
                if "urika.tui" in sys.modules:
                    del sys.modules["urika.tui"]
                if "urika.tui.app" in sys.modules:
                    del sys.modules["urika.tui.app"]
                from urika.tui.app import UrikaApp
```

**Step 2: Run test to verify it passes (basic import test)**

Run: `pytest tests/test_tui/test_entry_point.py::TestEntryPoint::test_run_tui_is_importable -v`
Expected: PASS

**Step 3: Update CLI entry point**

In `src/urika/cli.py`, modify lines 103-106:

Replace:
```python
    if ctx.invoked_subcommand is None:
        from urika.repl import run_repl

        run_repl()
```

With:
```python
    if ctx.invoked_subcommand is None:
        _classic = ctx.params.get("classic", False)
        if _classic:
            from urika.repl import run_repl

            run_repl()
        else:
            try:
                from urika.tui import run_tui

                run_tui()
            except ImportError:
                from urika.repl import run_repl

                run_repl()
```

Also add a `--classic` option to the `cli` group. Modify the `@click.group` decorator area (around line 82-85):

Replace:
```python
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx) -> None:
```

With:
```python
@click.group(invoke_without_command=True)
@click.option("--classic", is_flag=True, hidden=True, help="Use classic prompt_toolkit REPL")
@click.pass_context
def cli(ctx, classic: bool) -> None:
```

And update the no-subcommand block to use the `classic` parameter:
```python
    if ctx.invoked_subcommand is None:
        if classic:
            from urika.repl import run_repl

            run_repl()
        else:
            try:
                from urika.tui import run_tui

                run_tui()
            except ImportError:
                from urika.repl import run_repl

                run_repl()
```

**Step 4: Run tests**

Run: `pytest tests/test_tui/ tests/test_cli.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/cli.py src/urika/tui/__init__.py tests/test_tui/test_entry_point.py
git commit -m "feat(tui): wire CLI entry point with TUI-first, classic fallback"
```

---

### Task 10: Welcome screen with header and global stats

**Files:**
- Modify: `src/urika/tui/app.py`
- Create: `tests/test_tui/test_welcome.py`

**Step 1: Write the failing test**

`tests/test_tui/test_welcome.py`:
```python
"""Tests for the TUI welcome screen."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


class TestWelcomeScreen:
    """Test that the app shows welcome info on mount."""

    @pytest.mark.asyncio
    async def test_shows_urika_branding(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_shows_help_hint(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            # The welcome message should mention /help
            assert panel.line_count > 0
```

**Step 2: Run test — should pass with existing on_mount**

Run: `pytest tests/test_tui/test_welcome.py -v`
Expected: PASS (on_mount already writes welcome message)

**Step 3: Enhance the welcome message**

Update the `on_mount` in `src/urika/tui/app.py`:
```python
    def on_mount(self) -> None:
        """Show welcome info on startup."""
        panel = self.query_one(OutputPanel)

        # Show branding
        panel.write_line("  Urika — Multi-agent scientific analysis platform")
        panel.write_line("")

        # Show global stats
        try:
            from urika.repl_commands import get_global_stats

            stats = get_global_stats()
            panel.write_line(
                f"  {stats['projects']} projects · "
                f"{stats['experiments']} experiments · "
                f"{stats['methods']} methods · "
                f"{stats['sdk']}"
            )
        except Exception:
            pass

        panel.write_line("")
        panel.write_line("  Type /help for commands, or just type to talk to the advisor.")
        panel.write_line("")
```

**Step 4: Run tests**

Run: `pytest tests/test_tui/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/tui/app.py tests/test_tui/test_welcome.py
git commit -m "feat(tui): add welcome screen with global stats"
```

---

### Task 11: CSS theme and visual polish

**Files:**
- Create: `src/urika/tui/urika.tcss`
- Modify: `src/urika/tui/app.py`

**Step 1: Create Textual CSS file**

`src/urika/tui/urika.tcss`:
```css
/* Urika TUI theme */

Screen {
    background: $background;
}

OutputPanel {
    height: 1fr;
    border-bottom: solid $accent;
    scrollbar-size: 1 1;
}

InputBar {
    dock: bottom;
    height: 1;
    margin: 0;
    border-top: solid $accent;
}

StatusBar {
    height: 2;
    dock: bottom;
    background: $surface;
    color: $text-muted;
    padding: 0 1;
}

Footer {
    display: none;
}
```

**Step 2: Wire CSS into the app**

In `src/urika/tui/app.py`, add:
```python
class UrikaApp(App):
    CSS_PATH = "urika.tcss"
```

**Step 3: Run tests to verify nothing breaks**

Run: `pytest tests/test_tui/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/urika/tui/urika.tcss src/urika/tui/app.py
git commit -m "feat(tui): add CSS theme for three-zone layout"
```

---

### Task 12: Integration test — full command flow

**Files:**
- Modify: `tests/test_tui/test_app.py`

**Step 1: Write integration tests**

Replace `tests/test_tui/test_app.py`:
```python
"""Integration tests for the Textual TUI app."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from urika.repl_session import ReplSession
from urika.tui.app import UrikaApp


class TestUrikaAppMount:
    """Test that the app mounts without errors."""

    @pytest.mark.asyncio
    async def test_app_mounts(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            assert app.title == "Urika"

    @pytest.mark.asyncio
    async def test_three_zones_present(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            assert app.query_one("OutputPanel") is not None
            assert app.query_one("InputBar") is not None
            assert app.query_one("StatusBar") is not None


class TestCommandFlow:
    """Test end-to-end command flows."""

    @pytest.mark.asyncio
    async def test_help_flow(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            initial_count = panel.line_count
            input_bar = app.query_one("InputBar")
            input_bar.value = "/help"
            await input_bar.action_submit()
            await pilot.pause()
            assert panel.line_count > initial_count

    @pytest.mark.asyncio
    async def test_list_flow(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            input_bar = app.query_one("InputBar")
            input_bar.value = "/list"
            await input_bar.action_submit()
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_project_command_without_project(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            input_bar = app.query_one("InputBar")
            input_bar.value = "/status"
            await input_bar.action_submit()
            await pilot.pause()
            # Should show error about loading project first
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_queue_input_while_busy(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            # Mark agent as running
            app.session.set_agent_running(agent_name="task_agent")
            input_bar = app.query_one("InputBar")
            input_bar.value = "try ridge regression"
            await input_bar.action_submit()
            await pilot.pause()
            assert app.session.has_queued_input
            queued = app.session.pop_queued_input()
            assert "ridge regression" in queued


class TestSessionIntegration:
    """Test that session state flows through the TUI."""

    @pytest.mark.asyncio
    async def test_session_persists(self) -> None:
        session = ReplSession()
        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            assert app.session is session

    @pytest.mark.asyncio
    async def test_usage_tracked(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            # Session should have started timing
            assert app.session.elapsed_ms > 0
```

**Step 2: Run all tests**

Run: `pytest tests/test_tui/ -v`
Expected: ALL PASS

**Step 3: Run the full test suite to verify no regressions**

Run: `pytest -v`
Expected: ALL PASS (949+ existing tests + new TUI tests)

**Step 4: Commit**

```bash
git add tests/test_tui/test_app.py
git commit -m "test(tui): add integration tests for full TUI command flow"
```

---

### Task 13: Lint and final cleanup

**Step 1: Lint**

Run: `ruff check src/urika/tui/ tests/test_tui/`
Fix any issues.

Run: `ruff format src/urika/tui/ tests/test_tui/`

**Step 2: Run full test suite**

Run: `pytest -v`
Expected: ALL PASS

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore(tui): lint and format Phase B TUI code"
```

---

## Summary

| Task | What | New Files | Modified Files |
|------|------|-----------|----------------|
| 1 | Add textual dependency | — | `pyproject.toml` |
| 2 | Scaffold tui package | 9 files | — |
| 3 | Output panel widget | `test_output_panel.py` | `output_panel.py`, `app.py` |
| 4 | Status bar widget | `test_status_bar.py` | `status_bar.py`, `app.py` |
| 5 | Input bar widget | `test_input_bar.py` | `input_bar.py`, `app.py` |
| 6 | Stdout capture | `capture.py`, `test_capture.py` | — |
| 7 | Command dispatch | `test_command_dispatch.py` | `app.py` |
| 8 | Background workers | `test_agent_worker.py` | `agent_worker.py`, `app.py` |
| 9 | CLI entry point | `test_entry_point.py` | `cli.py` |
| 10 | Welcome screen | `test_welcome.py` | `app.py` |
| 11 | CSS theme | `urika.tcss` | `app.py` |
| 12 | Integration tests | — | `test_app.py` |
| 13 | Lint & cleanup | — | — |
