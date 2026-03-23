# Multi-Backend Agent Runtime — Design Plan

> **Goal:** Allow users to choose their agent runtime — Claude, OpenAI, Google, Pi (for local models), or any combination — via a single config line in `urika.toml`.

## Current State

```
AgentRunner (ABC)
    └── ClaudeSDKRunner (only implementation)
```

Everything in Urika calls `AgentRunner.run()`. The orchestrator, CLI, and REPL are already backend-agnostic. The work is in adding adapters and the selection plumbing.

## Target Architecture

```
AgentRunner (ABC)
    ├── ClaudeSDKRunner      — Anthropic Claude Agent SDK (direct)
    ├── OpenAIAgentsRunner   — OpenAI Agents SDK (direct)
    ├── GoogleADKRunner      — Google Agent Development Kit (direct)
    ├── PiRunner             — Pi coding agent (Claude, OpenAI, Gemini, Ollama, local)
    └── OllamaRunner         — Ollama direct (lightweight, for simple local use)
```

### Provider Matrix

| Adapter | SDK Package | Models | Tool Use | Local Models | Notes |
|---------|-------------|--------|----------|-------------|-------|
| `ClaudeSDKRunner` | `claude-agent-sdk` | Claude Opus, Sonnet, Haiku (+ Bedrock/Vertex/Foundry) | SDK-managed | Via proxy | Current default. Full coding agent with file/bash access. Supports 3P providers (AWS Bedrock, GCP Vertex, Azure Foundry) via settings. May work with local models via LiteLLM proxy but tool use compatibility not guaranteed. |
| `OpenAIAgentsRunner` | `openai-agents-python` | GPT-4o, GPT-4.1, o3, o4-mini | SDK-managed | No | OpenAI's native agent framework. Tool use, handoffs, guardrails. |
| `GoogleADKRunner` | `google-adk` | Gemini 2.5 Pro/Flash | SDK-managed | No | Google's agent development kit. Multi-agent, tool use. |
| `PiRunner` | `pi-agent` (Node CLI) | All of the above + Ollama, llama.cpp, any OpenAI-compatible | Pi-managed | Yes | TypeScript coding agent. Called as subprocess. Best option for local models. |
| `OllamaRunner` | `ollama` (Python) | Llama 3, Mistral, CodeLlama, Qwen, etc. | Custom tool loop | Yes | Lightweight direct Ollama. No agent SDK — Urika manages the tool loop. |

### Why both Pi and direct adapters?

- **Direct adapters** (Claude, OpenAI, Google): Best performance, native features, no Node dependency. Users who have an API key for one provider get the simplest path.
- **Pi adapter**: Best for users who want local models (Ollama), or who want to switch providers without changing config. Pi handles the tool-use runtime for all providers. Requires Node.js.
- **Ollama direct**: For users who want local models without installing Node. Simpler but Urika must manage the tool-calling loop itself.

## Configuration

### urika.toml

```toml
[runtime]
backend = "claude"                    # "claude" | "openai" | "google" | "pi" | "ollama"
model = "claude-sonnet-4-5"           # model name (provider-specific)

# Per-agent model overrides (optional — use cheaper models for routine tasks)
[runtime.models]
planning_agent = "claude-sonnet-4-5"
task_agent = "claude-sonnet-4-5"      # needs strong coding ability
evaluator = "claude-haiku-4-5"        # simpler task, cheaper model
advisor_agent = "claude-sonnet-4-5"
tool_builder = "claude-sonnet-4-5"
literature_agent = "claude-haiku-4-5"
report_agent = "claude-haiku-4-5"
presentation_agent = "claude-haiku-4-5"

# Pi-specific settings (only used when backend = "pi")
[runtime.pi]
provider = "ollama"                   # "anthropic" | "openai" | "google" | "ollama"
ollama_model = "llama3:70b"
ollama_host = "http://localhost:11434"

# Ollama-specific settings (only used when backend = "ollama")
[runtime.ollama]
model = "llama3:70b"
host = "http://localhost:11434"
```

### Environment variable override

```bash
URIKA_BACKEND=openai urika run my-project    # one-off override
```

### pyproject.toml optional dependencies

```toml
[project.optional-dependencies]
claude = ["claude-agent-sdk>=0.1"]
openai = ["openai-agents-python>=0.1"]
google = ["google-adk>=0.1"]
ollama = ["ollama>=0.3"]
all-backends = ["claude-agent-sdk>=0.1", "openai-agents-python>=0.1", "google-adk>=0.1", "ollama>=0.3"]
```

Pi is not a Python package — installed via npm: `npm install -g @nickthecook/pi-agent`. Documented in Getting Started.

## Implementation Plan

