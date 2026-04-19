# Agent Runtime Abstraction — Design Document

**Date**: 2026-04-10
**Status**: Approved
**Scope**: Reusable multi-SDK agent runtime with TUI, extractable for use in any agentic system

## Overview

A standalone TypeScript package (`agent-runtime`) that provides a unified interface for running multi-agent systems on any LLM backend. The host system (Urika, xPrism, etc.) declares its agents, tools, and commands in a config file + thin TS module. The abstraction handles the TUI, streaming, auth, and runtime execution.

### Design Principles

1. **Hybrid config**: Declarative `runtime.toml` for agents/tools/commands + TypeScript for logic (auth, project switching, custom commands)
2. **Runtime-agnostic**: Same host system code works with Claude CLI, OpenAI Codex, Google ADK, or Pi multi-provider
3. **Reusable**: Urika is the first consumer; the package works for any agentic system
4. **Monorepo now, separate repo later**: Lives in `packages/` for fast iteration, extract when stable
5. **Don't reinvent**: Use pi-tui, pi-ai, pi-agent-core as designed

---

## 1. Package Structure

```
Urika/
  packages/
    agent-runtime/                # Reusable abstraction
      package.json
      src/
        index.ts                  # Public API: createApp, types
        runtime/
          types.ts                # AgentRuntime, ManagedAgent, RuntimeEvent
          pi-runtime.ts           # Pi backend (pi-ai + pi-agent-core)
          claude-runtime.ts       # Claude CLI delegation
          codex-runtime.ts        # OpenAI Codex App Server (stub)
          google-runtime.ts       # Google ADK (stub)
        tui/
          app.ts                  # Generic TUI shell (pi-tui containers)
          footer.ts               # Dynamic footer component
          agent-display.ts        # Agent label formatting
        orchestrator/
          orchestrator.ts         # Generic orchestrator using chosen runtime
          prompt-loader.ts        # .md template loading
        rpc/
          client.ts               # JSON-RPC client for host system
          types.ts
        auth/
          storage.ts              # Credential persistence
          login.ts                # Auth flows per runtime
        config/
          loader.ts               # Reads runtime.toml
          types.ts                # RuntimeConfig, SystemConfig
      tests/

    urika-tui/                    # Urika-specific config
      package.json                # Depends on agent-runtime
      src/
        index.ts                  # createApp() with Urika config
        agents.ts                 # Urika's 10 agent definitions
        commands.ts               # Urika slash command handlers
        tools.ts                  # Urika RPC tool definitions
        header.ts                 # Urika ASCII logo
        orchestrator-prompt.ts    # Urika orchestrator prompt variables
      runtime.toml                # Urika's declarative config
      tests/

  src/urika/                      # Python (unchanged)
```

---

## 2. Runtime Interface

```typescript
interface AgentRuntime {
  readonly name: string;

  // Auth
  authenticate(): Promise<void>;
  isAuthenticated(): boolean;
  getAuthStatus(): { provider: string; method: "oauth" | "api-key" | "cli"; active: boolean };

  // Agent execution
  createAgent(config: AgentConfig): ManagedAgent;

  // Model info
  listModels(): ModelInfo[];
  getDefaultModel(): string;
}

interface ManagedAgent {
  prompt(message: string): Promise<void>;
  subscribe(listener: (event: RuntimeEvent) => void): () => void;
  steer(message: string): void;
  abort(): void;
  readonly isRunning: boolean;
}

type RuntimeEvent =
  | { type: "text_delta"; delta: string }
  | { type: "thinking_delta"; delta: string }
  | { type: "tool_start"; name: string; args: any }
  | { type: "tool_end"; name: string; result: any; isError: boolean }
  | { type: "agent_start" }
  | { type: "agent_end"; usage: UsageStats }
  | { type: "error"; message: string };

interface UsageStats {
  tokensIn: number;
  tokensOut: number;
  cost: number;
  model: string;
  elapsed: number;
}

interface AgentConfig {
  name: string;
  systemPrompt: string;
  tools: ToolDefinition[];
  model?: string;
  runtime?: string;
  privacy?: "local" | "cloud";
}
```

---

## 3. Runtime Backends

### PiRuntime (API keys, any provider)
- Auth: API keys via env vars or credential storage
- Execution: pi-agent-core `Agent` class
- Streaming: `agent.subscribe()` → mapped to `RuntimeEvent`
- Supports 20+ providers (Anthropic, OpenAI, Google, Ollama, vLLM, etc.)
- **Status**: Extracted from current TUI orchestrator

### ClaudeRuntime (subscription auth, CLI delegation)
- Auth: `claude login` (browser OAuth, stored by Claude Code)
- Execution: spawns `claude` CLI as subprocess with system prompt + tools
- Streaming: parses CLI stdout into `RuntimeEvent`
- Steering: writes to CLI stdin
- RPC tools: exposed as custom tools that CLI calls back for
- **Status**: New implementation, high priority

### CodexRuntime (OpenAI, future)
- Auth: OpenAI OAuth or API key
- Execution: Codex App Server (JSON-RPC over stdio)
- **Status**: Stub

### GoogleRuntime (Google, future)
- Auth: Google OAuth or API key
- Execution: Google ADK
- **Status**: Stub

---

## 4. Privacy Model

```toml
[privacy]
mode = "hybrid"          # open | hybrid | private
local_agents = ["data_agent"]
```

| Mode | Behavior |
|------|----------|
| open | All agents use the configured cloud runtime |
| hybrid | Agents in `local_agents` use a local runtime (Ollama/vLLM), rest use cloud |
| private | All agents use local runtime — no data leaves the machine |

