# Agent Runtime Abstraction — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract the current TUI into a reusable `agent-runtime` package with pluggable backends (PiRuntime, ClaudeRuntime), then create a thin `urika-tui` package that configures it for Urika.

**Architecture:** Monorepo with two packages in `packages/`. The `agent-runtime` package provides the TUI shell, runtime interface, orchestrator, and RPC client. The `urika-tui` package provides Urika-specific config (agents, tools, commands, header) via `runtime.toml` + `createApp()`.

**Tech Stack:** TypeScript/Bun, pi-tui, pi-ai, pi-agent-core, Claude CLI (`claude --print --output-format stream-json`)

**Reference Design:** `docs/plans/2026-04-10-agent-runtime-abstraction-design.md`

---

## Phase 1: Package Scaffolding

### Task 1: Create monorepo structure

**Files:**
- Create: `packages/agent-runtime/package.json`
- Create: `packages/agent-runtime/tsconfig.json`
- Create: `packages/agent-runtime/src/index.ts`
- Create: `packages/urika-tui/package.json`
- Create: `packages/urika-tui/tsconfig.json`
- Create: `packages/urika-tui/src/index.ts`

**Step 1: Create agent-runtime package**

```json
// packages/agent-runtime/package.json
{
  "name": "@urika/agent-runtime",
  "version": "0.1.0",
  "type": "module",
  "main": "src/index.ts",
  "scripts": {
    "dev": "bun run src/index.ts",
    "build": "bun build --compile --target=bun src/index.ts --outfile dist/agent-runtime",
    "test": "bun test"
  },
  "dependencies": {
    "@mariozechner/pi-ai": "^0.65.0",
    "@mariozechner/pi-agent-core": "^0.65.0",
    "@mariozechner/pi-tui": "^0.65.0",
    "chalk": "^5.5.0",
    "marked": "^15.0.0"
  },
  "devDependencies": {
    "@types/bun": "latest",
    "typescript": "^5.7.0"
  }
}
```

```json
// packages/urika-tui/package.json
{
  "name": "@urika/urika-tui",
  "version": "0.1.0",
  "type": "module",
  "main": "src/index.ts",
  "scripts": {
    "dev": "bun run src/index.ts",
    "build": "bun build --compile --target=bun src/index.ts --outfile dist/urika-tui",
    "test": "bun test"
  },
  "dependencies": {
    "@urika/agent-runtime": "workspace:*",
    "chalk": "^5.5.0"
  },
  "devDependencies": {
    "@types/bun": "latest",
    "typescript": "^5.7.0"
  }
}
```

Stub `src/index.ts` for both — just export an empty object.

**Step 2: Install deps**

```bash
cd packages/agent-runtime && bun install
cd ../urika-tui && bun install
```

**Step 3: Commit**

```bash
git add packages/
git commit -m "feat: create monorepo package structure — agent-runtime + urika-tui"
```

---

### Task 2: Runtime interface types

**Files:**
- Create: `packages/agent-runtime/src/runtime/types.ts`
- Test: `packages/agent-runtime/tests/runtime-types.test.ts`

Define the core interfaces: `AgentRuntime`, `ManagedAgent`, `RuntimeEvent`, `UsageStats`, `AgentConfig`, `ToolDefinition`, `SystemConfig`.

These are the types from the design doc Section 2. Write structural tests verifying the type exports.

**Commit:** `feat(runtime): add core runtime interface types`

---

### Task 3: Config loader — read runtime.toml

**Files:**
- Create: `packages/agent-runtime/src/config/types.ts`
- Create: `packages/agent-runtime/src/config/loader.ts`
- Test: `packages/agent-runtime/tests/config-loader.test.ts`

The loader reads `runtime.toml` and returns a `SystemConfig` object containing:
- `system` section (name, rpc_command, prompts_dir)
- `runtime` section (default_backend, default_model, per-agent models)
- `privacy` section (mode, local_agents)
- `agents[]` declarations
- `tools[]` declarations with params → TypeBox schemas
- `commands[]` declarations
- `orchestrator` section

