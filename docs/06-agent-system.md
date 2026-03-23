# Agent System

Urika uses a multi-agent architecture where specialized agents collaborate through a structured experiment loop. Each agent has a defined role, specific tool access, and security boundaries that control what it can read and write.


## Architecture Overview

The system follows a **research team model**: agents take on roles analogous to members of a research group. A deterministic orchestrator drives the experiment loop, calling agents in sequence and using structured JSON parsing to pass information between them.

Key design principles:

- **Separation of concerns** -- each agent has one job (planning, execution, evaluation, advising)
- **Security boundaries** -- read-only agents cannot modify project state; writable agents are restricted to specific directories
- **Filesystem communication** -- agents exchange information through files (progress.json, methods.json, suggestions/) rather than direct message passing
- **Stateless agents** -- each agent invocation is independent; context is provided through the system prompt and the filesystem


## Agent Roles

### 1. Project Builder

**Name:** `project_builder`

Scopes new projects by analyzing data sources. During `urika new`, the project builder agent examines the scanned data profile and asks clarifying questions to understand the research goals, target variables, analysis constraints, and domain context. It generates structured questions with optional multiple-choice answers.

| Property | Value |
|----------|-------|
| Tools | Read, Glob, Grep |
| Writable dirs | None (read-only) |
| Max turns | 10 |

---

### 2. Planning Agent

**Name:** `planning_agent`

Designs complete analytical method pipelines. Given the current project state and previous results, the planning agent reads experiment data and proposes a specific method to try next -- including the algorithm, feature engineering steps, hyperparameters, and expected outcome. It can also flag when a custom tool or literature search is needed.

| Property | Value |
|----------|-------|
| Tools | Read, Glob, Grep |
| Writable dirs | None (read-only) |
| Max turns | 10 |

---

### 3. Task Agent

**Name:** `task_agent`

The only agent that writes and executes Python code. It takes a method plan (from the planning agent or the orchestrator) and implements it: loading data, building models, computing metrics, generating visualizations, and recording structured results. It writes method scripts and artifacts to the experiment directory.

| Property | Value |
|----------|-------|
| Tools | Read, Write, Bash, Glob, Grep |
| Writable dirs | `experiments/<id>/` |
| Allowed bash | `python`, `pip` |
| Blocked bash | `rm -rf`, `git push`, `git reset` |
| Max turns | 25 |

---

### 4. Evaluator

**Name:** `evaluator`

Scores experiment results against the project's success criteria. The evaluator reads the task agent's output, examines metrics, and determines whether criteria have been met. It is strictly read-only -- it cannot modify any files. When criteria are met, the orchestrator completes the experiment.

| Property | Value |
|----------|-------|
| Tools | Read, Glob, Grep |
| Writable dirs | None (read-only) |
| Max turns | 10 |

---

### 5. Advisor Agent

**Name:** `advisor_agent`

Acts as a research advisor. After the evaluator scores results, the advisor reviews everything and proposes what to try next. It can suggest new methods, parameter adjustments, feature engineering ideas, or entirely new experimental directions. It can also propose updates to the success criteria based on what has been learned.

The advisor agent is also used for interactive conversation in the REPL and via `urika advisor`.

| Property | Value |
|----------|-------|
| Tools | Read, Glob, Grep |
| Writable dirs | None (read-only) |
| Max turns | 10 |

---

### 6. Tool Builder

**Name:** `tool_builder`

Creates reusable project-specific tools when the planning agent identifies a need that existing built-in tools do not cover. Tool builder writes Python modules that implement the `ITool` interface and saves them to the project's `tools/` directory, where they are discoverable by subsequent runs.

You can also request tools directly. From the REPL, ask the advisor:

```
urika:my-project> I need a tool that computes inter-rater reliability (Cohen's kappa and ICC)
```

Or provide a list of tools you know you'll need in the project description during setup. The planning agent will flag these as tool requests and the tool builder will create them before experiments begin.

| Property | Value |
|----------|-------|
| Tools | Read, Write, Bash, Glob, Grep |
| Writable dirs | `tools/` |
| Allowed bash | `python`, `pip`, `pytest` |
| Blocked bash | `rm -rf`, `git push`, `git reset` |
| Max turns | 15 |

---

### 7. Literature Agent

**Name:** `literature_agent`

Searches the project's knowledge base for domain-relevant information. When the planning agent flags that a method requires literature context (e.g., a specific algorithm or domain knowledge), the literature agent searches ingested documents and returns relevant excerpts.

The literature agent can also search the web for relevant papers and methods when web search is enabled (see [Configuration](10-configuration.md)). This allows it to find whether a proposed method has been used in similar research before, or discover methods that might be useful for your specific problem.

Adding even 1-2 relevant papers to your project's `knowledge/papers/` directory significantly improves the quality of the agents' work. See [Knowledge Pipeline](09-knowledge-pipeline.md) for details.

| Property | Value |
|----------|-------|
| Tools | Read, Write, Bash, Glob, Grep |
| Writable dirs | `knowledge/` |
| Allowed bash | `python`, `pip` |
| Blocked bash | `rm -rf`, `git push`, `git reset` |
| Max turns | 15 |

---

### 8. Report Agent

**Name:** `report_agent`

Writes narrative markdown reports from experiment results. The report agent reads progress data, metrics, observations, and artifacts, then produces a coherent research narrative. It writes experiment-level narratives and project-level summaries that go beyond the auto-generated templates.