In hybrid/private mode, the orchestrator creates a secondary local runtime (PiRuntime with local endpoint) for the specified agents. The `privacy` field on `AgentConfig` enforces this at the routing level.

---

## 5. Host System Config (runtime.toml)

```toml
[system]
name = "urika"
version = "0.1.2"
description = "Multi-agent scientific analysis platform"
rpc_command = "python -m urika.rpc"
prompts_dir = "src/urika/agents/roles/prompts"

[runtime]
default_backend = "claude"
default_model = "anthropic/claude-sonnet-4-6"

[runtime.models]
orchestrator = "anthropic/claude-opus-4-6"
evaluator = "anthropic/claude-haiku-4-5"
data_agent = "ollama/qwen3:14b"

[privacy]
mode = "open"
local_agents = ["data_agent"]

# ── Agents ──

[[agents]]
name = "planning_agent"
prompt = "planning_agent_system.md"
description = "Designs analytical method pipelines"
tools = ["Read", "Glob", "Grep"]

[[agents]]
name = "task_agent"
prompt = "task_agent_system.md"
description = "Executes experiments by writing and running Python code"
tools = ["Read", "Write", "Bash", "Glob", "Grep"]

[[agents]]
name = "data_agent"
prompt = "data_agent_system.md"
description = "Extracts features in privacy-preserving mode"
privacy = "local"

# ... more agents

# ── RPC Tools ──

[[tools]]
name = "list_experiments"
rpc_method = "experiment.list"
description = "List all experiments in the project"
scope = "project"

[[tools]]
name = "list_projects"
rpc_method = "project.list"
description = "List all registered projects"
scope = "global"

[[tools]]
name = "switch_project"
rpc_method = "project.list"
description = "Load a project by name"
scope = "global"
special = "switch_project"
[tools.params]
name = { type = "string", description = "Project name" }

# ... more tools

# ── Slash Commands ──

[[commands]]
name = "project"
description = "Open a project"
scope = "global"
autocomplete_rpc = "project.list"

[[commands]]
name = "status"
description = "Show project status"
scope = "project"

# ... more commands

# ── Orchestrator ──

[orchestrator]
prompt = "orchestrator_system.md"
model_override = "anthropic/claude-opus-4-6"
```

---

## 6. TypeScript Registration API

```typescript
// Host system entry point (e.g. packages/urika-tui/src/index.ts)
import { createApp } from "@urika/agent-runtime";

const app = createApp({
  configPath: "./runtime.toml",

  renderHeader: (projectName, version) => {
    return renderUrikaHeader(projectName, version);
  },

  commandHandlers: {
    "project": async (args, ctx) => {
      // Custom project switching logic
    },
  },

  getPromptVariables: async (ctx) => ({
    project_name: ctx.projectName,
    question: ctx.projectConfig?.question ?? "",
    data_dir: ctx.projectDir + "/data",
  }),

  onProjectSwitch: async (projectDir, ctx) => {
    const config = await ctx.rpc.call("project.load_config", { project_dir: projectDir });
    return { projectName: config.name, projectDir };
  },
});

app.start();
```

---

## 7. TUI Layer

### Generic (agent-runtime provides):
- Container hierarchy (Pi's pattern): header → chat → status → editor → footer
- Streaming Markdown rendering from RuntimeEvents
- CancellableLoader with Escape to abort
- Dynamic footer: model, tokens, cost, elapsed, current agent
- Editor with slash command autocomplete
- Agent label formatting with colors
- Event subscription → TUI updates

### Pluggable (host system provides):
- Header via `renderHeader()` callback
- Slash command handlers via `commandHandlers`
- Autocomplete sources via `autocomplete_rpc` in config
- Prompt variables via `getPromptVariables()`
- Project switching via `onProjectSwitch()`
- Agent colors via optional `agentColors` config

---

## 8. Migration Path

### Phase 1: Create package structure
- Create `packages/agent-runtime/` and `packages/urika-tui/`
- Set up package.json, tsconfig for both

### Phase 2: Extract generic code from tui/
- Move auth, rpc, tui shell, orchestrator base, prompt loader into agent-runtime
- Move Urika-specific code (agents, commands, header, prompts) into urika-tui

### Phase 3: Create runtime interface + PiRuntime
- Define AgentRuntime, ManagedAgent, RuntimeEvent interfaces
- Extract PiRuntime from current orchestrator (wraps pi-agent-core Agent)

### Phase 4: Create ClaudeRuntime
- Implement claude CLI subprocess spawning
- Parse stdout events into RuntimeEvent
- Handle auth via `claude login`

### Phase 5: Create runtime.toml config loader
- Parse TOML declarations into AgentConfig, ToolDefinition, CommandDefinition
- Build TypeBox tool schemas from config

### Phase 6: Wire createApp() API
- Entry point that reads config + TS hooks → creates TUI + orchestrator + runtime
- Urika's index.ts becomes a thin createApp() call

### Phase 7: Delete old tui/
- Update Python CLI to point to packages/urika-tui/
- Verify all tests pass

### Phase 8: Test with ClaudeRuntime
- `urika config` → select Claude backend
- Login via claude CLI auth
- Run experiments using subscription

### Future phases:
- CodexRuntime implementation
- GoogleRuntime implementation
- Extract agent-runtime to its own repo
- xPrism integration

---

## 9. Third-Party Attribution

```
pi-mono (https://github.com/badlogic/pi-mono)
Copyright (c) 2025 Mario Zechner — MIT License

Components used:
- pi-tui: Terminal UI library
- pi-ai: Multi-provider LLM abstraction
- pi-agent-core: Agent loop primitives
```
