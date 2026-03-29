# Unified Terminal Interface Design

## Goal

Redesign Urika's terminal experience into two clean layers: a scriptable CLI and a unified interactive interface. No changes to the agentic pipeline — this is purely UI/UX.

## Architecture

Two layers, two phases:

- **CLI layer** (Click) — every command works non-interactively with flags. Interactive prompts use prompt_toolkit when flags are missing. `--json` on all commands. Auto-quiet when piped.
- **Unified interface** (`urika` with no args) — always-on input, streaming output, combined status bar. Replaces the current REPL.
- **Phase B (future)** — optionally upgrade the unified interface rendering from prompt_toolkit to Textual for Claude Code-level polish.

## Phase A: CLI Fixes + Unified Interface

### CLI Layer

**Principle:** Every command works non-interactively with all flags provided. When flags are missing, interactive prompts use prompt_toolkit (proper arrow keys, history, multi-line). Pipe-friendly when stdout is not a TTY.

#### Interactive prompts

Replace all `click.prompt()` calls with a new `_interactive_prompt()` helper that uses prompt_toolkit:
- Arrow key history (shared InMemoryHistory per session)
- Multi-line paste support (newlines don't leak into subsequent prompts)
- Ctrl+C handling (raises `click.Abort`)

Affected commands: `new`, `update`, `setup`, `build_tool`, `advisor`, and any command that falls back to interactive input.

#### `--json` flag

Every command that produces output gets `--json`. When present:
- Output is valid JSON to stdout
- No colors, no spinners, no status bars
- Exit code 0 = success, non-zero = failure
- Errors go to stderr as JSON: `{"error": "message"}`

A shared `_output_json(data)` helper. Each command builds its result dict, then either prints human-readable (default) or calls `_output_json`.

Commands and their JSON output:

| Command | JSON output |
|---------|------------|
| `urika new --json` | `{"project": "name", "path": "/..."}` |
| `urika list --json` | `{"projects": [...]}` |
| `urika status --json` | `{"project": "...", "experiments": N, "criteria_met": bool, ...}` |
| `urika results --json` | `{"ranking": [...]}` |
| `urika methods --json` | `{"methods": [...]}` |
| `urika tools --json` | `{"tools": [...]}` |
| `urika usage --json` | `{"tokens_in": N, "cost_usd": N, ...}` |
| `urika criteria --json` | `{"criteria": {...}}` |
| `urika inspect --json` | `{"rows": N, "columns": N, "dtypes": {...}, ...}` |
| `urika logs --json` | `{"runs": [...]}` |
| `urika run --json` | `{"status": "completed", "turns": N, "best_method": "...", ...}` |
| `urika finalize --json` | `{"success": bool, "outputs": {...}}` |
| `urika setup --json` | `{"packages": {...}, "hardware": {...}}` |
| `urika config --json` | `{"privacy": {...}, "runtime": {...}}` |
| `urika update --history --json` | `{"revisions": [...]}` |
| `urika knowledge list --json` | `{"entries": [...]}` |
| `urika knowledge search --json` | `{"results": [...]}` |
| `urika report --json` | `{"reports": [...], "paths": [...]}` |
| `urika present --json` | `{"path": "..."}` |
| `urika evaluate --json` | `{"criteria_met": bool, "assessment": {...}}` |

#### Auto-quiet when piped

When stdout is not a TTY:
- No spinners, no ThinkingPanel, no colors
- Agent output still captured, just not displayed
- Exit codes reflect success/failure
- `--json` implies quiet automatically

### Unified Interface

**What launches it:** `urika` with no args.

**Three-zone layout:**

```
┌─────────────────────────────────────────────────┐
│ Output stream (scrollable)                      │
│                                                 │
│   ─── Planning Agent ────────────────────────   │
│     ▸ Read /path/to/urika.toml                  │
│     ▸ Read /path/to/progress.json               │
│                                                 │
│   ─── Task Agent ────────────────────────────   │
│     ▸ Bash python methods/ridge_regression.py   │
│     ✓ Recorded run: ridge_regression (R²=0.82)  │
│                                                 │
├─────────────────────────────────────────────────┤
│ urika:my-study> try a bayesian approach next    │
├─────────────────────────────────────────────────┤
│ my-study · private · Turn 3/5 · Task Agent      │
│ qwen3-coder · 45K tokens · ~$0.23 · 2m 14s     │
└─────────────────────────────────────────────────┘
```

- **Top zone:** Output stream — scrolls naturally, all agent output appears here
- **Middle zone:** Input line — always available via prompt_toolkit session
- **Bottom zone:** Status bar (2 lines) — persistent, combines current REPL toolbar and ThinkingPanel info

**Key behaviors:**

1. **Input always available** — while agents run, user types into the input line. Text is queued.
2. **Queued input injection** — when the next agent is called, queued text is prepended to its prompt. Between experiments, goes to advisor.
3. **`/commands`** work same as current REPL — `/run`, `/status`, `/results`, `/new`, etc.
4. **Free text** goes to the advisor agent.
5. **`/new` flow** — project creation happens inline. Questions appear in the output stream, user answers in the input line. No mode switch.
6. **Ctrl+C during agent run** — stops the current agent gracefully, returns to input.
7. **Ctrl+D or `/quit`** — exits the interface.

**Status bar content:**
- Line 1: `project · privacy-mode · turn-info · active-agent · activity`
- Line 2: `model · token-count · cost · elapsed`

## Phase B: Textual TUI (future, optional)

Replace prompt_toolkit rendering with a Textual app:
- Proper widget-based layout (no scroll region hacks)
- Scrollable output panel with mouse support
- Dedicated input widget with multi-line editing
- Potential split panes (output + live leaderboard)
- Syntax highlighting in agent code output

Same features as Phase A — just a rendering engine upgrade. New dependency: `textual>=0.40`.

**When:** After Phase A is stable. Phase A might be sufficient.

## What Changes

| File | Change |
|------|--------|
| `cli.py` | Replace `click.prompt()` with prompt_toolkit helper. Add `--json` to all commands. Auto-quiet when piped. |
| `repl.py` | Major rewrite — becomes unified interface. Three-zone layout. Always-on input. Queued input during agent runs. |
| `repl_commands.py` | Minor — commands stay the same, `/new` becomes fully inline |
| `cli_display.py` | ThinkingPanel merges with unified interface status bar. Spinner stays for CLI-only use. |
| `repl_session.py` | Add input queue for messages typed during agent execution |

## What Does NOT Change

- All agent code (`agents/`)
- All orchestrator code (`orchestrator/`)
- All tools, evaluation, methods, knowledge
- All core modules (`core/`)

The agentic pipeline is completely untouched. Agents receive prompts and return results — they don't know or care what UI is driving them.

## Dependencies

- Phase A: No new dependencies (prompt_toolkit already installed)
- Phase B: `textual>=0.40` (only if/when pursued)
