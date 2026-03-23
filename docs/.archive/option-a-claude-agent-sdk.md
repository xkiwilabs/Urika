# Urika on Claude Agent SDK: PRD & Implementation Plan

## Option A — Build Urika on the Claude Agent SDK (Python)

---

## 1. Overview

### What This Option Is

Urika is built as a Python application on top of the Claude Agent SDK (`claude-code-sdk`). The SDK provides the agent runtime: the LLM loop, tool dispatch (read, write, edit, bash, grep, glob), session management, permission enforcement, and subagent spawning. Urika provides everything domain-specific: multi-agent orchestration, security boundaries, the Python analysis framework, investigation semantics, and knowledge pipeline.

The key insight: **Urika's agents ARE coding agents.** They write Python scripts that load datasets, fit models, compute metrics, generate plots, and write JSON result summaries. They run those scripts via bash. The Claude Agent SDK's built-in tools -- `Read`, `Write`, `Edit`, `Bash`, `Grep`, `Glob` -- are exactly what these agents need. The agent runtime does not need to "understand" scientific analysis. It needs to let agents write and run Python code effectively.

This means there is **no bridge layer** between the runtime and the analysis framework. Agents write Python files that `import urika` and execute them via `bash`. The `urika` Python package provides data loading, methods, evaluation, metrics, leaderboard, knowledge pipeline, built-in methods, and session tracking. Agents call it as a library, not through a protocol.

### The Key Advantage: Entirely Python

The entire Urika stack is Python:

- **Orchestration**: Python code using `query()` and `ClaudeSDKClient` to spawn subagents
- **Security**: Python `can_use_tool` handler returning `PermissionResultAllow` / `PermissionResultDeny`
- **Analysis framework**: Python `urika` package (data, methods, evaluation, metrics, leaderboard)
- **Agent-written scripts**: Python scripts that `import urika` and execute analysis
- **CLI**: Python `click`-based commands

No TypeScript. No split stack. No two package managers. One language, one dependency system, one debugging experience.

### The Key Disadvantage: Claude Only

The Claude Agent SDK calls Claude models only. There is no provider abstraction, no swappable LLM backend. If you need GPT-4, Gemini, or open-source models, this option does not support them without migrating away from the SDK.

This is vendor lock-in to Anthropic. The mitigation is that the `urika` Python package (the 80% of the work) has zero coupling to the SDK. If you later need multi-model support, you swap the orchestration layer. The analysis framework does not change.

### What the Claude Agent SDK Provides

| Capability | SDK Feature | Why Urika Needs It |
|---|---|---|
| **One-off agent tasks** | `query()` | Spawn a task agent, get a result, return. Ideal for evaluator runs, tool builder tasks, literature searches. |
| **Continuous conversation** | `ClaudeSDKClient` | Interactive investigation setup (system builder). Long-running analysis sessions where the agent needs back-and-forth. |
| **Subagent spawning** | `query()` with `system_prompt`, `allowed_tools`, `cwd`, `max_turns` | Orchestrator spawns each agent with distinct configuration. Each agent is isolated. |
| **Autonomous mode** | `bypassPermissions` | Agents run without human approval for tool calls. Propagates to subagents. Essential for autonomous investigation runs. |
| **Custom permission logic** | `can_use_tool` handler returning `PermissionResultAllow`/`PermissionResultDeny` | Enforce per-agent write boundaries. Evaluator cannot write to `methods/`. Task agents cannot modify evaluation criteria. Input rewriting for path sanitization. |
| **Tool restriction** | `allowed_tools` list | Strip tools from agents entirely. Evaluator gets no `Write` or `Edit`. |
| **Custom tools** | `@tool` decorator with type-safe schemas | Register Urika-specific MCP tools (e.g., `urika_profile_dataset`, `urika_update_leaderboard`) if needed beyond bash-based workflow. |
| **In-process tool servers** | `create_sdk_mcp_server()` | Serve custom tools without a separate process. Tools run in the same Python process as the orchestrator. |
| **Security hooks** | `PreToolUse` / `PostToolUse` hooks | Additional enforcement layer. Log all tool calls. Block unauthorized writes. Validate bash commands. |
| **Per-agent system prompts** | `system_prompt` parameter | Each agent role gets its own prompt: task agent, evaluator, suggestion agent, tool builder, literature agent. |
| **Turn limits** | `max_turns` parameter | Prevent runaway agents. Task agents get N turns per cycle. Evaluators get fewer. |
| **Working directory control** | `cwd` parameter | Each agent runs in the investigation workspace directory. |
| **Typed message stream** | Async iterator yielding `AssistantMessage`, `ResultMessage`, `ToolUseBlock` | Monitor agent progress, extract results, display streaming output in CLI. |
| **File checkpointing** | `rewind_files()` | Roll back filesystem changes if an agent fails mid-run. Restore to known-good state. |
| **Built-in retry logic** | SDK internals | API errors, rate limits, transient failures handled automatically. |
| **Built-in core tools** | `Read`, `Write`, `Edit`, `Bash`, `Grep`, `Glob` | Battle-tested implementations. No need to write `edit_file` from scratch. |

### What Urika Must Build (The Real Gaps)

The Claude Agent SDK is a general-purpose agent runtime. It does not know about experiments, evaluation metrics, method registries, or scientific integrity. Urika adds five things:

**1. Multi-agent orchestration (Python).** The SDK runs one agent at a time per `query()` call. Urika sequences orchestrator -> task agent -> evaluator -> suggestion agent -> tool builder in a loop. This is a deterministic Python control loop, not an LLM. It calls `query()` or `ClaudeSDKClient` to spawn each agent, collects results, decides next steps.

**2. Security boundaries (Python).** The `can_use_tool` handler enforces per-agent filesystem boundaries. The evaluator agent cannot write to `methods/`. Task agents cannot modify evaluation criteria. The tool builder cannot alter leaderboard results. This maps cleanly onto the SDK's `can_use_tool` + `allowed_tools` + `PreToolUse` hooks.

**3. Python analysis framework (`urika` package).** The big piece. A pip-installable Python package that agent-written scripts import. Contains: data loading, method base classes, method registry, evaluation runner, metrics library, criteria validation, leaderboard management, knowledge indexing, session tracking, built-in methods, built-in tools (as importable modules), visualization helpers.

**4. Knowledge pipeline.** PDF text and table extraction, literature search, knowledge indexing. Agents need to ingest papers and reference domain knowledge when choosing analytical approaches.

**5. CLI and investigation lifecycle.** `urika init`, `urika run`, `urika status`, `urika results`. Click-based CLI that launches the orchestrator, manages sessions, and displays results.

### Honest Pros and Cons

**Advantages:**

1. **All-Python stack.** One language for orchestration, security, analysis framework, agent scripts, CLI. No TypeScript. No `npm`. No split-stack debugging. Python developers (the target audience -- researchers) encounter only Python.

2. **SDK handles the hard parts.** Agent loop, tool dispatch, streaming, retries, context window management, permission enforcement, `edit_file` semantics -- all battle-tested by Anthropic. You do not write or maintain these.

3. **Clean permission model.** `can_use_tool` returns allow/deny per tool call with input rewriting. `allowed_tools` strips tools from agents entirely. No hook-ordering ambiguity. No "observe but cannot block" risk.

4. **Subagent isolation is built in.** Each `query()` call creates an isolated agent with its own system prompt, tools, permissions, working directory, and turn limit. No shared mutable state between agents.

5. **`bypassPermissions` mode for autonomous runs.** Propagates to subagents. Essential for `urika run` where agents must operate without human approval.

6. **File checkpointing.** `rewind_files()` can roll back a failed agent's filesystem changes. Useful for tool builder agents that create broken tools.

7. **Minimal boilerplate.** Spawning an agent is a function call, not a framework configuration. No YAML, no graph DSL, no role definitions in a markup language.

8. **Async iterator for monitoring.** Stream agent progress via typed messages. Display intermediate results in the CLI without polling.

**Disadvantages:**

1. **Claude-only.** No GPT-4, no Gemini, no open-source models. If Anthropic raises prices, changes API terms, or degrades quality, there is no fallback. Research institutions with non-Anthropic mandates cannot use Urika.

2. **Vendor lock-in.** The orchestration layer is coupled to Anthropic's SDK. Migration requires rewriting the orchestration (~20% of codebase) but not the analysis framework (~80%).

3. **SDK maturity.** The Claude Agent SDK is relatively new. APIs may change. Features may be added or deprecated. You depend on Anthropic's SDK roadmap.

4. **No model tiering within the stack.** You can specify different Claude models (Opus for strategy, Sonnet for routine work, Haiku for profiling) but cannot mix Claude with non-Claude models. Cannot use a cheap open-source model for data profiling.

5. **Subprocess model.** Each `query()` call spawns a Claude Code subprocess. Overhead per agent spawn is higher than an in-process LLM call. For fast inner-loop operations (evaluator checking 10 methods), the subprocess overhead may be noticeable.

6. **SDK is a black box for debugging.** When the agent loop misbehaves, you cannot breakpoint Anthropic's SDK internals. You can inspect inputs and outputs but not the loop itself. Compare with Option B (custom runtime) where every layer is your code.

---

## 2. Architecture

### 2.1 System Architecture