Use the TOML parser from the existing `tui/src/config/loader.ts` as a starting point, but extend it to handle the full `runtime.toml` format including arrays of tables (`[[agents]]`).

Tests: parse a sample runtime.toml, verify agents/tools/commands extracted correctly.

**Commit:** `feat(config): add runtime.toml config loader`

---

## Phase 2: Extract Generic Code from tui/

### Task 4: Move RPC client

**Files:**
- Move: `tui/src/rpc/client.ts` → `packages/agent-runtime/src/rpc/client.ts`
- Move: `tui/src/rpc/types.ts` → `packages/agent-runtime/src/rpc/types.ts`
- Move: `tui/tests/rpc-client.test.ts` → `packages/agent-runtime/tests/rpc-client.test.ts`

No code changes — just move and verify tests pass.

**Commit:** `refactor: move RPC client to agent-runtime package`

---

### Task 5: Move auth module

**Files:**
- Move: `tui/src/auth/storage.ts` → `packages/agent-runtime/src/auth/storage.ts`
- Move: `tui/src/auth/login.ts` → `packages/agent-runtime/src/auth/login.ts`
- Move: `tui/tests/auth.test.ts` → `packages/agent-runtime/tests/auth.test.ts`

No code changes — already generic.

**Commit:** `refactor: move auth module to agent-runtime package`

---

### Task 6: Move prompt loader

**Files:**
- Move: `tui/src/orchestrator/prompt-loader.ts` → `packages/agent-runtime/src/orchestrator/prompt-loader.ts`
- Move: `tui/tests/prompt-loader.test.ts` → `packages/agent-runtime/tests/prompt-loader.test.ts`

No code changes.

**Commit:** `refactor: move prompt loader to agent-runtime package`

---

### Task 7: Move TUI components (app shell, footer, agent display)

**Files:**
- Move: `tui/src/tui/agent-display.ts` → `packages/agent-runtime/src/tui/agent-display.ts`
- Create: `packages/agent-runtime/src/tui/footer.ts` (extract FooterComponent from app.ts)
- Create: `packages/agent-runtime/src/tui/app.ts` (generic version — remove Urika-specific logic)

The generic `app.ts` receives everything via `createApp()` options — no Urika imports. The `FooterComponent` becomes its own file.

**Commit:** `refactor: extract generic TUI shell to agent-runtime`

---

## Phase 3: Runtime Backends

### Task 8: PiRuntime — extract from current orchestrator

**Files:**
- Create: `packages/agent-runtime/src/runtime/pi-runtime.ts`
- Test: `packages/agent-runtime/tests/pi-runtime.test.ts`

Extract the pi-agent-core `Agent` usage from `tui/src/orchestrator/orchestrator.ts` into a class implementing `AgentRuntime`.

```typescript
export class PiRuntime implements AgentRuntime {
  readonly name = "pi";
  
  authenticate(): Promise<void> { /* check API key env vars */ }
  isAuthenticated(): boolean { /* check env vars or stored keys */ }
  createAgent(config: AgentConfig): ManagedAgent { /* create pi-agent-core Agent */ }
  listModels(): ModelInfo[] { /* from pi-ai getModels() */ }
}
```

The `ManagedAgent` wraps `Agent` from pi-agent-core:
- `prompt()` → `agent.prompt()`
- `subscribe()` → maps `AgentEvent` to `RuntimeEvent`
- `steer()` → `agent.steer()`
- `abort()` → `agent.abort()`

Tests: construction, tool names, model resolution.

**Commit:** `feat(runtime): add PiRuntime backend — wraps pi-agent-core Agent`

---

### Task 9: ClaudeRuntime — claude CLI delegation

