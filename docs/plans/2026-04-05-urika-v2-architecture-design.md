# Urika v2 Architecture Design

**Date**: 2026-04-05
**Status**: Approved
**Scope**: TUI, adaptive orchestrator, multi-provider support, notification integration

## Overview

Urika v2 introduces a TypeScript frontend layer built on a pi-tui fork and pi-ai multi-provider SDK, replacing the deterministic Python orchestrator with an LLM-driven adaptive orchestrator that uses agents-as-tools. The existing Python codebase stays intact as a compute server and CLI.

### Design Principles

1. **Additive, not destructive** -- Python codebase stays functional throughout migration
2. **TypeScript handles LLM calls + user interaction**, Python handles computation + state + data
3. **Agent prompts unchanged** -- same .md templates, read by TS orchestrator
4. **Multi-provider from day one** -- any LLM provider via pi-ai
5. **CLI stays scriptable** -- all non-orchestrated commands remain pure Python

---

## 1. Architecture

```
+-----------------------------------------------------------+
|  TYPESCRIPT PROCESS                                        |
|                                                            |
|  pi-tui (fork)          Orchestrator                       |
|  +----------------+    +-------------------------------+   |
|  | Terminal UI     |<-->| Orchestrator LLM              |   |
|  | - Markdown      |    | (agents-as-tools via pi-ai)   |   |
|  | - Editor        |    |                               |   |
|  | - Status bar    |    | Provider: any (pi-ai)         |   |
|  +----------------+    | Claude/OpenAI/Gemini/Ollama   |   |
|                         +--------------+----------------+   |
|  Message Sources:                      |                    |
|  +----------+ +--------+              | agents = tools     |
|  | Terminal  | |Telegram|              |                    |
|  | (pi-tui) | |/Slack  |--------------+                    |
|  +----------+ +--------+                                   |
+----------------------------+-------------------------------+
                             | JSON-RPC over stdio
+----------------------------v-------------------------------+
|  PYTHON PROCESS (compute server)                            |
|                                                             |
|  State:           Execution:          Data:                 |
|  - experiments    - run Python code   - load datasets       |
|  - progress       - 18 built-in tools - data profiling      |
|  - sessions       - labbook/reports   - knowledge pipeline  |
|  - criteria       - presentations     - feature extraction  |
|  - methods        - finalize pipeline                       |
|  - usage tracking - README generation                       |
+-------------------------------------------------------------+
```

### What Moves to TypeScript

- **TUI** (replaces prompt_toolkit REPL)
- **Orchestrator** (replaces deterministic loop.py + meta.py)
- **Agent invocation** (replaces Claude SDK adapter -- now pi-ai, any provider)
- **Notification routing** (Telegram/Slack become message sources into orchestrator)

### What Stays Python

- **CLI** (Click) -- all scriptable commands
- **Core modules** -- experiment, progress, session, criteria, labbook, etc.
- **Agent prompts** -- .md templates, read by both Python and TS
- **Tools** -- 18 built-in + project tools
- **Data/Knowledge** -- loading, profiling, knowledge pipeline
- **Reports/Presentations** -- generation stays Python
- **Orchestrator loop** -- stays as `urika run --legacy` fallback
- **Agent runner + Claude SDK** -- stays for legacy mode

### What Gets Added

- `src/urika/rpc_server.py` -- JSON-RPC server (~200-300 lines)
- `tui/` -- TypeScript package (pi-tui fork + orchestrator + RPC client)

---

## 2. The TypeScript Orchestrator

An LLM agent (via pi-ai) with all Urika agent roles as callable tools.

### Orchestrator System Prompt

Loaded from a .md template (like all agent prompts):
- Describes Urika's research workflow
- Describes available tools (agents + state + execution)
- Describes the "standard protocol" (planning -> task -> evaluator -> advisor) as default
- Gives freedom to deviate (skip planning, parallel approaches, call tool_builder, go to finalize)
- Rules: always evaluate after task agent, never skip evaluator, respect user steering

### Agents-as-Tools

| Tool | What it does | Calls |
|------|-------------|-------|
| `planning_agent` | Design analytical approach | pi-ai LLM call |
| `task_agent` | Execute experiment | pi-ai LLM call + Python RPC (execute code) |
| `evaluator` | Score results | pi-ai LLM call |
| `advisor` | Analyze results, suggest next | pi-ai LLM call |
| `tool_builder` | Create project tools | pi-ai LLM call + Python RPC (save tool) |
| `literature_agent` | Search knowledge | pi-ai LLM call + Python RPC (knowledge search) |
| `data_agent` | Extract features (private mode) | pi-ai LLM call + Python RPC (data ops) |
| `report_agent` | Write narratives | pi-ai LLM call + Python RPC (save report) |

### Agent Prompt Loading