```
+-----------------------------------------------------------------------+
|                            User / CLI                                  |
|   $ urika init my-investigation                                        |
|   $ urika run --max-turns 50                                           |
|   $ urika status                                                       |
+----------------------------------+------------------------------------+
                                   |
+----------------------------------v------------------------------------+
|                     Urika Orchestrator                                  |
|               (deterministic Python loop)                              |
|                                                                        |
|   Uses query() / ClaudeSDKClient to spawn agents:                      |
|                                                                        |
|   +------------+  +------------+  +------------+  +---------------+    |
|   |   Task     |  | Evaluator  |  | Suggestion |  | Tool Builder  |    |
|   |   Agent    |  |   Agent    |  |   Agent    |  |    Agent      |    |
|   | (query()   |  | (query()   |  | (query()   |  | (query()      |    |
|   |  subagent) |  |  subagent) |  |  subagent) |  |  subagent)    |    |
|   +-----+------+  +-----+------+  +-----+------+  +------+--------+    |
|         |              |               |                |               |
|         |    Each agent writes and runs Python scripts  |               |
|         |    using SDK's bash/write/read/edit tools      |               |
|         |                                                |               |
+---------|------------------------------------------------|---------------+
          |                                                |
+---------v------------------------------------------------v---------------+
|                Investigation Workspace (Filesystem)                       |
|                                                                           |
|   urika.toml                  methods/          results/                  |
|   config/                     tools/            knowledge/                |
|   data/                                                                   |
|                                                                           |
|   Agent scripts import from the urika Python package:                     |
|   from urika.data import load_dataset                                     |
|   from urika.evaluation import run_evaluation, check_criteria             |
|   from urika.methods import list_methods, get_method                      |
|   from urika.metrics import compute_metrics                               |
|   from urika.leaderboard import update_leaderboard                        |
|   from urika.knowledge import search_knowledge, ingest_pdf                |
|                                                                           |
+---------------------------------------------------------------------------+
          |
+---------v----------------------------------------------------------------+
|                  urika Python Package (pip install urika)                 |
|                                                                           |
|   numpy, scipy, pandas, scikit-learn, statsmodels, pingouin,              |
|   matplotlib, seaborn, pymupdf                                            |
+---------------------------------------------------------------------------+
```

### 2.2 How Agents Work

Each Urika agent is a `query()` call with a specific system prompt, allowed tools, permission handler, working directory, and turn limit. The agent enters the SDK's standard loop: receive prompt, reason, call tools, repeat. The tools it calls are the SDK's built-in tools: `Write` to create Python scripts, `Bash` to run them, `Read` to inspect results.

**What a task agent actually does, concretely:**

1. Reads the investigation config (`urika.toml`) and current suggestions (`results/suggestions/*.json`)
2. Writes a Python script like:

```python
#!/usr/bin/env python3
"""Try ridge regression on the survey data."""
from urika.data import load_dataset
from urika.methods.builtin.regression import RidgeRegression
from urika.evaluation import run_evaluation
from urika.leaderboard import update_leaderboard

dataset = load_dataset("data/survey_responses.csv", target="satisfaction")
method = RidgeRegression(alpha=1.0)
result = run_evaluation(method, dataset, metrics=["r2", "rmse", "mae"])

update_leaderboard(
    investigation_root=".",
    method_name="ridge_regression",
    params={"alpha": 1.0},
    metrics=result.metrics,
    run_id=result.run_id,
    primary_metric="r2",
    direction="higher_is_better",
)

print(result.summary())
```

3. Runs the script via bash: `python3 scripts/run_ridge.py`
4. Reads the output and any generated files (plots, JSON results)
5. Updates `results/sessions/<id>/progress.json` with the run record
6. Decides what to try next based on results and available suggestions

The agent does not call a special `run_analysis` tool that bridges to Python. It writes and runs code, exactly as a human data scientist would. The `urika` package provides the library functions that make this efficient.

### 2.3 How the Orchestrator Spawns Agents

The orchestrator is a deterministic Python loop. It uses the Claude Agent SDK to spawn each agent as an isolated subprocess:

```python
# urika/agents/orchestrator.py

import asyncio
from claude_code_sdk import query, ClaudeSDKClient
from urika.agents.security import make_permission_handler
from urika.agents.prompts import load_prompt

async def run_investigation(config: InvestigationConfig):
    """The main orchestration loop. NOT an LLM — deterministic Python."""

    session = create_or_resume_session(config)

    while not session.is_complete():
        # --- TASK AGENT ---
        task_prompt = build_task_prompt(config, session)
        task_result = await query(
            prompt=task_prompt,
            system_prompt=load_prompt("task_agent"),
            allowed_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
            can_use_tool=make_permission_handler(
                role="task_agent",
                writable_dirs=[
                    config.root / "methods",
                    config.root / "results" / "sessions" / session.id,
                    config.root / "scripts",
                ],
            ),
            cwd=str(config.root),
            max_turns=config.task_agent_turns,
        )
        session.record_task_agent_result(task_result)

        # --- EVALUATOR ---
        eval_prompt = build_eval_prompt(config, session)
        eval_result = await query(
            prompt=eval_prompt,
            system_prompt=load_prompt("evaluator"),
            allowed_tools=["Read", "Bash", "Grep", "Glob"],  # NO Write, NO Edit
            can_use_tool=make_permission_handler(
                role="evaluator",
                writable_dirs=[],  # pure read-only agent
                bash_allowlist=["python"],  # can only run python scripts
            ),
            cwd=str(config.root),
            max_turns=config.evaluator_turns,
        )
        session.record_evaluator_result(eval_result)

        # --- CHECK CRITERIA ---
        if session.criteria_met():
            session.mark_complete("criteria_met")
            break

        # --- SUGGESTION AGENT ---
        suggest_prompt = build_suggestion_prompt(config, session)
        suggest_result = await query(
            prompt=suggest_prompt,
            system_prompt=load_prompt("suggestion_agent"),
            allowed_tools=["Read", "Write", "Bash", "Grep", "Glob"],
            can_use_tool=make_permission_handler(
                role="suggestion_agent",
                writable_dirs=[config.root / "results" / "suggestions"],
                bash_allowlist=["python"],
            ),
            cwd=str(config.root),
            max_turns=config.suggestion_agent_turns,
        )
        session.record_suggestion_result(suggest_result)

        # --- TOOL BUILDER (conditional) ---
        if session.has_tool_requests():
            tool_prompt = build_tool_builder_prompt(config, session)
            tool_result = await query(
                prompt=tool_prompt,
                system_prompt=load_prompt("tool_builder"),
                allowed_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
                can_use_tool=make_permission_handler(
                    role="tool_builder",
                    writable_dirs=[
                        config.root / "tools",
                        config.root / "methods",
                    ],
                ),
                cwd=str(config.root),
                max_turns=config.tool_builder_turns,
            )
            session.record_tool_builder_result(tool_result)

        session.increment_turn()

    generate_report(config, session)
```

**Key design decisions:**

- **Deterministic loop.** The orchestrator is not an LLM. It follows a fixed sequence: task -> evaluate -> check -> suggest -> (optional tool build) -> repeat. Decision logic is plain Python `if/else`, not prompted reasoning.
- **Each agent is a `query()` call.** Isolated subprocess. Own system prompt, tools, permissions, working directory, turn limit. No shared state between agent processes.
- **Permission handler per agent.** Each agent gets a `can_use_tool` handler configured for its role. The handler is a Python function -- no YAML, no config file, just code.
- **Turn budgets.** Each agent gets a configured number of turns per orchestration cycle. Task agents get more (10-20). Evaluators get fewer (3-5). This controls cost.
- **Session state on filesystem.** The orchestrator reads `progress.json`, `leaderboard.json`, and `suggestions/*.json` to understand current state. It does not maintain in-memory state across agent runs.

### 2.4 Security Model

The security model uses three layers, all in Python:

**Layer 1: `allowed_tools` -- tool stripping.**

The evaluator agent's `allowed_tools` list does not include `Write` or `Edit`. The tools simply do not exist from the evaluator's perspective. The LLM never sees them in its tool definitions, so it never tries to call them.

```python
# Evaluator: no write capability at all
eval_result = await query(
    prompt=eval_prompt,
    allowed_tools=["Read", "Bash", "Grep", "Glob"],  # Write and Edit omitted
    ...
)
```

**Layer 2: `can_use_tool` -- conditional permission logic.**

For agents that need write access but to restricted directories, the `can_use_tool` handler inspects every tool call and returns allow/deny:

