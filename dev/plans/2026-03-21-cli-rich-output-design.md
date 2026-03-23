# CLI Rich Output Design

**Date:** 2026-03-21
**Status:** Approved

## Problem

The CLI shows minimal feedback during agent operations. No colors, no visual separation between agents, no thinking/chain-of-thought visibility. The spinner shows one line but all internal agent activity is hidden. Users can't tell what's happening during long operations.

## Design

### Color System

Urika brand color: Blue (34). Colors off by default, enabled via `URIKA_COLOR=1` or `--color` flag.

```
Urika brand/headers:     Blue (34)
Planning agent:          Cyan (36)
Task agent:              Green (32)
Evaluator:               Yellow (33)
Suggestion agent:        Magenta (35)
Tool builder:            Cyan (36), dimmed
Literature agent:        Blue (34), dimmed

Questions to user:       Bold white
Thinking/working:        Dim
Errors:                  Red (31)
Success:                 Green (32)
Warnings:                Yellow (33)
Metrics/results:         Bold
```

### Verbose Mode

Verbose is the default. Quiet mode (`-q` / `--quiet`) suppresses detail.

**Verbose (default):** Shows tool use from agents (file reads, writes, bash commands, search patterns) inline as they happen. Each agent block has a colored header separator.

```
  ─── Task agent ──────────────────────────────
    Writing methods/conditional_logit.py
    Running: python conditional_logit.py
    Output: 7721 transitions, 12 features
    Fitting conditional logit (LOSO, 16 folds)...
  ✓ Recorded run: conditional_logit (acc=0.611)
```

**Quiet (`-q`):** Only major milestones.

```
  ▸ Turn 1/3
  ◆ Planning agent
  ◆ Task agent
  ✓ Recorded 3 run(s)
  ◆ Evaluator
  ◆ Suggestion agent
```

### Live Thinking Panel

A 3-4 line reserved area at the bottom of the terminal (scroll region) that shows chain-of-thought in real-time. Updates in place, does not persist in terminal scrollback.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  0:42 · Turn 1/3 · task_agent · dht-target-selection
  Reading progress.json... found 3 runs
  ⠹ Fitting conditional logit with LOSO (fold 12/16)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Content: elapsed time, current turn, current agent, project name. Below that, 1-2 lines of latest tool activity with spinner.

**Safe fallback:** If scroll region setup fails (`try/except` on ANSI write), degrade to inline output. Terminal always restored via `atexit` handler and Ctrl+C handler.

### SDK Adapter Changes

`ClaudeSDKRunner.run()` currently collects all messages and returns them at the end. For verbose output, it needs to emit events as they arrive — tool use blocks (Read, Write, Bash, Glob, Grep) printed inline during the async iteration.

Add an optional `on_message` callback to `run()`:
```python
async def run(self, config, prompt, *, on_message=None) -> AgentResult:
    async for msg in query(prompt=prompt, options=options):
        if on_message:
            on_message(msg)
        # existing collection logic
```

The CLI passes a callback that formats and prints tool use in real-time.

### What Changes

| File | Change |
|------|--------|
| `src/urika/cli_display.py` | Rewrite — color system, agent colors, thinking panel, verbose formatting |
| `src/urika/cli.py` | Add `--verbose`/`-q` flags, colored agent output, thinking panel activation |
| `src/urika/agents/adapters/claude_sdk.py` | Add `on_message` callback for streaming tool-use events |
| `src/urika/agents/runner.py` | Add `on_message` to AgentRunner ABC signature |
| `src/urika/orchestrator/loop.py` | Pass message callback through to runner |

### Not In Scope

- Interactive REPL / shell mode (separate design)
- Slash commands (separate design)
- Fuzzy project filtering (separate design)
- No new external dependencies — pure ANSI