**Files:**
- Create: `packages/agent-runtime/src/runtime/claude-runtime.ts`
- Test: `packages/agent-runtime/tests/claude-runtime.test.ts`

Implements `AgentRuntime` by spawning the `claude` CLI:

```typescript
export class ClaudeRuntime implements AgentRuntime {
  readonly name = "claude";
  
  authenticate(): Promise<void> {
    // Check if claude is logged in: claude auth status
    // If not: spawn claude login (opens browser)
  }
  
  createAgent(config: AgentConfig): ManagedAgent {
    // Returns a ClaudeManagedAgent that spawns:
    // claude --print --output-format stream-json --input-format stream-json
    //        --system-prompt-file <file> --model <model>
    //        --allowed-tools <tools> --bare
  }
}
```

The `ClaudeManagedAgent`:
- `prompt(message)` → writes `{"type":"user","content":message}` to CLI stdin
- `subscribe()` → reads CLI stdout JSONL, maps to `RuntimeEvent`
- `steer(message)` → writes to CLI stdin (stream-json input)
- `abort()` → sends SIGINT to CLI subprocess

Stream-json output events from Claude CLI:
```jsonl
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]}}
{"type":"result","subtype":"success","session_id":"...","cost_usd":0.01,...}
```

With `--include-partial-messages`, we get text deltas for streaming.

RPC tools: defined as custom tools via `--agents` JSON. When Claude calls one, the CLI emits a tool_use event — we intercept, call the RPC server, and write the result back via stdin.

Tests: check claude CLI is available, construct runtime, verify auth status detection.

**Commit:** `feat(runtime): add ClaudeRuntime backend — claude CLI delegation`

---

### Task 10: Runtime stubs (Codex, Google)

**Files:**
- Create: `packages/agent-runtime/src/runtime/codex-runtime.ts`
- Create: `packages/agent-runtime/src/runtime/google-runtime.ts`

Minimal stubs that throw "not yet implemented" on all methods.

**Commit:** `feat(runtime): add Codex and Google runtime stubs`

---

### Task 11: Runtime factory

**Files:**
- Create: `packages/agent-runtime/src/runtime/factory.ts`
- Test: `packages/agent-runtime/tests/runtime-factory.test.ts`

```typescript
export function createRuntime(backend: string, options?: RuntimeOptions): AgentRuntime {
  switch (backend) {
    case "claude": return new ClaudeRuntime(options);
    case "pi": return new PiRuntime(options);
    case "codex": return new CodexRuntime(options);
    case "google": return new GoogleRuntime(options);
    default: throw new Error(`Unknown runtime: ${backend}`);
  }
}
```

**Commit:** `feat(runtime): add runtime factory — createRuntime(backend)`

---

## Phase 4: Generic Orchestrator

### Task 12: Generic orchestrator

**Files:**
- Create: `packages/agent-runtime/src/orchestrator/orchestrator.ts`
- Test: `packages/agent-runtime/tests/orchestrator.test.ts`

The generic orchestrator:
1. Reads `SystemConfig` (from runtime.toml)
2. Creates a runtime (from factory)
3. Builds agent tools (from config agents + RPC tools)
4. Creates a `ManagedAgent` with the orchestrator prompt + all tools
5. Handles project switching, tool scoping (global vs project)
6. Exposes `processMessage()`, `subscribe()`, `steer()`, `abort()`

This replaces the Urika-specific `tui/src/orchestrator/orchestrator.ts` with a generic version driven by config.

**Commit:** `feat(orchestrator): add generic config-driven orchestrator`

---

## Phase 5: createApp() API

### Task 13: createApp entry point

**Files:**
- Create: `packages/agent-runtime/src/app.ts`
- Update: `packages/agent-runtime/src/index.ts` — export createApp and all types

