# REPL Interactive Shell Design

**Date:** 2026-03-22
**Status:** Approved

## Problem

Users must remember CLI syntax and type full commands for every action. There's no persistent session, no conversational interaction with the advisor, and no way to run experiments autonomously across experiment boundaries. Novice users need a friendlier interface; power users need the existing CLI.

## Design

### Two Entry Points

```
$ urika new ...        ← CLI mode (existing, unchanged)
$ urika run ...        ← CLI mode (existing, unchanged)
$ urika                ← REPL mode (new)
```

Existing CLI commands remain unchanged. The REPL is an additional entry point.

### REPL Session Flow

**Startup (no project loaded):**
- Shows Urika header with logo
- Lists existing projects
- Prompt: `urika>`
- Available: `/new`, `/project`, `/projects`, `/help`, `/quit`

**After loading a project:**
- Shows project summary (experiments, methods, criteria)
- Prompt changes: `urika:project-name>`
- Full command set available
- Free text goes to advisor agent

**Free text → advisor conversation:**
- Any input without `/` calls the advisor agent immediately
- Advisor reads current project state (methods.json, criteria.json)
- Conversation context accumulates within the session
- Context feeds into next `/run` as instructions

**Running experiments:**
- `/run` shows defaults, offers custom settings
- Consistent pattern: defaults → 1. Run / 2. Custom / 3. Skip
- Same ThinkingPanel and streaming output as current CLI

**Project switching:**
- `/project other-name` does a hard switch
- Warns if experiment is active
- For parallel projects, use multiple terminals

### Slash Commands

**Global (no project):**

| Command | Description |
|---------|-------------|
| `/new` | Create new project |
| `/project <name>` | Load project (tab-complete) |
| `/projects` | List all projects |
| `/help` | Show commands |
| `/quit` | Exit |

**Project loaded:**

| Command | Description |
|---------|-------------|
| `/run` | Run next experiment |
| `/status` | Project status |
| `/experiments` | List experiments |
| `/methods` | Methods table |
| `/inspect` | Inspect dataset |
| `/report` | Generate reports |
| `/present <exp>` | Generate presentation |
| `/logs <exp>` | Experiment logs |
| `/criteria` | Show criteria |
| `/knowledge` | Knowledge base |
| `/project <name>` | Switch project |
| `/new` | Create new project |
| `/help` | Show commands |
| `/quit` | Exit |

Tab completion on: command names, project names, experiment IDs.

### Consistent Settings Pattern

All agent/orchestrator calls with configurable parameters show defaults and offer custom:

```
  Settings:
    Max turns: 5
    Auto mode: checkpoint
    Instructions: (none)

  1. Run with defaults (default)
  2. Custom settings
  3. Skip
```

Applies to: `/run`, meta-orchestrator, `/present`, `/new`, `/report`. Defaults from `urika.toml [preferences]`, overridable per-call.

### Meta-Orchestrator

`src/urika/orchestrator/meta.py` — manages experiment-to-experiment flow.

```python
async def run_project(project_dir, runner, *, mode="checkpoint",
                      max_experiments=10, max_turns=5, instructions=""):
```

**Three modes (configurable in urika.toml):**

- **checkpoint** (default): autonomous within experiments, pauses between them to show results. User confirms, adds instructions, or stops.
- **capped**: runs up to N experiments × M turns with no pauses.
- **unlimited**: runs until advisor says all approaches exhausted or criteria fully met. Hard safety cap of 50 experiments.

**Checkpoint interaction:**
```
  ━━━ Experiment 2 Complete ━━━━━━━━━━━━━━━━━━━━━━
  ✓ 4 runs · 12m 30s
  Best: fov_logistic (99.34%)

  1. Continue to next experiment (default)
  2. Continue with instructions
  3. Stop here
```

**Stop conditions (unlimited mode):**
- Criteria fully met (threshold + quality + completeness)
- Advisor explicitly says no further productive experiments
- Hard safety cap (50 experiments)

### Session Context

```python
class ReplSession:
    project_path: Path
    conversation: list[dict]  # {"role": "user"/"advisor", "text": "..."}
```

- Conversation history is session-only (resets on exit)
- Advisor reads persistent project state each call
- Last 5-10 exchanges included in advisor prompt
- Conversation context feeds into `/run` instructions

### Implementation

**New files:**

| File | Purpose |
|------|---------|
| `src/urika/repl.py` | REPL loop, prompt_toolkit session |
| `src/urika/repl_commands.py` | Slash command handlers, parameter prompting |
| `src/urika/repl_session.py` | Session state, advisor conversation |
| `src/urika/orchestrator/meta.py` | Meta-orchestrator |

**Modified files:**

| File | Change |
|------|--------|
| `src/urika/cli.py` | `urika` with no args → launches REPL |
| `pyproject.toml` | Add `prompt_toolkit>=3.0` |

**New dependency:** `prompt_toolkit>=3.0`

**Existing CLI unchanged.** The REPL calls the same core functions — no duplication.

### urika.toml Preferences

```toml
[preferences]
auto_mode = "checkpoint"
max_experiments = 10
max_turns_per_experiment = 5
presentation_theme = "light"
```
