# Agent Roles & Orchestrator Design

**Date**: 2026-03-09
**Status**: Approved
**Context**: Phase 10 of Urika — real agent roles + orchestrator loop to run experiments end-to-end.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Agent roles | 4 (task, evaluator, suggestion, tool builder) | Minimum for a complete loop + on-demand tool creation |
| Orchestrator style | Hybrid: deterministic loop + LLM at decision points | Predictable flow with intelligent pivot/stop decisions |
| SDK coupling | Direct Claude SDK via existing ClaudeSDKRunner | SDK already set up, no need for abstraction layer |
| Testing | FakeRunner for orchestrator loop tests | Verify loop logic without API calls |
| CLI integration | Not in this phase | Orchestrator is a Python API; `urika run` wired later |

---

## 2. Agent Roles

Each role follows the existing echo pattern: module in `agents/roles/` with `get_role()` factory, markdown prompt in `agents/roles/prompts/`.

### Task Agent
- **File**: `roles/task_agent.py`, prompt: `prompts/task_agent_system.md`
- **Purpose**: Explores data, runs methods, records observations
- **Tools**: Read, Write, Bash (python/pip only), Glob, Grep
- **Security**: Write to experiment dir only
- **Max turns**: 25

### Evaluator
- **File**: `roles/evaluator.py`, prompt: `prompts/evaluator_system.md`
- **Purpose**: Scores results, validates against success criteria
- **Tools**: Read, Glob, Grep (read-only)
- **Security**: No write access
- **Max turns**: 10

### Suggestion Agent
- **File**: `roles/suggestion_agent.py`, prompt: `prompts/suggestion_agent_system.md`
- **Purpose**: Analyzes results, proposes 1-3 next experiments with hypotheses
- **Tools**: Read, Glob, Grep (read-only)
- **Security**: No write access
- **Max turns**: 10

### Tool Builder
- **File**: `roles/tool_builder.py`, prompt: `prompts/tool_builder_system.md`
- **Purpose**: Creates project-specific tools implementing ITool
- **Tools**: Read, Write, Bash (python/pip/pytest only)
- **Security**: Write to project `tools/` dir only
- **Max turns**: 15

All `build_config(project_dir, experiment_id=..., **kwargs)` functions build an `AgentConfig` with appropriate security sandbox and system prompt with variable substitution.

---

## 3. System Prompts

Each prompt is a markdown file (~50-100 lines) establishing role, constraints, output format.

| Prompt | Variables | Key instructions |
|---|---|---|
| `task_agent_system.md` | `{project_dir}`, `{experiment_id}`, `{experiment_dir}` | Explore data, run methods via Python, record RunRecords, write artifacts to artifacts/ |
| `evaluator_system.md` | `{project_dir}`, `{experiment_id}`, `{experiment_dir}` | Read progress.json, score against success criteria, NO write access, output JSON evaluation |
| `suggestion_agent_system.md` | `{project_dir}`, `{experiment_id}`, `{experiment_dir}` | Review results + labbook, propose 1-3 next experiments, NO write access, structured suggestions |
| `tool_builder_system.md` | `{project_dir}`, `{tools_dir}` | Build ITool implementations in tools/, include get_tool() factory, run pytest to verify |

---

## 4. Orchestrator

### Module Structure

```
src/urika/orchestrator/
    __init__.py          # Public API: run_experiment
    loop.py              # Main orchestrator loop
    parsing.py           # Parse agent text output → RunRecords, suggestions
```

### Loop Design

```python
async def run_experiment(project_dir, experiment_id, runner, *, max_turns=50):
```

Each orchestrator turn:
1. Run **task agent** → explore data, run methods
2. Parse output → call `append_run()` for any RunRecords
3. Run **evaluator** → score results, check criteria
4. If criteria met → `complete_session()`, return
5. Run **suggestion agent** → propose next steps
6. If suggestion requests a tool → run **tool builder**
7. Feed suggestions as next task agent prompt
8. `update_turn()` → increment counter
9. If `current_turn >= max_turns` → `complete_session()`, return

On error → `fail_session()`.

### LLM Decision Points

A `_should_continue()` helper asks the SDK at strategic moments:
- After evaluator: "Are results robust enough to stop?"
- After N turns without metric improvement: "Should we pivot?"

### Session Integration

Uses existing session management:
- `start_session()` at loop start (acquires lock)
- `update_turn()` each iteration
- `record_agent_session()` to track SDK session IDs
- `complete_session()` / `fail_session()` at end

### Output Parsing

`parsing.py` extracts structured data from agent text output:
- `parse_run_records(text) → list[RunRecord]` — finds JSON blocks with metrics
- `parse_suggestions(text) → list[dict]` — finds suggested experiments
- `parse_evaluation(text) → dict` — extracts criteria pass/fail + scores

---

## 5. Testing Strategy

- **Agent roles**: Same pattern as echo — verify `build_config()` produces correct `AgentConfig` (security, tools, prompt content)
- **Orchestrator loop**: FakeRunner returning canned AgentResults to verify turn counting, session state transitions, criteria checking, error handling
- **Parsing**: Unit tests with sample agent output strings
- **No integration tests requiring API calls** in the test suite