- Prompt templates live in `src/urika/agents/roles/prompts/*.md` (unchanged)
- TS orchestrator reads .md files from disk
- Substitutes variables (`{project_dir}`, `{experiment_id}`, `{criteria}`, etc.)
- Sends to pi-ai with the configured provider/model

### Per-Agent Provider Routing

Configured in `urika.toml`:

```toml
[runtime]
default_model = "anthropic/claude-sonnet-4-6"

[runtime.models]
orchestrator = "anthropic/claude-opus-4-6"
planning_agent = "anthropic/claude-sonnet-4-6"
task_agent = "anthropic/claude-sonnet-4-6"
evaluator = "anthropic/claude-haiku-4-5"
advisor = "anthropic/claude-opus-4-6"
data_agent = "ollama/qwen3:14b"
```

### Two Modes

- **Interactive** (`urika tui`): pi-tui renders streaming output, user types mid-run, orchestrator adapts
- **Headless** (`urika run`): streams events to stdout as JSON lines, no user input mid-run, still adaptive

---

## 3. Python JSON-RPC Server

Thin layer exposing existing core modules as RPC methods. No new logic.

### Protocol

JSON-RPC 2.0 over stdio (newline-delimited JSON). Same protocol as MCP and Pi's RPC mode.

### Lifecycle

```
urika tui (or urika run)
  -> spawns: python -m urika.rpc_server
  -> TS sends JSON-RPC requests on stdin
  -> Python responds on stdout
  -> stderr reserved for logging
```

### RPC Methods

**State operations:**
- `project.load_config`, `project.list`
- `experiment.create`, `experiment.list`, `experiment.load`
- `progress.append_run`, `progress.load`, `progress.get_best_run`
- `session.start`, `session.pause`, `session.resume`
- `criteria.load`, `criteria.append`
- `methods.register`, `methods.list`
- `usage.record`

**Execution:**
- `tools.run`, `tools.list`
- `code.execute` (subprocess in project venv)
- `finalize.run` (deterministic: finalizer -> report -> presentation -> README)

**Data & knowledge:**
- `data.load`, `data.profile`
- `knowledge.ingest`, `knowledge.search`, `knowledge.list`

**Reports:**
- `labbook.update_notes`, `labbook.generate_summary`
- `report.results_summary`, `report.key_findings`
- `presentation.generate`

### Streaming

Long operations use JSON-RPC notifications for progress:
```json
{"jsonrpc": "2.0", "method": "progress", "params": {"type": "stdout", "data": "..."}}
```

---

## 4. Pi-TUI Fork

Fork of `@mariozechner/pi-tui` (~10k lines, MIT license) customized for Urika.

### Kept As-Is

- `tui.ts` -- core TUI, differential rendering
- `terminal.ts` -- terminal abstraction
- `editor.ts` -- multi-line editor with undo, kill-ring, autocomplete
- `markdown.ts` -- CommonMark ANSI renderer
- `keys.ts` -- three-layer key parsing
- `utils.ts` -- ANSI text utilities
- All components (text, input, select-list, loader, image, box)

### Customized

- **Status bar**: project, experiment, turn, agent, provider/model, tokens, cost, elapsed
- **Agent output**: color-coded labels (same map as current cli_display.py)
- **Autocomplete**: Urika commands + project/experiment names
- **Branding**: Urika ASCII header, version

### Layout

Append-based, native terminal scrollback (same philosophy as Pi):

```
+-------------------------------------------+
|  Urika v1.0          sleep-study          |  <- header
|-------------------------------------------|
|  Orchestrator: Starting experiment...     |  <- streaming output
|                                           |     (native scrollback)
|  > Planning Agent                         |
|  Designing random forest approach...      |
|  > Task Agent                             |
|  R2=0.85, RMSE=0.07                      |
|  > Evaluator                              |
|  Criteria met: R2 > 0.80                  |
|-------------------------------------------|
|  exp-003 | turn 4 | sonnet | $0.23       |  <- status bar
|-------------------------------------------|
|  > try gradient boosting next_            |  <- editor (always active)
+-------------------------------------------+
```

### Slash Commands (local, not sent to orchestrator)

- `/status` -- project/experiment state (Python RPC call)
- `/results` -- results table (Python RPC call)
- `/pause` -- pause current run
- `/stop` -- stop current run
- `/login <provider>` -- OAuth browser login
- `/quit` -- exit TUI

Everything else is natural language sent to the orchestrator.

---

## 5. Multi-Provider Configuration

### Auth Methods (in priority order)

| Method | How | Providers |
|--------|-----|-----------|
| OAuth login | `/login anthropic` in TUI -> browser OAuth | Anthropic (Pro/Max), Google, GitHub Copilot |
| API key (config) | `urika config` -> `~/.urika/settings.toml` | All |
| API key (env var) | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc. | All |