```python
# urika/agents/security.py

from claude_code_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
)
from pathlib import Path

def make_permission_handler(
    role: str,
    writable_dirs: list[Path],
    bash_allowlist: list[str] | None = None,
    bash_blocklist: list[str] | None = None,
):
    """Create a can_use_tool handler for a specific agent role."""

    async def handler(tool_name: str, tool_input: dict) -> PermissionResultAllow | PermissionResultDeny:

        # --- Write/Edit boundary enforcement ---
        if tool_name in ("Write", "Edit"):
            target_path = Path(tool_input.get("file_path", ""))
            resolved = target_path.resolve()
            allowed = any(
                resolved == d.resolve() or str(resolved).startswith(str(d.resolve()) + "/")
                for d in writable_dirs
            )
            if not allowed:
                return PermissionResultDeny(
                    reason=f"{role} cannot write to {target_path}. "
                           f"Writable dirs: {[str(d) for d in writable_dirs]}"
                )
            return PermissionResultAllow()

        # --- Bash command enforcement ---
        if tool_name == "Bash":
            command = tool_input.get("command", "")

            # Block shell metacharacters that could bypass restrictions
            dangerous_patterns = ["&&", "||", ";", "|", ">", ">>", "`", "$(", "${"]
            if bash_allowlist is not None:
                for pattern in dangerous_patterns:
                    if pattern in command:
                        return PermissionResultDeny(
                            reason=f"{role}: shell metacharacters blocked in restricted mode"
                        )

            # Allowlist enforcement
            if bash_allowlist is not None:
                cmd_name = command.strip().split()[0] if command.strip() else ""
                if cmd_name not in bash_allowlist:
                    return PermissionResultDeny(
                        reason=f"{role} can only run: {bash_allowlist}. Got: {cmd_name}"
                    )

            # Blocklist enforcement
            if bash_blocklist is not None:
                for blocked in bash_blocklist:
                    if blocked in command:
                        return PermissionResultDeny(
                            reason=f"{role}: blocked command pattern: {blocked}"
                        )

            return PermissionResultAllow()

        # All other tools (Read, Grep, Glob) -- always allow
        return PermissionResultAllow()

    return handler
```

**Layer 3: `PreToolUse` hooks -- audit and additional enforcement.**

For defense-in-depth, `PreToolUse` hooks log every tool call and can enforce additional rules:

```python
# Optional: hook-based enforcement as a second layer
# The can_use_tool handler is the primary enforcement.
# Hooks provide audit logging and catch edge cases.
```

**Per-agent security boundaries:**

| Agent | `allowed_tools` | `can_use_tool` writable dirs | Bash restrictions |
|---|---|---|---|
| **Task Agent** | Read, Write, Edit, Bash, Grep, Glob | `methods/`, `results/sessions/<id>/`, `scripts/` | None (full bash) |
| **Evaluator** | Read, Bash, Grep, Glob | (none -- no Write/Edit) | `python` only, no metacharacters |
| **Suggestion Agent** | Read, Write, Bash, Grep, Glob | `results/suggestions/` only | `python` only, no metacharacters |
| **Tool Builder** | Read, Write, Edit, Bash, Grep, Glob | `tools/`, `methods/` | None (full bash, needs to test) |
| **Literature Agent** | Read, Write, Bash, Grep, Glob | `knowledge/` only | `python`, `curl` |

**Trust model -- the most important property:**

1. Evaluator has no `Write` or `Edit` tools. It literally cannot write to `methods/` or tamper with results. Tool stripping is the strongest guarantee.
2. Success criteria (`config/success_criteria.json`) are not writable by any agent during a run. The `can_use_tool` handler for every agent role denies writes to `config/`.
3. The evaluator runs evaluation independently. If a task agent claims `criteria_met: true`, the evaluator re-runs the metrics and corrects the flag.
4. All tool calls are logged. Every write, every bash command, every edit -- auditable.

### 2.5 How `query()` Maps to Urika's Needs

| Urika need | SDK mechanism |
|---|---|
| Spawn a task agent with specific instructions | `query(prompt=..., system_prompt=task_prompt)` |
| Restrict evaluator to read-only | `allowed_tools=["Read", "Bash", "Grep", "Glob"]` |
| Prevent task agent from writing to `evaluation/` | `can_use_tool=handler` that denies writes outside allowed dirs |
| Limit agent runtime | `max_turns=N` |
| Run agents without human approval | `bypassPermissions=True` (propagates to subagents) |
| Run agent in investigation workspace | `cwd=str(investigation_root)` |
| Monitor agent progress | Async iterate over `query()` results: `AssistantMessage`, `ToolUseBlock`, `ResultMessage` |
| Roll back failed agent's changes | `rewind_files()` to restore filesystem state |
| Interactive investigation setup | `ClaudeSDKClient` for multi-turn conversation |

### 2.6 Investigation Modes

All three modes use the same agent architecture and the same Python package. The differences are in orchestrator behavior, system prompts, and evaluator configuration:

**Exploratory mode** (default): Optimize one or more metrics. No pre-registration. The suggestion agent can recommend any direction. The leaderboard ranks all methods tried. Success = metric threshold reached or turn limit exhausted with best-effort results.

**Confirmatory mode**: Pre-specified hypothesis and analysis plan. Guardrails enforce:
- Analysis plan locked after registration (`config/analysis_plan.json`, writable by no agent)
- Task agents cannot change the primary metric or test
- Evaluator flags deviations from the registered plan
- Multiple comparisons corrections enforced
- Suggestion agent restricted to sensitivity analyses
- `confirmatory_audit.json` records every decision point
- No leaderboard (prevents cherry-picking)

**Pipeline mode**: Ordered preprocessing stages (e.g., filtering -> artifact rejection -> epoching -> feature extraction -> modelling). Each stage has defined inputs and outputs. Task agents work one stage at a time. The orchestrator advances stages only when the evaluator approves the current stage's outputs. Essential for EEG, motor control, and wearable sensor data.

---

## 3. What Urika Develops vs What the SDK Provides

### Work the Claude Agent SDK Gives You for Free

| Component | What It Does | Approximate effort if built from scratch |
|-----------|-------------|----------------------------------------|
| Agent loop (prompt -> LLM -> tools -> repeat) | The core cycle every agent runs | 500-800 lines |
| Core tools: Read, Write, Edit, Bash, Grep, Glob | File operations and command execution | 800-1,200 lines |
| Permission enforcement (`can_use_tool`, `allowed_tools`) | Per-agent security boundaries | 200-400 lines |
| Session management | Conversation history, resume, context | 300-500 lines |
| Context window management | Token counting, history compaction | 200-400 lines |
| Streaming response handling | Async iterator with typed messages | 200-300 lines |
| Retry logic / rate limit backoff | API error handling, transient failures | 100-200 lines |
| Subprocess isolation | Each agent in its own process | 200-300 lines |
| File checkpointing | `rewind_files()` for rollback | 100-200 lines |
| **Total** | | **~2,600-4,300 lines** |

You do not write, test, or maintain any of this. The SDK handles it.

### Work That Urika Must Build

| Component | Lines (est.) | Notes |
|-----------|-------------|-------|
| Multi-agent orchestrator | 400-600 | Deterministic Python loop calling `query()` |
| Permission handlers (`security.py`) | 200-300 | `can_use_tool` handlers per agent role |
| Agent prompt engineering | ~2,000 (prose) | System prompts for each agent role |
| Python analysis library (`urika` package) | 3,000-5,000 | Data loading, methods, evaluation, metrics, leaderboard, knowledge |
| Built-in analysis methods | 1,500-3,000 | Linear regression, random forest, t-tests, mixed models, etc. |
| Evaluation framework | 500-800 | Metric registry, criteria validation, leaderboard |
| Knowledge pipeline | 500-800 | PDF extraction, literature search, indexing |
| Session/experiment tracking | 400-600 | Runs, metrics, hypotheses, progress tracking |
| CLI (`urika init`, `urika run`, etc.) | 300-500 | Click subcommands |
| Investigation config system | 300-400 | TOML config, success criteria, agent config |
| Tests | 2,000-3,000 | Unit + integration tests |
| **Total** | **~11,100-17,000** | |

### The Ratio

The SDK gives you ~2,600-4,300 lines of infrastructure for free.
The Urika-specific platform is ~11,000-17,000 lines.

**The orchestration/security layer (what the SDK replaces) is ~5% of Urika's code.** The analysis platform is ~95%. The SDK does not just save you from writing a runtime -- it saves you from maintaining one.

Compare with Option B (custom runtime): you write the 2,600-4,300 lines yourself AND maintain them as APIs evolve. Compare with the Pi option: you get the same runtime benefits but in TypeScript, creating a split stack.

---

## 4. The Python Analysis Framework

This section describes the `urika` Python package that agents import when writing analysis scripts. **This is identical regardless of whether you use the Claude Agent SDK, Pi, or a custom runtime.** It is the actual product -- the thing that makes Urika useful for scientific analysis rather than being a generic coding agent pointed at data.

### 4.1 Package Overview

```
pip install urika
```

Agents write Python scripts like:

```python
#!/usr/bin/env python3
"""Explore the dataset and run initial statistical tests."""

from urika.data import load_dataset, profile
from urika.methods import LinearRegression, MixedANOVA
from urika.evaluation import evaluate, check_criteria
from urika.metrics import rmse, r_squared, cohens_d
from urika.leaderboard import update_leaderboard
from urika.sessions import current_session, log_run

# Load and profile
ds = load_dataset("data/experiment.csv")
summary = profile(ds)
print(summary)

# Run a method
model = LinearRegression()
result = model.fit(ds, target="accuracy", predictors=["age", "condition", "practice_hours"])
print(result.summary())
result.save_artifacts("results/sessions/session_001/runs/run_001/")

# Evaluate
metrics = evaluate(result, ds, metrics=[rmse, r_squared])
passed, failures = check_criteria(metrics, "config/success_criteria.json")

# Update tracking
log_run(
    session_id="session_001",
    run_id="run_001",
    method="linear_regression",
    params=model.get_params(),
    metrics=metrics,
    hypothesis="Baseline linear model to establish floor",
    observation=f"R2={metrics['r_squared']:.3f}, significant nonlinearity in residuals",
    next_step="Try tree-based methods for nonlinear relationships",
)
update_leaderboard(method="linear_regression", metrics=metrics, run_id="run_001")
```

The agent writes this script, runs it via `bash python3 analyze.py`, reads the output, and decides what to try next.

### 4.2 Data Loading and Profiling

```python
# urika/data/loader.py

def load_dataset(
    path: str | Path,
    format: str | None = None,    # auto-detected if None
    schema: dict | None = None,   # optional column type overrides
) -> Dataset:
    """Load a dataset from any supported format.

    Supports: CSV, TSV, Excel, Parquet, SPSS (.sav), Stata (.dta),
    JSON, JSON Lines. Optional readers for HDF5, EDF, C3D, etc.
    """
    ...

def profile(ds: Dataset) -> DataProfile:
    """Generate a comprehensive data profile.

    Returns: row/column counts, dtypes, missing values per column,
    descriptive stats (mean, sd, median, IQR), distribution shapes,
    correlation matrix, potential issues (high missingness, low variance,
    multicollinearity).
    """
    ...
```

**Dataset class:**

```python
@dataclass
class Dataset:
    df: pd.DataFrame              # the actual data
    path: Path                    # source file path
    metadata: dict                # format info, load options used
    schema: DataSchema            # column types, roles, measurement levels

@dataclass
class DataSchema:
    columns: dict[str, ColumnInfo]

@dataclass
class ColumnInfo:
    dtype: str                    # "numeric", "categorical", "ordinal", "datetime", "text"
    role: str | None              # "target", "predictor", "id", "group", "time", None
    measurement_level: str | None # "nominal", "ordinal", "interval", "ratio"
    missing_count: int
    unique_count: int
```

**Format readers** -- pluggable via protocol:

| Reader | Formats | Install |
|--------|---------|---------|
| `tabular.py` | CSV, TSV, Excel, Parquet, SPSS, Stata | Core |
| `json_reader.py` | JSON, JSON Lines | Core |
| `hdf5_reader.py` | HDF5, MAT v7.3 | `pip install urika[hdf5]` |
| `edf_reader.py` | EDF, EDF+, BDF | `pip install urika[eeg]` |
| `c3d_reader.py` | C3D | `pip install urika[motion]` |
| `imu_reader.py` | Axivity CWA, ActiGraph GT3X | `pip install urika[wearables]` |
| `audio_reader.py` | WAV, MP3 | `pip install urika[audio]` |

### 4.3 Methods

Methods are Python classes that follow a consistent interface. Agents can use built-in methods or write new ones.

```python
# urika/methods/base.py

class AnalysisMethod(ABC):
    """Base class for all analysis methods."""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def category(self) -> str: ...   # "regression", "classification", "hypothesis_test", etc.

    @abstractmethod
    def fit(self, ds: Dataset, **kwargs) -> MethodResult: ...

    def get_params(self) -> dict: ...
    def set_params(self, **kwargs): ...
    def default_params(self) -> dict: ...

@dataclass
class MethodResult:
    method_name: str
    outputs: dict[str, Any]       # predictions, coefficients, p-values, etc.
    metrics: dict[str, float]     # computed quality metrics
    diagnostics: dict             # residual plots paths, assumption checks, etc.
    artifacts: list[str]          # paths to generated files
    summary_text: str             # human-readable summary

    def summary(self) -> str:
        return self.summary_text

    def save_artifacts(self, directory: str | Path):
        """Save all artifacts to the given directory."""
        ...
```

**Built-in methods (ship with the package):**

| Category | Methods |
|----------|---------|
| Regression | `LinearRegression`, `RidgeRegression`, `LassoRegression`, `ElasticNet` |
| Classification | `LogisticRegression`, `RandomForest`, `GradientBoosting`, `SVM` |
| Hypothesis tests | `TTest`, `PairedTTest`, `WelchTTest`, `MannWhitneyU`, `ANOVA`, `MixedANOVA`, `ChiSquared`, `KruskalWallis` |
| Effect sizes | `CohensD`, `HedgesG`, `EtaSquared`, `OddsRatio` |
| Mixed models | `LinearMixedEffects`, `GeneralizedLinearMixed` |
| Dimensionality reduction | `PCA`, `FactorAnalysis` |
| Time series | `ARIMAModel`, `ExponentialSmoothing`, `SpectralAnalysis` |
| Clustering | `KMeansClustering`, `HierarchicalClustering`, `DBSCAN` |

Agents can also write entirely new methods as Python classes in the `methods/` directory. The method registry auto-discovers them:

```python
# urika/methods/registry.py

def discover_methods(search_dirs: list[Path]) -> dict[str, type[AnalysisMethod]]:
    """Auto-discover AnalysisMethod subclasses from Python files in search_dirs."""
    ...
```

### 4.4 Evaluation Framework

```python
# urika/evaluation/evaluate.py

def evaluate(
    result: MethodResult,
    ds: Dataset,
    metrics: list[Metric] | None = None,
) -> dict[str, float]:
    """Compute evaluation metrics for a method result."""
    ...

def check_criteria(
    metrics: dict[str, float],
    criteria_path: str | Path,
) -> tuple[bool, list[str]]:
    """Check metrics against success criteria.

    Returns (all_passed, list_of_failure_messages).
    """
    ...
```

**Metric registry:**

```python
# urika/evaluation/metrics.py

class Metric(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def compute(self, y_true, y_pred, **kwargs) -> float: ...

    @abstractmethod
    def direction(self) -> str: ...   # "higher_is_better" | "lower_is_better"
```

Built-in metrics: RMSE, MAE, R-squared, adjusted R-squared, accuracy, precision, recall, F1, AUC-ROC, AIC, BIC, Cohen's d, Hedge's g, eta-squared, ICC, Cronbach's alpha, CFI, RMSEA.

**Leaderboard:**

```python
# urika/evaluation/leaderboard.py

def update_leaderboard(
    method: str,
    metrics: dict[str, float],
    run_id: str,
    params: dict | None = None,
    leaderboard_path: str | Path = "results/leaderboard.json",
    primary_metric: str | None = None,
    direction: str | None = None,
):
    """Update the investigation leaderboard with a new result."""
    ...

def get_leaderboard(
    leaderboard_path: str | Path = "results/leaderboard.json",
) -> pd.DataFrame:
    """Load the leaderboard as a DataFrame, sorted by primary metric."""
    ...
```

**Success criteria format:**

```json
{
  "primary_metric": "rmse",
  "direction": "lower_is_better",
  "criteria": [
    {"metric": "rmse", "max": 0.05, "description": "Prediction error below 5%"},
    {"metric": "r_squared", "min": 0.85, "description": "At least 85% variance explained"},
    {"metric": "residual_normality_p", "min": 0.05, "type": "diagnostic", "description": "Residuals approximately normal"}
  ]
}
```

**Trust model:**

1. Evaluator has no `Write` or `Edit` tools (enforced via `allowed_tools`)
2. `config/success_criteria.json` is not writable by any agent (enforced via `can_use_tool`)
3. The evaluator runs evaluation independently after task agents claim results
4. If an agent claims `criteria_met: true` but the evaluator's independent check disagrees, the evaluator corrects the flag
5. All evaluation runs are logged with full provenance

### 4.5 Investigation Modes

Three modes to handle the range of scientific analysis:

**Exploratory mode** (default) -- Try approaches, rank them, iterate:
- Task agents explore freely
- Leaderboard tracks all attempts
- Suggestion agent proposes next directions
- Terminates when criteria are met or turn limit is reached

**Confirmatory mode** -- Pre-registered analysis with p-hacking guardrails:
- Analysis plan is locked before data is examined
- No leaderboard (no method shopping)
- Multiple comparison corrections enforced
- Full transparency log: every test run, every metric computed
- Cannot retroactively change success criteria
- Warnings if the agent attempts to run tests not in the pre-registered plan

**Pipeline mode** -- Ordered processing stages:
- For domains requiring preprocessing before analysis (EEG, motor control, wearables)
- Stages: ingest -> preprocess -> feature extraction -> analysis -> evaluation
- Each stage has its own success criteria
- Agents can iterate within a stage but cannot skip stages

### 4.6 Knowledge Pipeline

```python
# urika/knowledge/pdf_extractor.py
def extract_pdf(path: Path) -> ExtractedDocument:
    """Extract text, tables, and figures from a PDF using pymupdf."""
    ...

# urika/knowledge/literature.py
def search_literature(query: str, max_results: int = 10) -> list[PaperSummary]:
    """Search academic databases for relevant papers."""
    ...

def fetch_paper(url: str) -> ExtractedDocument:
    """Download and extract a paper from a URL."""
    ...

# urika/knowledge/index.py
class KnowledgeIndex:
    """Manages the knowledge base for an investigation."""

    def add_document(self, doc: ExtractedDocument): ...
    def search(self, query: str, top_k: int = 5) -> list[KnowledgeEntry]: ...
    def list_methods_mentioned(self) -> list[str]: ...
    def list_papers(self) -> list[PaperSummary]: ...
```

Knowledge storage:

```
knowledge/
    index.json                    # master index of all knowledge
    papers/
        paper_001.json            # extracted text, tables, key findings
        paper_002.json
    profiles/
        dataset_profile.json      # auto-generated data profile
    notes/
        user_notes.md             # researcher's own notes
```

### 4.7 Session and Experiment Tracking

```
results/
    sessions/
        session_001/
            session.json              # metadata: start time, status, config snapshot
            progress.json             # run-by-run tracking
            evaluation/
                metrics.json          # evaluator output
                criteria_check.json   # pass/fail per criterion
            runs/
                run_001/
                    run.json          # method, params, metrics, hypothesis, observation
                    artifacts/        # plots, tables, exports
                run_002/
                    ...
    leaderboard.json                  # global method rankings
    suggestions/
        suggestion_001.json           # structured suggestion from suggestion agent
```

**`progress.json` format:**

```json
{
    "session_id": "session_001",
    "status": "in_progress",
    "criteria_met": false,
    "best_run": {"run_id": "run_003", "method": "xgboost_v2", "metrics": {"rmse": 0.042}},
    "runs": [
        {
            "run_id": "run_001",
            "method": "linear_regression",
            "params": {"alpha": 0.1},
            "metrics": {"rmse": 0.15, "r_squared": 0.72},
            "hypothesis": "Baseline linear model to establish floor",
            "observation": "R2=0.72, significant nonlinearity in residuals",
            "next_step": "Try tree-based methods for nonlinear relationships"
        }
    ]
}
```

---

## 5. Project Structure

Everything is Python. No `src/ts/`, no `package.json`, no `node_modules/`.

```
urika/
    pyproject.toml                    # PEP 621, hatch build, dependency groups
    LICENSE                           # MIT
    CLAUDE.md

    src/urika/
        __init__.py
        __main__.py                   # python -m urika
        cli.py                        # click CLI: init, run, status, results, compare, report

        # =============================================
        # ORCHESTRATION & SECURITY (Claude Agent SDK layer)
        # This is the ~5% that is SDK-specific.
        # =============================================
        agents/
            __init__.py
            orchestrator.py           # Deterministic loop: task -> evaluate -> suggest -> repeat
                                      # Uses query() / ClaudeSDKClient to spawn agents
            security.py               # make_permission_handler() for each agent role
                                      # Returns can_use_tool handlers (PermissionResultAllow/Deny)
            prompts.py                # load_prompt() — reads system prompt files
            agent_registry.py         # Auto-discover agent roles from agents/roles/

            roles/                    # Agent role definitions
                __init__.py
                task_agent.py         # get_config() -> AgentRoleConfig (tools, permissions, model)
                evaluator.py
                suggestion_agent.py
                tool_builder.py
                literature_agent.py
                system_builder.py

            prompts/                  # System prompts for each role
                task_agent.md
                evaluator.md
                suggestion_agent.md
                tool_builder.md
                literature_agent.md
                system_builder.md

        # =============================================
        # URIKA PLATFORM (identical in all options)
        # This is the ~95% that is the actual product.
        # =============================================

        # --- Core configuration and protocols ---
        core/
            __init__.py
            config.py                 # InvestigationConfig, ProjectConfig, TOML loading
            investigation.py          # Investigation lifecycle (init, run, resume)
            protocols.py              # Shared interfaces/protocols
            exceptions.py
            pipeline.py               # PipelineStage, Pipeline for ordered processing

        # --- Data loading and profiling ---
        data/
            __init__.py
            dataset.py                # Dataset, DataSchema, ColumnInfo dataclasses
            loader.py                 # load_dataset() with format auto-detection
            profile.py                # profile() — comprehensive EDA
            schema.py                 # Schema inference and column role detection
            readers/
                __init__.py
                base.py               # IDataReader protocol
                tabular.py            # CSV, Excel, Parquet, SPSS, Stata
                json_reader.py        # JSON, JSON Lines
                # Optional readers (installed via extras):
                # hdf5_reader.py
                # edf_reader.py
                # c3d_reader.py
                # imu_reader.py
                # audio_reader.py

        # --- Analysis methods ---
        methods/
            __init__.py
            base.py                   # AnalysisMethod ABC, MethodResult dataclass
            registry.py               # discover_methods() auto-discovery
            statistical/
                __init__.py
                linear_regression.py
                logistic_regression.py
                ridge_lasso.py
                t_tests.py            # TTest, PairedTTest, WelchTTest
                anova.py              # ANOVA, MixedANOVA
                nonparametric.py      # MannWhitneyU, KruskalWallis, ChiSquared
                mixed_models.py       # LinearMixedEffects
                effect_sizes.py       # CohensD, HedgesG, EtaSquared
            ml/
                __init__.py
                random_forest.py
                gradient_boosting.py
                svm.py
                clustering.py         # KMeans, Hierarchical, DBSCAN
                dimensionality.py     # PCA, FactorAnalysis
            timeseries/
                __init__.py
                arima.py
                spectral.py
                smoothing.py

        # --- Evaluation framework ---
        evaluation/
            __init__.py
            evaluate.py               # evaluate() — run metrics on a MethodResult
            criteria.py               # check_criteria() — validate against success criteria
            leaderboard.py            # update_leaderboard(), get_leaderboard()
            metrics/
                __init__.py
                base.py               # Metric ABC
                registry.py           # MetricRegistry with auto-discovery
                regression.py         # RMSE, MAE, R2, adjusted R2
                classification.py     # Accuracy, Precision, Recall, F1, AUC
                information.py        # AIC, BIC
                effect_size.py        # Cohen's d, Hedge's g, eta-squared
                reliability.py        # ICC, Cronbach's alpha
                fit_indices.py        # CFI, RMSEA (for SEM/CFA)

        # --- Knowledge pipeline ---
        knowledge/
            __init__.py
            pdf_extractor.py          # PDF text + table extraction (pymupdf)
            literature.py             # Web search, paper fetching
            index.py                  # KnowledgeIndex management

        # --- Session and experiment tracking ---
        sessions/
            __init__.py
            tracking.py              # log_run(), current_session()
            comparison.py            # Cross-session comparison
            persistence.py           # SQLite metadata store for fast queries

        # --- Investigation modes and guardrails ---
        guardrails/
            __init__.py
            confirmatory.py          # Plan locking, multiple comparisons, HARKing detection
            validators.py            # Assumption checks, sample size warnings

    # Per-investigation workspace (created by `urika init`):
    # my-investigation/
    #     urika.toml                 # Investigation config
    #     data/                      # Dataset files
    #     knowledge/                 # Ingested papers, profiles, notes
    #     methods/                   # Agent-written methods (writable by task agents)
    #     tools/                     # Agent-built tools (writable by tool builder)
    #     scripts/                   # Agent-written analysis scripts (auditable)
    #     results/
    #         sessions/
    #         suggestions/
    #         leaderboard.json
    #     config/
    #         success_criteria.json
    #         agents.json
    #         analysis_plan.json     # (confirmatory mode only)

    tests/
        conftest.py
        test_agents/
            test_orchestrator.py
            test_security.py
            test_permission_handlers.py
        test_data/
            test_loader.py
            test_profile.py
            test_readers.py
        test_methods/
            test_statistical.py
            test_ml.py
            test_registry.py
        test_evaluation/
            test_evaluate.py
            test_criteria.py
            test_leaderboard.py
            test_metrics.py
        test_knowledge/
            test_pdf_extractor.py
            test_literature.py
        test_sessions/
            test_tracking.py
            test_comparison.py
        test_guardrails/
            test_confirmatory.py
            test_validators.py
        test_integration/
            test_end_to_end.py       # Full: init -> run -> evaluate -> results
```

**What is NOT here (compared to Option B custom runtime):**

There is no `runtime/` directory. No `loop.py`, no `llm/`, no `providers/`, no `tools/core/read_file.py`, no `session/session.py`, no `compaction.py`, no `streaming.py`. The SDK provides all of this.

**What is NOT here (compared to the Pi option):**

There is no TypeScript. No `package.json`, no `tsconfig.json`, no `src/ts/`, no `extensions/`, no `commands/`. The entire project is Python.

---

## 6. Implementation Plan

### Phase 0: SDK Validation Spike (1-2 days)

Before committing to this option, validate that the Claude Agent SDK supports Urika's requirements.

**0.1 Subagent spawning test**
- Write a Python script that uses `query()` to spawn an agent with a system prompt, `allowed_tools`, `max_turns`, and `cwd`
- Verify the agent can write files, run bash commands, and read results
- Verify `bypassPermissions` works and propagates

**0.2 Permission handler test**
- Implement a `can_use_tool` handler that denies writes to specific directories
- Verify the handler is called for every tool use
- Verify `PermissionResultDeny` actually blocks the operation (the LLM gets the error message, not a silent failure)
- Test `PermissionResultAllow` with input rewriting (can we sanitize file paths?)

**0.3 Sequential agent chaining test**
- Orchestrate two agents: agent A writes a file, agent B reads it
- Verify filesystem-based communication works
- Verify `allowed_tools` stripping works (agent B with no Write tool)
- Measure overhead: how long does each `query()` call take to spin up?

**0.4 ClaudeSDKClient test**
- Test multi-turn conversation for interactive investigation setup
- Verify the async iterator yields typed messages correctly

**Exit criteria:** All four tests pass. Subprocess overhead is acceptable (<5 seconds per agent spawn). Permission handlers block unauthorized writes reliably. If any test fails in a way that cannot be worked around, reconsider this option.

### Phase 1: Core Platform Infrastructure (2-3 weeks)

This phase builds the analysis framework foundation. The code here is identical across all options.

**1.1 Configuration system (~2 days)**
- `core/config.py` -- `InvestigationConfig`, `ProjectConfig` dataclasses
- TOML loading/saving for `urika.toml`
- Success criteria JSON format and loading
- Agent configuration (which model, turn limits per agent role)

**1.2 Data loading and profiling (~4 days)**
- `data/dataset.py` -- `Dataset`, `DataSchema`, `ColumnInfo` dataclasses
- `data/loader.py` -- `load_dataset()` with format auto-detection
- `data/readers/tabular.py` -- CSV, Excel, Parquet reader (pandas-based)
- `data/readers/json_reader.py` -- JSON / JSON Lines reader
- `data/profile.py` -- `profile()` function: dtypes, missing values, descriptive stats, distributions, correlations, potential issues
- `data/schema.py` -- schema inference, column role detection (id, target, predictor, group, time)

**1.3 Method base classes and registry (~2 days)**
- `methods/base.py` -- `AnalysisMethod` ABC, `MethodResult` dataclass
- `methods/registry.py` -- `discover_methods()` auto-discovery from Python files
- Template for writing new methods

**1.4 Evaluation framework (~3 days)**
- `evaluation/metrics/base.py` -- `Metric` ABC
- `evaluation/metrics/registry.py` -- `MetricRegistry` with auto-discovery
- Built-in metrics: RMSE, MAE, R2, accuracy, F1, AUC, Cohen's d
- `evaluation/evaluate.py` -- `evaluate()` function
- `evaluation/criteria.py` -- `check_criteria()` against success criteria JSON
- `evaluation/leaderboard.py` -- `update_leaderboard()`, `get_leaderboard()`

**1.5 Session tracking (~2 days)**
- `sessions/tracking.py` -- `log_run()`, `current_session()`
- `sessions/persistence.py` -- SQLite metadata for fast queries across sessions
- `sessions/comparison.py` -- cross-session comparison utilities
- `progress.json` reading/writing

**1.6 Core protocols and pipeline (~2 days)**
- `core/protocols.py` -- `IAnalysisMethod`, `IMetric`, `IDataReader` protocols
- `core/pipeline.py` -- `PipelineStage`, `Pipeline` for ordered processing (pipeline mode)
- `core/exceptions.py` -- custom exception hierarchy

**Phase 1 total: ~15-17 days**

**Milestone: The `urika` Python library is pip-installable. You can write a Python script that loads a CSV, runs a linear regression, evaluates it, checks criteria, and updates a leaderboard -- all using `from urika import ...`.**

### Phase 2: Built-in Methods (~2 weeks)

**2.1 Statistical methods (~4 days)**
- `methods/statistical/linear_regression.py` -- OLS via statsmodels, with diagnostics
- `methods/statistical/logistic_regression.py` -- via statsmodels
- `methods/statistical/t_tests.py` -- `TTest`, `PairedTTest`, `WelchTTest` via scipy/pingouin
- `methods/statistical/anova.py` -- `ANOVA`, `MixedANOVA` via pingouin
- `methods/statistical/nonparametric.py` -- Mann-Whitney U, Kruskal-Wallis, Chi-squared
- `methods/statistical/effect_sizes.py` -- Cohen's d, Hedge's g, eta-squared
- `methods/statistical/mixed_models.py` -- linear mixed effects via statsmodels

**2.2 ML methods (~3 days)**
- `methods/ml/random_forest.py` -- via scikit-learn
- `methods/ml/gradient_boosting.py` -- XGBoost/scikit-learn
- `methods/ml/svm.py` -- via scikit-learn
- `methods/ml/clustering.py` -- KMeans, Hierarchical, DBSCAN
- `methods/ml/dimensionality.py` -- PCA, Factor Analysis

**2.3 Time series methods (~2 days)**
- `methods/timeseries/arima.py` -- via statsmodels
- `methods/timeseries/spectral.py` -- via scipy
- `methods/timeseries/smoothing.py` -- exponential smoothing via statsmodels

**2.4 Additional evaluation metrics (~1 day)**
- `evaluation/metrics/information.py` -- AIC, BIC
- `evaluation/metrics/reliability.py` -- ICC, Cronbach's alpha
- `evaluation/metrics/fit_indices.py` -- CFI, RMSEA

**Phase 2 total: ~10-12 days**

**Milestone: A substantial library of analysis methods and metrics that agents can import and use. Enough to handle the most common analysis patterns across behavioral and health sciences.**

### Phase 3: Multi-Agent Orchestration (~2-3 weeks)

This is where the Claude Agent SDK layer is built. This is the ~5% that is SDK-specific.

**3.1 Permission handlers (~2 days)**
- `agents/security.py` -- `make_permission_handler()` for each agent role
- Handlers return `PermissionResultAllow` or `PermissionResultDeny`
- Write boundary enforcement for task agent, suggestion agent, tool builder
- Bash command allowlisting for evaluator and suggestion agent
- Shell metacharacter blocking
- Tests verifying each handler blocks/allows correctly

**3.2 Agent role definitions (~2 days)**
- `agents/roles/task_agent.py` -- `AgentRoleConfig` dataclass: `allowed_tools`, `system_prompt_path`, `default_model`, `max_turns`, `writable_dirs`
- Same for evaluator, suggestion_agent, tool_builder, literature_agent, system_builder
- `agents/agent_registry.py` -- auto-discover roles from `agents/roles/`

**3.3 Orchestrator (~4 days)**
- `agents/orchestrator.py` -- deterministic Python loop
- Sequence: task agent -> evaluator -> check criteria -> suggestion agent -> (optional) tool builder -> repeat
- Each agent spawned via `query()` with role-specific config
- Session creation, result collection, turn counting
- Termination: criteria met, turn limit, agent requests stop
- Support for `--continue` (resume from last session state)
- `bypassPermissions=True` for autonomous runs

**3.4 Agent prompts (~5 days)**
- `agents/prompts/system_builder.md` -- investigation setup workflow
- `agents/prompts/task_agent.md` -- analysis workflow, how to use `urika` library, how to read suggestions, how to record progress
- `agents/prompts/evaluator.md` -- independent evaluation, criteria checking, do not trust agent claims
- `agents/prompts/suggestion_agent.md` -- strategic analysis, literature integration, actionable suggestions with priorities
- `agents/prompts/tool_builder.md` -- tool/method creation, testing, registration
- `agents/prompts/literature_agent.md` -- knowledge acquisition workflow
- Each prompt includes: role description, available tools, expected outputs, examples, constraints

**3.5 Investigation lifecycle (~2 days)**
- `core/investigation.py` -- `init_investigation()`, `run_investigation()`, `resume_investigation()`
- `urika init` workflow: create directory structure, launch system builder via `ClaudeSDKClient`
- `urika run` workflow: launch orchestrator
- `urika run --continue` workflow: load last session, resume orchestrator

**Phase 3 total: ~15-19 days**

**Milestone: A working multi-agent system. `urika init` launches the system builder for interactive investigation setup. `urika run` launches the orchestrator, which sequences task, evaluator, and suggestion agents. Agents communicate via JSON files on disk. Permission handlers enforce security boundaries.**

### Phase 4: Knowledge Pipeline (~1-2 weeks)

**4.1 PDF extraction (~2 days)**
- `knowledge/pdf_extractor.py` -- text and table extraction via pymupdf
- Handle: multi-column layouts, tables, figures (as image paths), references sections

**4.2 Literature search (~3 days)**
- `knowledge/literature.py` -- web search integration for academic papers
- Semantic Scholar API integration
- ArXiv API integration
- Paper download and extraction

**4.3 Knowledge index (~2 days)**
- `knowledge/index.py` -- `KnowledgeIndex` class
- Add documents, search by query, list methods mentioned, list papers
- JSON-based storage with optional SQLite backing for search

**4.4 Literature agent integration (~1 day)**
- `agents/roles/literature_agent.py` -- config and launch via `query()`
- Integration with orchestrator (called when suggestion agent requests literature)

**Phase 4 total: ~8-10 days**

### Phase 5: CLI and Investigation Modes (~1-2 weeks)

**5.1 CLI implementation (~3 days)**
- `cli.py` -- click subcommands:
  ```
  urika init <name>                 # Create investigation workspace
  urika run                         # Start investigation
  urika run --continue              # Resume last session
  urika run --max-turns <n>         # Limit total turns
  urika status                      # Show investigation status
  urika results                     # Show all results and leaderboard
  urika compare <s1> <s2>           # Compare two sessions
  urika report                      # Generate summary report
  urika knowledge ingest <path>     # Ingest a document
  urika knowledge search <query>    # Search knowledge base
  urika agents --list               # List available agents
  urika tools --list                # List available tools/methods
  ```

**5.2 Investigation modes (~3 days)**
- Confirmatory mode: locked analysis plan, no leaderboard, multiple comparison corrections, transparency log
- Pipeline mode: ordered stages with per-stage criteria
- Mode selection in `urika.toml` and `urika init`
- `guardrails/confirmatory.py` -- plan locking, Bonferroni/Holm/FDR corrections, HARKing detection
- `guardrails/validators.py` -- assumption checking, sample size warnings

**5.3 Reporting (~2 days)**
- `urika report` -- generate a markdown summary of the investigation
- Include: research question, methods tried, results, best method, leaderboard, plots, recommendations

**Phase 5 total: ~8-10 days**

### Phase 6: Testing and Hardening (~1-2 weeks)

**6.1 Unit tests (~3 days)**
- Data: loading each format, profiling, schema inference
- Methods: each built-in method produces correct output on known data
- Evaluation: each metric computes correctly, criteria checking, leaderboard
- Security: permission handlers block/allow correctly for each agent role

**6.2 Integration tests (~3 days)**
- End-to-end: CSV dataset -> `urika init` -> `urika run --max-turns 10` -> results
- Agent security: verify evaluator cannot write, task agent cannot modify evaluation
- Session resume: run, stop, resume, verify state continuity
- Permission handler: verify `can_use_tool` denies unauthorized writes at the SDK level

**6.3 Hardening (~2 days)**
- Error messages for common failures (missing API key, data format errors, method failures)
- Graceful degradation when optional dependencies are missing
- Signal handling (Ctrl+C saves session state)
- Cost tracking and estimation (log token usage per agent)

**Phase 6 total: ~8-10 days**

### Phase 7: Domain Packs (post-core, ongoing)

Domain packs are separate optional installs. Each provides domain-specific readers, methods, metrics, pipeline stages, and prompt templates.

Priority order:

1. **Survey/Psychometrics** -- factor analysis, SEM, Cronbach's alpha, Likert scale methods
2. **Cognitive Experiments** -- RT analysis, signal detection theory, drift diffusion models
3. **Wearable Sensors** -- IMU readers, activity classification, signal processing pipelines
4. **Motor Control** -- C3D readers, kinematics, coordination analysis
5. **Eye Tracking** -- fixation analysis, scanpath comparison, pupillometry
6. **Cognitive Neuroscience** -- EDF readers, ERP analysis, time-frequency, MVPA (requires MNE)
7. **Linguistics** -- NLP pipelines, acoustic analysis, speech processing
8. **Epidemiology** -- survival analysis, spatial statistics, case-control methods

### Total Timeline Estimate

| Phase | Duration | Cumulative |
|-------|---------|-----------|
| Phase 0: SDK Validation Spike | 1-2 days | 1-2 days |
| Phase 1: Core Platform | 2-3 weeks | 2-3 weeks |
| Phase 2: Built-in Methods | 2 weeks | 4-5 weeks |
| Phase 3: Multi-Agent Orchestration | 2-3 weeks | 6-8 weeks |
| Phase 4: Knowledge Pipeline | 1-2 weeks | 7-10 weeks |
| Phase 5: CLI and Modes | 1-2 weeks | 8-12 weeks |
| Phase 6: Testing and Hardening | 1-2 weeks | 9-14 weeks |
| **Total to working system** | **9-14 weeks** | |
| Phase 7: Domain Packs | Ongoing | |

**Compare with Option B (custom runtime):** Option B requires 4-6 additional weeks upfront to build the agent runtime (agent loop, LLM providers, core tools, session management, context window management, streaming). That puts Option B at 13-20 weeks. The Claude Agent SDK saves 4-6 weeks and eliminates ongoing runtime maintenance.

**Compare with the Pi option:** Pi saves similar development time but introduces a TypeScript/Python split stack. The Claude Agent SDK option keeps everything in Python. Pi gives you multi-model support. The Claude Agent SDK does not.

---

## 7. Risks and Mitigations

### Risk 1: Vendor Lock-in to Anthropic

**Risk:** Urika can only use Claude models. If Anthropic raises prices significantly, degrades model quality, changes API terms unfavorably, or if a research institution requires non-Anthropic models (budget, data sovereignty, institutional agreements), Urika cannot adapt without a migration.

**Likelihood:** Medium. Anthropic is a well-funded company with strong models, but the AI landscape is unpredictable. Price changes and institutional mandates are real possibilities.

**Mitigation:**
- The `urika` Python package (80% of the codebase) has zero coupling to the Claude Agent SDK. It is a regular pip-installable library. If you need to migrate, you swap the orchestration layer (~5% of code), not the analysis framework.
- The orchestrator is a deterministic Python loop that calls `query()`. Replacing `query()` with a different agent-spawning mechanism (custom LLM client, LangGraph, Pi, etc.) is a contained change.
- Design the `agents/roles/*.py` configs to be SDK-agnostic data: system prompt path, allowed tools (as strings), writable dirs, max turns. Only `agents/orchestrator.py` and `agents/security.py` import from `claude_code_sdk`.
- Monitor alternative runtimes. If multi-model becomes a hard requirement, migrate the orchestration layer.

### Risk 2: Claude Agent SDK Maturity

**Risk:** The Claude Agent SDK is relatively new. APIs may change. Features may be added or deprecated. Documentation may be incomplete. Edge cases may not be handled.

**Likelihood:** Medium-high. SDKs from active companies evolve rapidly in their first year.

**Mitigation:**
- Phase 0 validation spike catches showstopper issues before committing
- Pin `claude-code-sdk` to a specific version in `pyproject.toml`
- Isolate SDK imports to two files: `agents/orchestrator.py` and `agents/security.py`. SDK API changes are absorbed in those files, not scattered across the codebase.
- Test against SDK updates in CI before upgrading
- Worst case: the SDK is open-source (or the API is documented). If a specific version works, pin it and do not upgrade until needed.

### Risk 3: Subprocess Overhead

**Risk:** Each `query()` call spawns a Claude Code subprocess. If the overhead is >5 seconds per spawn, and the orchestrator runs 4 agents per turn for 50 turns, that is 200 agent spawns = 17+ minutes of pure overhead (not counting LLM time).

**Likelihood:** Medium. Subprocess spawning is inherently slower than in-process function calls. The overhead depends on SDK internals (initialization, tool registration, model warm-up).

**Mitigation:**
- Phase 0 spike measures actual overhead. If it is unacceptable, consider:
  - Using `ClaudeSDKClient` for agents that run multiple times (keeps the session alive, avoids re-spawn)
  - Batching multiple evaluator checks into a single agent run
  - Running the evaluator less frequently (every N task agent turns instead of every turn)
- For most investigations (10-30 turns), even 5-second overhead per spawn is tolerable (3-10 minutes total)
- The LLM inference time (30-120 seconds per agent turn) will dominate. Subprocess overhead is likely <10% of total time.

### Risk 4: `can_use_tool` Handler Reliability

**Risk:** The `can_use_tool` handler might not be called for all tool uses, might be called with unexpected input formats, or might not reliably block operations. If the handler fails silently, agents could escape their security boundaries.

**Likelihood:** Low-medium. The SDK is designed for this use case, but edge cases exist (tool calls from subagents, tool calls during streaming, etc.).

**Mitigation:**
- Phase 0 spike tests this specifically and extensively
- Defense in depth: combine `allowed_tools` (strips tools entirely) with `can_use_tool` (conditional logic). Even if `can_use_tool` fails, the evaluator has no `Write` tool in its `allowed_tools` list.
- Audit logging: log every tool call (via async iterator) regardless of whether the handler blocked it. Post-hoc verification catches any handler failures.
- If the handler is unreliable for writes, fall back to a `PostToolUse` hook that checks filesystem state after each tool call and `rewind_files()` if unauthorized writes occurred.

### Risk 5: Debugging SDK Internals

**Risk:** When agents behave unexpectedly (wrong tool calls, hallucinated outputs, context window issues), debugging requires understanding what happened inside the SDK's agent loop. You cannot set breakpoints in Anthropic's code.

**Likelihood:** High. Debugging agentic systems is inherently difficult. Not being able to inspect the loop makes it harder.

**Mitigation:**
- Use the async iterator to log every message, tool call, and result. The logs are your debugger.
- Reproduce issues by replaying the same prompt and system prompt in a standalone `query()` call with verbose logging.
- The `ResultMessage` from `query()` includes the full conversation history. Inspect it.
- For persistent issues, extract the prompt and tool definitions and test them directly against the Claude API (no SDK) to determine if the issue is in the SDK or in your prompts.
- Keep system prompts deterministic and well-structured. Most "SDK bugs" are actually prompt engineering issues.

### Risk 6: LLM Token Costs

**Risk:** Multi-agent orchestration multiplies LLM costs. Each orchestrator turn involves 4+ agent sessions. An investigation with 50 turns means 200+ LLM calls, potentially costing $50-100+ with Opus.

**Likelihood:** High. Inherent to multi-agent architectures.

**Mitigation:**
- Model tiering: Sonnet (cheap) for task agents and evaluator, Opus (expensive) only for the suggestion agent which needs strategic reasoning. Haiku-class models for data profiling.
- Turn budgets: configurable `max_turns` with cost estimation before each turn
- Cost tracking: the orchestrator logs cumulative LLM costs, can pause for user confirmation at thresholds
- Short agent sessions: each agent is spawned fresh with focused context, not a long-running conversation
- Aggressive prompt engineering: system prompts should be concise, not verbose

### Risk 7: Agent Quality and Reliability

**Risk:** LLM agents write buggy Python scripts. Scripts crash, import the wrong things, write incorrect JSON formats, fail to record progress. The multi-agent loop degrades because one agent's output is garbage that the next agent cannot process.

**Likelihood:** High. This is the fundamental challenge of agentic systems.

**Mitigation:**
- High-quality system prompts with concrete examples of correct scripts (Phase 3.4)
- The urika Python package validates inputs aggressively -- `load_dataset()` raises clear errors for wrong paths/formats, `log_run()` validates JSON schema, `update_leaderboard()` validates metric values
- The evaluation runner catches exceptions and returns structured error results (not crashes)
- The orchestrator checks agent outputs between turns -- if progress.json is malformed or missing, the next agent gets an error message with instructions to fix it
- Retry logic: if an agent's script fails, the orchestrator can re-prompt the agent with the error
- `rewind_files()` can roll back a failed agent's filesystem changes before the next agent runs

### Risk 8: Python Environment Management

**Risk:** Users have different Python versions, missing scientific packages, broken pip installs, conda vs pip conflicts. The urika Python package fails to install or import.

**Likelihood:** High. Python environment management is notoriously fragile, and scientific packages (numpy, scipy, etc.) have native dependencies.

**Mitigation:**
- Require Python >=3.10, detect and report version issues at install time
- Recommend `uv` for installation (`uv pip install urika`) -- faster, more reliable than pip
- Provide a `urika doctor` command that checks: Python version, required packages importable, Claude Agent SDK installed, API key configured, sample data loads correctly
- Minimal core dependencies: numpy, pandas, scipy, scikit-learn, statsmodels. Domain-specific packages are optional extras: `pip install urika[neuroscience]`
- Test installation on clean environments (Python 3.10, 3.11, 3.12) in CI

---

## 8. Migration Path

If you later need multi-model support or want to move away from Anthropic, here is what changes and what stays.

### What Does NOT Change (the 95%)

The entire `urika` Python package is runtime-agnostic:

| Component | Files | Coupling to SDK |
|-----------|-------|----------------|
| Data loading | `data/*` | None |
| Analysis methods | `methods/*` | None |
| Evaluation framework | `evaluation/*` | None |
| Knowledge pipeline | `knowledge/*` | None |
| Session tracking | `sessions/*` | None |
| Investigation modes | `guardrails/*` | None |
| Core config | `core/*` | None |
| CLI framework | `cli.py` (mostly) | Calls `run_investigation()` which internally uses SDK |

These modules import from `urika.*` only. They do not know the Claude Agent SDK exists. They work in any Python environment.

### What Changes (the 5%)

| File | What it does now | What it becomes |
|------|-----------------|----------------|
| `agents/orchestrator.py` | Calls `query()` / `ClaudeSDKClient` to spawn agents | Calls new runtime's agent-spawning API |
| `agents/security.py` | Returns `PermissionResultAllow` / `PermissionResultDeny` | New runtime's permission mechanism |
| `agents/roles/*.py` | References `allowed_tools` as SDK tool names | Maps to new runtime's tool names |
| `cli.py` (partially) | `urika run` calls orchestrator which uses SDK | `urika run` calls orchestrator which uses new runtime |

### Migration to Pi

If you want multi-model support via Pi:

1. Rewrite `agents/orchestrator.py` to use `createAgentSession()` instead of `query()`
2. Rewrite `agents/security.py` to use Pi's `tool_call` event hooks instead of `can_use_tool`
3. Add `package.json` and TypeScript extension for Pi integration
4. The Python `urika` package does not change at all

**Estimated effort: 1-2 weeks.**

**Tradeoff:** You gain 15+ LLM providers. You lose the all-Python stack (TypeScript enters for orchestration/security). The analysis framework is identical.

### Migration to Custom Python Runtime

If you want full control and multi-model in Python:

1. Build the agent runtime described in Option B: agent loop, LLM providers, core tools, session management (~4-6 weeks)
2. Rewrite `agents/orchestrator.py` to use custom `AgentLoop` instead of `query()`
3. Rewrite `agents/security.py` to use per-agent `ToolRegistry` construction instead of `can_use_tool`
4. The Python `urika` package does not change at all

**Estimated effort: 5-7 weeks** (mostly the runtime construction).

**Tradeoff:** You gain full control, full debuggability, any LLM provider. You take on runtime maintenance. The analysis framework is identical.

### Migration to LangGraph, CrewAI, or Other Framework

1. Rewrite `agents/orchestrator.py` to use the framework's agent orchestration primitives
2. Rewrite `agents/security.py` to use the framework's permission/tool management
3. The Python `urika` package does not change at all

**Estimated effort: 2-4 weeks** depending on framework complexity.

### The Key Insight

The migration cost is proportional to the orchestration layer, which is ~5% of the codebase. The analysis platform -- the thing that makes Urika useful -- is 95% of the code and transfers unchanged. This is by design: the `urika` package does not import from `claude_code_sdk`, does not know about `query()`, and does not reference any runtime concept. It is a regular Python library that agents happen to call from scripts.

Choosing the Claude Agent SDK now does not prevent you from switching later. It lets you start building the actual product faster because you skip the runtime work entirely.

---

## 9. Comparison with Other Options

### vs. Option B (Custom Python Runtime)

| Dimension | Claude Agent SDK | Custom Runtime |
|-----------|-----------------|----------------|
| **Time to first agent** | Day 1 (after Phase 0 spike) | Week 4-6 (after building runtime) |
| **Total timeline** | 9-14 weeks | 13-20 weeks |
| **Language** | All Python | All Python |
| **Model support** | Claude only | Any (Anthropic, OpenAI, Gemini, local) |
| **Debugging** | Cannot inspect SDK internals | Can breakpoint every line |
| **Maintenance** | SDK maintained by Anthropic | Runtime maintained by you |
| **Tool quality** | Battle-tested Read/Write/Edit/Bash | Your v1 implementations |
| **Context management** | SDK handles it | You build it |
| **Permission model** | `can_use_tool` + `allowed_tools` | Per-agent `ToolRegistry` construction |
| **Vendor lock-in** | Yes (Anthropic) | No |
| **Migration cost** | Swap orchestration layer (~5%) | N/A (already independent) |

**When to choose Claude Agent SDK:** You want to validate the analysis platform concept as fast as possible. The runtime is not the product. You are comfortable with Claude as the LLM (at least for v1). You want minimal maintenance burden.

**When to choose Custom Runtime:** Model flexibility is a hard requirement today (not "maybe someday"). You want full control over every layer. You have 5+ months of development time. You enjoy building infrastructure.

### vs. Pi Option

| Dimension | Claude Agent SDK | Pi |
|-----------|-----------------|-----|
| **Time to first agent** | Day 1 | Day 1 (Pi is also ready to use) |
| **Language** | All Python | TypeScript (orchestration) + Python (analysis) |
| **Model support** | Claude only | 15+ LLM providers |
| **Package managers** | pip only | npm + pip |
| **Debugging** | Python only | TypeScript + Python |
| **Permission model** | Python `can_use_tool` handler | TypeScript event hooks |
| **Community** | Anthropic SDK users | Pi community |
| **Upstream dependency** | Anthropic (large company) | Pi (individual maintainer, MIT) |
| **Researcher accessibility** | Python-native audience | Requires Node.js |

**When to choose Claude Agent SDK:** You want an all-Python stack. Your target audience (researchers) should not encounter TypeScript or npm. You are comfortable with Claude-only for now.

**When to choose Pi:** Multi-model support is important from day one. You are comfortable managing a TypeScript+Python split stack. You value Pi's session management and TUI features.

---

## 10. Open Questions

1. **`query()` vs `ClaudeSDKClient` for the orchestrator loop.** Should each agent be a one-shot `query()` call (simpler, fully isolated) or a `ClaudeSDKClient` conversation (can ask follow-up questions, handle errors interactively)? Recommendation: start with `query()` for simplicity. Use `ClaudeSDKClient` only for the system builder (which is interactive by nature).

2. **Custom MCP tools vs bash-only.** Should Urika register custom tools via `@tool` decorator (e.g., `urika_evaluate(method, dataset)`) or should agents always write Python scripts and run them via bash? Recommendation: bash-only for v1. Custom tools add a layer of abstraction that limits agent flexibility. Agents writing scripts can do anything Python can do, not just what you pre-built tools for.

3. **Model selection per agent.** The SDK supports specifying the model. Should different agent roles use different models? Recommendation: Yes. Suggestion agent uses Opus (strategic reasoning). Task agent and evaluator use Sonnet (routine work). Literature agent uses Sonnet. System builder uses Opus (complex scoping). This controls cost while maintaining quality where it matters.

4. **Parallel agent runs.** The orchestrator loop is sequential. Could task agents and the literature agent run in parallel? Recommendation: not for v1. Sequential is simpler to debug and reason about. Parallel execution is an optimization for later.

5. **Session resume granularity.** When `urika run --continue` resumes, does it re-spawn agents from scratch with updated context, or try to resume mid-agent-turn? Recommendation: re-spawn from scratch. Each `query()` call is stateless. The orchestrator reads filesystem state (progress.json, leaderboard.json) and constructs fresh prompts for each agent. Simpler and more robust than trying to resume a subprocess mid-stream.

6. **`rewind_files()` scope.** When should the orchestrator use `rewind_files()` to roll back a failed agent's changes? Recommendation: when a tool builder creates something that fails tests, or when a task agent corrupts progress.json. Not for routine failures (agent script crashes are normal and recoverable).

7. **Domain pack distribution.** Separate PyPI packages (`urika-neuroscience`, `urika-psychometrics`) or optional dependency groups (`pip install urika[neuroscience]`)? Recommendation: optional dependency groups for v1 (simpler). Separate packages if the dependency trees become large or conflicting.
