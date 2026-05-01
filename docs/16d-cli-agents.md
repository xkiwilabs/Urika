# CLI Reference — Agents

Agent invocation commands (advisor, evaluate, plan, finalize, build-tool, summarize). See [Projects](16a-cli-projects.md) for the intro, [Experiments](16b-cli-experiments.md), [Results and Reports](16c-cli-results.md), and [System](16e-cli-system.md) for the rest of the CLI surface.

## Agents

### `urika advisor`

Ask the advisor agent a question about the project. Provides project context (methods tried, current state) alongside your question.

```
urika advisor [PROJECT] [TEXT]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `TEXT` | Question or instructions (prompted if omitted) |

**Example:**

```bash
urika advisor my-project "What methods should I try next?"
```

After the advisor responds with experiment suggestions, you are offered the option to run them immediately. See [Advisor Chat and Instructions](07-advisor-and-instructions.md) for the full guide on advisor conversations, the suggestion-to-run flow, and how to steer agents with instructions.

---

### `urika evaluate`

Run the evaluator agent on an experiment to score results against success criteria.

```
urika evaluate [PROJECT] [EXPERIMENT_ID]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `EXPERIMENT_ID` | Experiment to evaluate (defaults to most recent) |

---

### `urika plan`

Run the planning agent to design the next analytical method for an experiment.

```
urika plan [PROJECT] [EXPERIMENT_ID]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `EXPERIMENT_ID` | Experiment to plan for (defaults to most recent) |


### `urika finalize`

Run the finalization sequence on a project: Finalizer Agent (selects best methods, writes standalone scripts, findings, and reproducibility artifacts), Report Agent (final report), Presentation Agent (final presentation), and README update.

```
urika finalize [PROJECT] [OPTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |

**Options:**

| Option | Description |
|--------|-------------|
| `--instructions TEXT` | Optional instructions for the finalizer agent (e.g., "focus on the random forest method") |
| `--audience [novice\|standard\|expert]` | Control explanation depth in reports and presentations (default: standard) |
| `--draft` | Interim summary -- outputs to `projectbook/draft/`, does not overwrite final outputs or write standalone scripts |

**Examples:**

```bash
urika finalize my-project
urika finalize my-project --instructions "emphasize the ensemble methods"
urika finalize my-project --draft
urika finalize my-project --draft --audience novice
```

See [Finalizing Projects](09-finalizing-projects.md) for details on what is produced, including draft mode.

---

### `urika build-tool`

Build a custom tool for the project. The tool builder agent creates a Python module in the project's `tools/` directory based on your instructions.

```
urika build-tool [PROJECT] [INSTRUCTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `INSTRUCTIONS` | What tool to build (prompted if omitted) |

**Examples:**

```bash
urika build-tool my-project "create an EEG epoch extractor using MNE"
urika build-tool my-project "build a tool that computes ICC using pingouin"
urika build-tool my-project "install librosa and create an audio feature extractor"
```

---

### `urika summarize`

Run the **Project Summarizer** agent on a project. Reads project files (config, criteria, methods, leaderboard) and the experiment history, then writes a high-level summary to `projectbook/summary.md`.

```
urika summarize [PROJECT] [OPTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |

**Options:**

| Option | Description |
|--------|-------------|
| `--instructions TEXT` | Optional guidance to steer the summarizer (e.g., "focus on open questions"). |
| `--json` | Output the summarizer result as JSON. |

**Examples:**

```bash
urika summarize my-project
urika summarize my-project --instructions "focus on what's still unknown"
urika summarize my-project --json
```


## See also

- [CLI Reference — Projects](16a-cli-projects.md)
- [CLI Reference — Experiments](16b-cli-experiments.md)
- [CLI Reference — Results and Reports](16c-cli-results.md)
- [CLI Reference — System](16e-cli-system.md)
- [Configuration](14a-project-config.md)
- [Interactive TUI](17-interactive-tui.md)
- [Dashboard](18a-dashboard-pages.md)