OAuth tokens stored in `~/.urika/auth/`. Pi-ai's `AuthStorage` handles persistence and refresh.

### Custom/Local Providers

Pi-ai's `models.json` at `~/.urika/models.json`:

```json
{
  "providers": {
    "my-vllm": {
      "baseUrl": "http://localhost:8000/v1",
      "api": "openai-completions",
      "models": [{
        "id": "qwen2.5-72b",
        "contextWindow": 32768,
        "maxTokens": 8192
      }]
    }
  }
}
```

### Privacy Mode Mapping

- `open`: all roles use cloud provider
- `private`: all roles use local provider
- `hybrid`: roles in `local_roles` list use local, rest use cloud

Configured in `urika.toml` `[privacy]` section (existing).

---

## 6. Notification Integration

Remote messages become input to the orchestrator -- same as terminal input.

### Architecture

```
Terminal user  --> pi-tui editor --> orchestrator LLM
Telegram user  --> Telegram bot  --> orchestrator LLM  (same conversation)
Slack user     --> Slack bot     --> orchestrator LLM  (same conversation)
```

### Internal Message Format

```typescript
interface UserMessage {
  text: string;
  source: "terminal" | "telegram" | "slack";
  respondTo: (text: string) => void;
}
```

### What Gets Simpler

- No `RemoteSession` class with command queue
- No mapping commands to REPL handlers per channel
- No separate handler code per notification platform
- Orchestrator LLM understands natural language -- "pause" works like "/pause"

### Notification Output

Orchestrator emits events (experiment_started, turn_completed, criteria_met). A dispatcher subscribes and sends formatted messages to configured channels. Same events drive TUI display and remote notifications.

---

## 7. Project Structure

```
Urika/
  src/urika/                  # Python (existing, mostly unchanged)
    cli/                      # Click CLI stays
    core/                     # All core modules stay
    agents/roles/prompts/     # .md templates read by BOTH Python and TS
    orchestrator/             # Deterministic loops stay as fallback
    tools/                    # 18 built-in stay
    data/                     # Data loading stays
    knowledge/                # Knowledge pipeline stays
    rpc_server.py             # NEW: JSON-RPC server

  tui/                        # NEW: TypeScript package
    package.json
    src/
      index.ts                # Entry: TUI or headless mode
      orchestrator/
        orchestrator.ts       # Orchestrator LLM, agents-as-tools
        agent-tools.ts        # Agent role wrappers
        prompt-loader.ts      # Reads .md templates
        config-loader.ts      # Reads urika.toml
      rpc/
        client.ts             # JSON-RPC client
        types.ts              # RPC method types
      tui/
        app.ts                # Pi-tui customization
        agent-display.ts      # Agent labels, colors
        commands.ts           # Slash commands
        autocomplete.ts       # Urika completions
      notifications/
        telegram.ts           # Bot listener
        slack.ts              # Bot listener
        dispatcher.ts         # Event routing

  tests/                      # Python tests (existing 1100+)
  tui/tests/                  # TypeScript tests (new)
```

### Distribution

- Python: `pip install -e ".[dev]"` (unchanged)
- TUI binary: `bun build --compile` per platform
- Combined: `urika tui` downloads TUI binary on first run, then launches it
- Dev: `cd tui/ && bun run dev` for hot reload

---

## 8. Migration Path

Additive phases. Existing functionality never breaks.

### Phase 1: Python RPC Server

- Add `rpc_server.py` wrapping existing core modules
- All 1100+ tests still pass
- `urika run` works exactly as before

### Phase 2: TypeScript Scaffolding

- Create `tui/` with package.json
- Fork pi-tui components
- Build RPC client, prompt loader, config loader
- Nothing in Python changes

### Phase 3: Orchestrator

- Build agents-as-tools wrappers
- Build orchestrator system prompt
- Wire to pi-ai for multi-provider
- `urika tui` becomes functional
- `urika run` still works via Python

### Phase 4: Replace `urika run`

- `urika run` launches TS orchestrator headless
- Old loop stays as `urika run --legacy`

### Phase 5: Notifications

- Move Telegram/Slack to TypeScript
- Simpler code (message sources into orchestrator)
- Python notification modules deprecated

---

## 9. Third-Party Attribution

This project adapts code from:

```
pi-mono (https://github.com/badlogic/pi-mono)
Copyright (c) 2025 Mario Zechner -- MIT License

Components used:
- pi-tui: Terminal UI library (forked and customized)
- pi-ai: Multi-provider LLM abstraction (used as dependency)
- pi-agent-core: Agent loop primitives (used as dependency)
```

MIT license requires preserving copyright notice in copies or substantial portions. Full license text included in `THIRD-PARTY-LICENSES`.