```typescript
export interface AppOptions {
  configPath: string;
  renderHeader?: (projectName: string, version: string) => string[];
  commandHandlers?: Record<string, CommandHandler>;
  getPromptVariables?: (ctx: AppContext) => Promise<Record<string, string>>;
  onProjectSwitch?: (projectDir: string, ctx: AppContext) => Promise<ProjectInfo>;
}

export async function createApp(options: AppOptions): Promise<App> {
  // 1. Load runtime.toml
  // 2. Create runtime from config
  // 3. Create RPC client (spawn host system's rpc_command)
  // 4. Create orchestrator
  // 5. Create TUI (generic app shell)
  // 6. Merge declarative commands with custom handlers
  // 7. Return App with start()/stop()
}
```

**Commit:** `feat: add createApp() entry point — the public API`

---

## Phase 6: Urika-TUI Package

### Task 14: Urika runtime.toml

**Files:**
- Create: `packages/urika-tui/runtime.toml`

Full Urika config declaring all 10 agents, 17 RPC tools, slash commands, orchestrator config. Content from the design doc Section 5.

**Commit:** `feat(urika-tui): add runtime.toml with all agents, tools, commands`

---

### Task 15: Urika entry point + custom handlers

**Files:**
- Create: `packages/urika-tui/src/index.ts`
- Move: `tui/src/tui/header.ts` → `packages/urika-tui/src/header.ts`
- Create: `packages/urika-tui/src/commands.ts` (Urika-specific command handlers)
- Create: `packages/urika-tui/src/prompt-vars.ts` (Urika orchestrator prompt variables)

The entry point is a thin `createApp()` call:

```typescript
import { createApp } from "@urika/agent-runtime";
import { renderHeader } from "./header";
import { commandHandlers } from "./commands";
import { getPromptVariables, onProjectSwitch } from "./prompt-vars";

const app = await createApp({
  configPath: new URL("../runtime.toml", import.meta.url).pathname,
  renderHeader,
  commandHandlers,
  getPromptVariables,
  onProjectSwitch,
});

app.start();
```

**Commit:** `feat(urika-tui): add entry point with Urika-specific config`

---

## Phase 7: Wire and Clean Up

### Task 16: Update Python CLI

**Files:**
- Modify: `src/urika/cli/tui.py` — point to `packages/urika-tui/`
- Modify: `src/urika/cli/_base.py` — update TUI launch path

**Commit:** `fix(cli): point urika tui to packages/urika-tui`

---

### Task 17: Delete old tui/ directory

**Files:**
- Delete: `tui/` (entire directory)

Only after verifying both packages work and all tests pass.

**Commit:** `refactor: remove old tui/ — replaced by packages/agent-runtime + packages/urika-tui`

---

### Task 18: Verify full test suite

Run all tests:
```bash
cd packages/agent-runtime && bun test
cd ../urika-tui && bun test
cd ../../ && pytest -q
```

All must pass. Fix any issues.

**Commit:** `chore: fix any remaining test issues after refactor`

---

## Phase 8: ClaudeRuntime Integration Test

### Task 19: Test ClaudeRuntime end-to-end

Manually test:
1. `urika` → launches TUI
2. TUI detects ClaudeRuntime (claude CLI available)
3. Auth check passes (already logged into Claude Code)
4. `/project dht-target-selection-v2` → switches project
5. "where are we at with this project" → orchestrator calls tools, streams response
6. Verify: streaming text, footer updates, tool execution visible

This is manual testing — no automated test for full E2E with live API.

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| 1: Scaffolding | 1-3 | Package structure, types, config loader |
| 2: Extract | 4-7 | Move generic code to agent-runtime |
| 3: Runtimes | 8-11 | PiRuntime, ClaudeRuntime, stubs, factory |
| 4: Orchestrator | 12 | Generic config-driven orchestrator |
| 5: createApp | 13 | Public API entry point |
| 6: Urika-TUI | 14-15 | Urika-specific config + thin entry |
| 7: Wire | 16-18 | CLI updates, cleanup, verify |
| 8: Test | 19 | E2E with ClaudeRuntime |
