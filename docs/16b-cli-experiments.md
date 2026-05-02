# CLI Reference — Experiments

Experiment lifecycle and run commands. See [Projects](16a-cli-projects.md) for the intro and project-management commands; see [Results and Reports](16c-cli-results.md), [Agents](16d-cli-agents.md), and [System](16e-cli-system.md) for the rest of the CLI surface.

## Experiments

### `urika experiment create`

Create a new experiment within a project.

```
urika experiment create [PROJECT] NAME [--hypothesis TEXT]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `NAME` | Experiment name (required) |

**Options:**

| Option | Description |
|--------|-------------|
| `--hypothesis TEXT` | Experiment hypothesis |

**Example:**

```bash
urika experiment create dht-targeting baseline-models \
  --hypothesis "Linear models provide a reasonable baseline"
```

Returns the generated experiment ID (e.g., `exp-001`).

---

### `urika experiment list`

List all experiments in a project with their status and run count.

```
urika experiment list [PROJECT]
```

**Example output:**

```
  exp-001  baseline-models  [completed, 5 runs]
  exp-002  feature-engineering  [completed, 4 runs]
```

---

### `urika experiment delete`

Move a single experiment to the project's local trash at `<project>/trash/`. The experiment directory is moved (not deleted) so artifacts are preserved. A manifest entry is written to `<project>/trash/.urika-trash-manifest.json` so you can identify it later.

This mirrors `urika delete` (which trashes a whole project to `~/.urika/trash/`) but operates on one experiment within a project.

```
urika experiment delete [PROJECT] EXP_ID [OPTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (defaults to the most recent project if omitted) |
| `EXP_ID` | Experiment ID to trash (e.g., `exp-003`) — required |

**Options:**

| Option | Description |
|--------|-------------|
| `-f`, `--force` | Skip the confirmation prompt. |
| `--json` | Emit the trash result as JSON (`project_name`, `experiment_id`, `original_path`, `trash_path`). |

**Behavior:**

- Refuses to trash an active experiment (one with a `.lock` file) — stop the run first.
- Empty the project's `trash/` folder manually when you're sure (e.g., `rm -rf <project>/trash/<exp_id>-*`).

**Examples:**

```bash
urika experiment delete my-study exp-003
urika experiment delete my-study exp-003 --force
urika experiment delete my-study exp-003 --json
```

---

### `urika run`

Run an experiment using the orchestrator. This is the main command that drives the agent loop: planning, task execution, evaluation, and advisor suggestions.

```
urika run [PROJECT] [OPTIONS]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--experiment ID` | Specific experiment ID to run (auto-selected if omitted) |
| `--max-turns N` | Maximum orchestrator turns (default: from `urika.toml`, or 5) |
| `--max-experiments N` | Run multiple experiments (autonomous mode — meta-orchestrator) |
| `--resume` | Resume a paused or failed experiment |
| `-q`, `--quiet` | Suppress verbose tool-use streaming output |
| `--auto` | Fully autonomous mode — no confirmation prompts |
| `--dry-run` | Print the planned pipeline (agents, tools, writable directories) without invoking any agent. Includes a cost estimate row using prior session costs as a basis. |
| `--instructions TEXT` | Guide the next experiment (e.g., "focus on tree-based models") |
| `--review-criteria` | Re-run the criteria-review subroutine so the advisor can evolve project criteria based on accumulated experiment results (may raise the bar). |
| `--budget FLOAT` | Pause the run when accumulated cost crosses this USD amount. Pause is at the next turn boundary; resumable via `--resume`. Default: no cap. |
| `--advisor-first` | Run the advisor first to propose a name + hypothesis + direction, then proceed. Meaningful when paired with `--experiment` (the dashboard's handoff). |
| `--legacy` | Use the deterministic Python orchestrator (default behaviour for now). |
| `--audience [novice\|standard\|expert]` | Control explanation depth in reports and presentations (default: from `urika.toml`'s `[preferences].audience`) |
| `--json` | Emit a JSON result envelope instead of the streaming-prose output. |

**Interactive settings:** When called with no flags, shows a settings dialog:

```
Proceed?
  1. Run with defaults
  2. Run multiple experiments (autonomous)
  3. Custom max turns
  4. Skip
```

This dialog is skipped when any flag is provided or when called from the TUI.

**Experiment selection logic** (when `--experiment` is not provided):
1. If there are pending (non-completed) experiments, resumes the most recent one
2. If all experiments are completed, calls the advisor agent to propose and create the next experiment
3. If no experiments exist and no initial plan is found, raises an error

**Examples:**

```bash
# Run with defaults (shows settings dialog)
urika run my-project

# Run multiple experiments
urika run my-project --max-experiments 5

# Run specific experiment with more turns
urika run my-project --experiment exp-002 --max-turns 10

# Fully autonomous with guidance
urika run my-project --auto --instructions "try ensemble methods"

# Resume after interruption
urika run my-project --resume
```

The `max_turns` default can be set in `urika.toml`:

```toml
[preferences]
max_turns_per_experiment = 5
```


## See also

- [CLI Reference — Projects](16a-cli-projects.md)
- [CLI Reference — Results and Reports](16c-cli-results.md)
- [CLI Reference — Agents](16d-cli-agents.md)
- [CLI Reference — System](16e-cli-system.md)
- [Configuration](14a-project-config.md)
- [Interactive TUI](17-interactive-tui.md)
- [Dashboard](18a-dashboard-pages.md)