### Phase 1: Backend selection plumbing

**Files:**
- Modify: `src/urika/agents/runner.py` — add `get_runner()` factory
- Modify: `src/urika/agents/config.py` — add `RuntimeConfig` dataclass
- Modify: `src/urika/core/models.py` — add runtime config to `ProjectConfig`
- Modify: `src/urika/cli.py` — use `get_runner()` instead of hardcoded `ClaudeSDKRunner()`
- Modify: `src/urika/repl_commands.py` — same
- Modify: `src/urika/repl.py` — same
- Modify: `src/urika/orchestrator/loop.py` — same

**Changes:**

1. Add `RuntimeConfig` dataclass:
```python
@dataclass
class RuntimeConfig:
    backend: str = "claude"       # claude | openai | google | pi | ollama
    model: str = ""               # default model
    model_overrides: dict = {}    # per-agent model overrides
    pi_provider: str = ""         # pi-specific
    ollama_host: str = "http://localhost:11434"
```

2. Add `get_runner()` factory:
```python
def get_runner(config: RuntimeConfig | None = None) -> AgentRunner:
    backend = config.backend if config else os.environ.get("URIKA_BACKEND", "claude")
    if backend == "claude":
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
        return ClaudeSDKRunner()
    elif backend == "openai":
        from urika.agents.adapters.openai_sdk import OpenAIAgentsRunner
        return OpenAIAgentsRunner(model=config.model)
    elif backend == "google":
        from urika.agents.adapters.google_adk import GoogleADKRunner
        return GoogleADKRunner(model=config.model)
    elif backend == "pi":
        from urika.agents.adapters.pi_agent import PiRunner
        return PiRunner(provider=config.pi_provider, model=config.model)
    elif backend == "ollama":
        from urika.agents.adapters.ollama_runner import OllamaRunner
        return OllamaRunner(model=config.model, host=config.ollama_host)
    else:
        raise ValueError(f"Unknown backend: {backend}")
```

3. Replace all `ClaudeSDKRunner()` calls with `get_runner()`.

### Phase 2: OpenAI Agents SDK adapter

**File:** `src/urika/agents/adapters/openai_sdk.py`

Key mapping:
- OpenAI uses `Agent` class with `tools` parameter
- Tool results come as `RunResult` with `messages`
- Map Urika's `AgentConfig` (writable_dirs, allowed_tools, prompts) to OpenAI Agent config
- Parse `RunResult` into Urika's `AgentResult`

### Phase 3: Google ADK adapter

**File:** `src/urika/agents/adapters/google_adk.py`

Key mapping:
- Google ADK uses `Agent` with `model`, `instruction`, `tools`
- Tool use via `FunctionDeclaration`
- Results via `Runner`

### Phase 4: Pi adapter

**File:** `src/urika/agents/adapters/pi_agent.py`

Pi is a Node.js CLI. The adapter calls it as a subprocess:
- Pass system prompt, user prompt, working directory
- Parse stdout for agent output
- Pi handles tool use (file read/write, bash, search) for ALL providers including Ollama

**Benefit:** One adapter gives access to Claude, OpenAI, Gemini, AND local models. Users get local model support without Urika needing a custom tool loop.

### Phase 5: Ollama direct adapter

**File:** `src/urika/agents/adapters/ollama_runner.py`

Most complex adapter — Ollama provides a raw LLM API with no agent framework. Urika must manage the tool-calling loop:
- Send messages with tool definitions
- Parse tool call responses
- Execute tools (Read, Write, Edit, Bash, Glob, Grep)
- Feed results back
- Repeat until no more tool calls

The `_execute_tool` method handles the same tools the Claude SDK provides. Approximately 200-300 lines.

**Trade-off vs Pi:** More work to build, but no Node.js dependency. Better for users who want a pure Python stack.

### Phase 6: Per-agent model routing

Allow different agents to use different models/backends for cost optimisation:

```toml
[runtime.models]
task_agent = "claude-sonnet-4-5"       # needs strong coding
evaluator = "claude-haiku-4-5"         # simpler, cheaper
advisor_agent = "claude-opus-4-5"      # needs deep reasoning
literature_agent = "gemini-2.5-flash"  # good at search/summarisation
```

The runner factory accepts an agent name and returns the appropriate runner.

## Implementation Order

| Phase | What | Effort | Depends On |
|-------|------|--------|------------|
| 1 | Backend selection plumbing (factory, config, replace hardcoded runners) | Small | Nothing |
| 2 | OpenAI Agents SDK adapter | Medium | Phase 1 |
| 3 | Google ADK adapter | Medium | Phase 1 |
| 4 | Pi adapter | Small | Phase 1, Node.js |
| 5 | Ollama direct adapter (custom tool loop) | Large | Phase 1 |
| 6 | Per-agent model routing | Small | Phase 1 |

