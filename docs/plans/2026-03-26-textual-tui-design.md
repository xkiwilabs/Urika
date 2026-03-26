# Phase B: Textual TUI Design

## Goal

Replace the prompt_toolkit REPL rendering with a Textual-based TUI that provides the three-zone layout (output panel, input bar, status bar) with always-on input during agent execution. The existing REPL stays as a fallback.

## Background

Phase A delivered a stable prompt_toolkit REPL with tab completion, toolbar, and all slash commands. An attempt at a three-zone layout using ANSI scroll regions failed — escape sequences leaked when agents used ThinkingPanel, and background threads caused prompt conflicts. The system was reverted to simple blocking mode.

Textual solves this with proper widget isolation. The TUI is a rendering engine swap, not a redesign.

## Architecture

New `src/urika/tui/` package alongside existing `repl.py`:

```
src/urika/tui/
├── __init__.py          # exports run_tui()
├── app.py               # UrikaApp(App) — main Textual application
├── widgets/
│   ├── __init__.py
│   ├── output_panel.py  # Scrollable RichLog for agent output
│   ├── input_bar.py     # Input widget with command completion
│   └── status_bar.py    # 2-line persistent status footer
└── agent_worker.py      # Textual Worker that runs agents in background
```

Shared code stays where it is:
- `repl_commands.py` — all command handlers, unchanged
- `repl_session.py` — session state, input queue, usage tracking, unchanged
- `cli_display.py` — colors, agent labels, spinner (used by CLI, not TUI)

## Three-Zone Layout

```
┌─────────────────────────────────────────────────┐
│ Output Panel (RichLog, scrollable, mouse-aware)  │
│                                                  │
│   ─── Planning Agent ────────────────────────    │
│     ▸ Read /path/to/urika.toml                   │
│     ▸ Read /path/to/progress.json                │
│                                                  │
│   ─── Task Agent ────────────────────────────    │
│     ▸ Bash python methods/ridge_regression.py    │
│     ✓ Recorded run: ridge_regression (R²=0.82)   │
│                                                  │
├──────────────────────────────────────────────────┤
│ urika:my-study> try a bayesian approach next     │
├──────────────────────────────────────────────────┤
│ my-study · private · Turn 3/5 · Task Agent       │
│ qwen3-coder · 45K tokens · ~$0.23 · 2m 14s      │
└──────────────────────────────────────────────────┘
```

### Output Panel

`RichLog` widget. All agent output (`click.echo`, `print`, tool use labels) captured via stdout redirection and written here as Rich renderables. Scrollable with mouse/keyboard. Auto-scrolls to bottom on new content; if user scrolls up, stays put.

### Input Bar

`Input` widget. Always focused and accepting keystrokes, even while agents run.

On Enter:
- Starts with `/` → dispatched to `repl_commands.py` handlers
- Agent running → queued via `session.queue_input()`
- Agent idle → sent to advisor agent

Tab completion on `/` commands via Textual `Suggester`.

### Status Bar

`Static` widget, 2 lines. Updated from `ReplSession` state via periodic timer (250ms).

- Line 1: `project · privacy-mode · turn-info · active-agent`
- Line 2: `model · token-count · cost · elapsed`

## Agent Execution

Background execution via Textual `Worker` threads. The input bar stays live during agent runs.

### Output Capture

Install a custom `TextIO` wrapper on stdout before running a command. Each intercepted `write()` call posts to the output panel via `app.call_from_thread()`. Restored after command completes. Zero changes to `repl_commands.py`.

### Activity Updates

The existing `ReplSession.set_agent_running()`, `update_agent_activity()`, and `set_agent_idle()` methods feed the status bar. Already implemented in Phase A.

### Queued Input Injection

Already wired: `_user_input_callback` in `repl_commands.py` calls `session.pop_queued_input()`. Orchestrator gets whatever was typed during the run.

## Entry Point & Fallback

```python
# In cli.py, no-args handler:
try:
    from urika.tui import run_tui
    run_tui()
except ImportError:
    from urika.repl import run_repl
    run_repl()
```

A `--classic` flag forces the old REPL.

### Dependency

`textual>=0.90` as optional dependency:

```toml
[project.optional-dependencies]
tui = ["textual>=0.90"]
```

Included in dev extras.

## Key Behaviors

- **Ctrl+C during agent run** → cancels worker, returns to idle
- **Ctrl+D or /quit** → saves usage, exits app
- **All existing /commands** work identically
- **Free text** goes to advisor (idle) or queue (agent running)
- **/new flow** — questions appear in output panel, answers via input bar

## Testing Strategy

### Unit tests (`tests/test_tui/`)

- `test_output_panel.py` — lines appear in RichLog, auto-scroll behavior
- `test_input_bar.py` — command dispatch, tab completion
- `test_status_bar.py` — reactive updates from ReplSession
- `test_stdout_capture.py` — stdout redirection captures click.echo/print
- `test_agent_worker.py` — worker lifecycle, cancel, usage tracking

### Integration tests

- `test_tui_app.py` — using Textual's `App.run_test()` / `Pilot` framework
- Mount app, type commands, verify output panel content
- Load project, check status bar
- Simulate Ctrl+C during mock agent run

### Not retested

Agent correctness and command handler logic — covered by existing 949+ tests.

## What Changes

| File | Change |
|------|--------|
| `src/urika/tui/` (new) | Entire TUI package |
| `cli.py` | No-args path tries TUI first, `--classic` flag |
| `pyproject.toml` | `textual>=0.90` in optional deps |

## What Does NOT Change

- `repl.py` — stays as classic fallback
- `repl_commands.py` — all handlers unchanged
- `repl_session.py` — session state unchanged
- All agent code, orchestrator, tools, evaluation, core modules