| Property | Value |
|----------|-------|
| Tools | Read, Glob, Grep |
| Writable dirs | None (read-only) |
| Max turns | 15 |

The report agent does not write files directly. It returns narrative text which the orchestrator or CLI writes to the appropriate location using versioned file writing.

---

### 9. Presentation Agent

**Name:** `presentation_agent`

Creates reveal.js slide deck content from experiment results. The agent reads project data and outputs structured JSON with slide definitions (title, type, bullets, figures, stats). This JSON is then rendered into HTML by the presentation module.

| Property | Value |
|----------|-------|
| Tools | Read, Glob, Grep |
| Writable dirs | None (read-only) |
| Max turns | 10 |


## The Orchestrator

The orchestrator manages the experiment loop -- a deterministic cycle that calls agents in a fixed sequence. There are two levels of orchestration:

### Experiment Loop

The inner loop (`run_experiment`) runs a single experiment through repeated cycles of:

```
Planning Agent  -->  Task Agent  -->  Evaluator  -->  Advisor Agent
     |                                                      |
     +------- next turn prompt <--- suggestions ---<--------+
```

Each turn:

1. **Planning Agent** reads current state and designs the next method
2. If the plan flags `needs_tool`, the **Tool Builder** is called to create it
3. If the plan flags `needs_literature`, the **Literature Agent** provides context
4. **Task Agent** implements and runs the method, recording results
5. Run records are parsed and appended to `progress.json`; methods are registered in `methods.json`
6. **Evaluator** scores results against criteria
7. If criteria are met, the experiment is marked complete and reports are generated
8. **Advisor Agent** reviews everything and proposes next steps
9. Suggestions are saved to `experiments/<id>/suggestions/turn-N.json`
10. The advisor's suggestions become the task prompt for the next turn

Before the first turn, a **knowledge scan** checks for ingested documents and provides relevant context.

The loop runs for up to `max_turns` turns (configurable per experiment or in `urika.toml`). If criteria are never met, the experiment is still marked completed after the final turn.

### Meta-Orchestrator

The outer loop (`run_project`) manages experiment-to-experiment flow:

- Calls the advisor agent to propose the next experiment
- Creates the experiment
- Runs it through the experiment loop
- In **checkpoint** mode, pauses for user input between experiments
- In **capped** mode, runs up to N experiments without pausing
- In **unlimited** mode, continues until criteria are fully met (safety cap of 50)
- Checks whether all criteria are satisfied after each experiment


## Agent Communication via Filesystem

Agents do not communicate directly. All state is persisted to the filesystem, and each agent reads what it needs from disk:

### Key Files

| File | Written by | Read by | Contents |
|------|-----------|---------|----------|
| `progress.json` | Orchestrator (from task agent output) | All agents | Runs with metrics, observations, hypotheses, next steps |
| `methods.json` | Orchestrator (from task agent output) | Planning, Advisor, Evaluator | Registry of all methods tried with metrics and status |
| `criteria.json` | Orchestrator (from advisor suggestions) | Evaluator, Advisor | Versioned success criteria with thresholds |
| `suggestions/initial.json` | Project builder flow | Orchestrator | Initial experiment suggestions from project creation |
| `suggestions/turn-N.json` | Orchestrator (from advisor output) | Planning agent (next turn) | Per-turn suggestions with raw text and parsed JSON |
| `leaderboard.json` | Orchestrator | Results display | Best-per-method ranking sorted by primary metric |
| `experiments/<id>/artifacts/` | Task agent | Report, Presentation agents | Figures, plots, saved models |
| `experiments/<id>/methods/` | Task agent | Planning agent | Python scripts for each method |
| `knowledge/` | Literature agent, knowledge ingest | Literature agent, Planning agent | Ingested documents and search index |
| `usage.json` | REPL session, CLI | Usage display | Session-level token and cost tracking |


## Security Boundaries

Security is enforced through `SecurityPolicy` on each agent's configuration:

### Read-Only Agents

These agents can read the entire project directory but cannot write to any files:

- Project Builder
- Planning Agent
- Evaluator
- Advisor Agent
- Report Agent
- Presentation Agent

### Writable Agents

These agents have write access restricted to specific directories:

| Agent | Writable Directory | Allowed Commands |
|-------|-------------------|-----------------|
| Task Agent | `experiments/<id>/` | `python`, `pip` |
| Tool Builder | `tools/` | `python`, `pip`, `pytest` |
| Literature Agent | `knowledge/` | `python`, `pip` |

### Blocked Patterns

All writable agents block destructive commands: `rm -rf`, `git push`, `git reset`.

### Tool Restrictions

Read-only agents only have access to `Read`, `Glob`, and `Grep` tools. They cannot use `Write`, `Bash`, or any tool that modifies the filesystem.

Writable agents additionally have access to `Write` and `Bash`, with bash commands filtered by the allowed prefix and blocked pattern lists.


## Agent Configuration

Each agent's behavior is configured through:

- **System prompt** -- loaded from a markdown template in `agents/roles/prompts/`, with variables like `project_dir` and `experiment_id` injected at runtime
- **Allowed tools** -- the specific tools the agent can use
- **Security policy** -- writable directories, readable directories, bash command restrictions
- **Max turns** -- maximum number of tool-use turns per invocation
- **Working directory** -- set to the project directory

The Claude Agent SDK adapter (`ClaudeSDKRunner`) translates these configurations into SDK-compatible parameters and handles execution, streaming, and result parsing.