**Recommended order:** 1 → 4 → 2 → 3 → 6 → 5

Phase 4 (Pi) gives the most backends for the least work — one adapter, access to Claude, OpenAI, Gemini, AND local models. Phase 5 (Ollama direct) is the most work but removes the Node.js dependency.

## CLI Changes

```bash
# Run with a specific backend (overrides urika.toml)
urika run my-project --backend openai
urika run my-project --backend ollama --model llama3:70b

# Check which backend is configured
urika status my-project    # shows: Backend: claude (claude-sonnet-4-5)
```

## Migration

No breaking changes. Default backend remains `claude`. Existing projects work without any config changes. New backends are opt-in via `[runtime]` section in `urika.toml`.

## Open Questions

1. **Tool compatibility:** Each SDK has different tool-use capabilities. Urika should define a minimal tool set (Read, Write, Edit, Bash, Glob, Grep) that all backends must support. Adapters that can't provide one should raise a clear error at startup rather than failing mid-experiment.

2. **Streaming:** Normalise to a common `on_message(msg)` callback. Each adapter translates their SDK's streaming format into Urika's message format. Backends that don't stream can call `on_message` once at the end with the full result.

3. **Session persistence:** Backend-dependent. Claude SDK supports session IDs for resume. Other SDKs may not — resume would replay from progress.json instead of from SDK state. Document which backends support native resume.

4. **Quality threshold:** Local models (Llama 3 70B) may not be good enough for complex agent tasks (writing Python, parsing JSON). Urika should warn during `urika run` if the configured model is below a recommended tier for a given agent role, but not block execution.

---

## Virtual Environment Management

### Problem

When agents `pip install` packages during experiments, they install into whatever Python environment is active. This causes conflicts when multiple projects need different package versions.

### Design: Hybrid with shared base

```
Global Urika venv (installed by user)
├── numpy, pandas, scipy, scikit-learn, click  ← shared base
├── claude-agent-sdk                            ← shared
└── urika                                      ← shared

Per-project venv (opt-in, inherits from global)
├── inherits all packages from global via --system-site-packages
└── mne==1.6  ← project-specific, no conflicts
```

**Default:** Global — agents install into the active environment. No isolation, no overhead.

**Opt-in:** Per-project — created during `urika new` or later via `urika.toml`. Inherits the global base so only the delta is installed (not 2GB of PyTorch per project).

### Configuration

```toml
# urika.toml
[environment]
venv = true                    # false = use global, true = per-project venv
venv_path = ".venv"            # relative to project dir (default)
```

### Implementation

#### AgentConfig gains `env` field

```python
@dataclass
class AgentConfig:
    ...
    env: dict[str, str] | None = None  # environment vars for agent subprocess
```

Each adapter maps `env` to their SDK's mechanism:
- **Claude SDK:** `ClaudeAgentOptions(env=config.env)` — native support
- **OpenAI SDK:** Pass to `subprocess.Popen(env=...)` for tool execution
- **Google ADK:** Similar subprocess env
- **Pi:** Pass as env vars to the pi subprocess
- **Ollama:** Our custom tool loop uses `subprocess.run(env=...)`

#### Venv activation in agent configs

When a project has `venv = true`, the agent role's `build_config()` sets:

```python
venv_bin = project_dir / ".venv" / "bin"
env = {
    "PATH": f"{venv_bin}:{os.environ.get('PATH', '')}",
    "VIRTUAL_ENV": str(project_dir / ".venv"),
}
```

This goes into `AgentConfig.env`, and the adapter passes it through to the SDK.

#### Project creation flow

In `urika new`, after the existing questions:

```
Create isolated environment for this project? [y/N]:
```

If yes:
1. Create venv: `python -m venv <project>/.venv --system-site-packages`
2. Set `environment.venv = true` in `urika.toml`
3. Agents now install packages into the project venv

#### CLI commands

```bash
# Create venv for existing project
urika venv create my-project

# Show venv status
urika venv status my-project

# Run a command in the project venv
urika venv run my-project pip list
```

### Phase integration

Venv support should be implemented as **Phase 1.5** — after the backend plumbing (Phase 1) adds `env` to AgentConfig, but before any new adapters. This way all adapters get venv support from the start.

| Phase | What |
|-------|------|
| 1 | Backend plumbing: `get_runner()`, `RuntimeConfig`, `env` in AgentConfig |
| 1.5 | Venv: creation, activation, `urika.toml` config, CLI commands |
| 2+ | Individual backend adapters (all inherit venv support via `env`) |
