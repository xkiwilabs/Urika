# CLI Reference — Projects

Project lifecycle commands. See [Experiments](16b-cli-experiments.md), [Results and Reports](16c-cli-results.md), [Agents](16d-cli-agents.md), and [System](16e-cli-system.md) for the rest of the CLI surface.

Complete reference for all Urika CLI commands. Run `urika --help` for a summary, or `urika <command> --help` for any individual command.

Running `urika` with no subcommand launches the interactive TUI (see [Interactive TUI](17-interactive-tui.md)). Use `urika --classic` for the classic prompt-toolkit REPL.


## Scriptable by Design

Every command is fully scriptable. When you provide arguments and flags, no interactive prompts are shown -- commands run non-interactively and exit. Add `--json` to any read command for structured output that can be piped to `jq`, parsed in Python, or fed into other tools.

```bash
# Non-interactive: all args on the command line
urika run my-study --max-turns 5 --instructions "try ensemble methods" --auto

# JSON output for custom tooling
urika status my-study --json | jq '.experiments'
urika results my-study --json | python3 process_results.py

# Batch script example
for project in study-a study-b study-c; do
  urika run "$project" --max-experiments 3 --auto
  urika finalize "$project"
done
```

This makes Urika suitable for automated pipelines, batch processing, CI/CD integration, and building custom research tools on top of the platform.


## Project Management

### `urika new`

Create a new project. Launches an interactive flow: scan data, profile columns, ask clarifying questions via the project builder agent, generate initial experiment suggestions via the advisor agent, and write the project structure.

```
urika new [NAME] [OPTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `NAME` | Project name (prompted if omitted) |

**Options:**

| Option | Description |
|--------|-------------|
| `-q`, `--question TEXT` | Research question |
| `-m`, `--mode [exploratory\|confirmatory\|pipeline]` | Investigation mode |
| `--data PATH` | Path to data file or directory |
| `--description TEXT` | Project description |

All options are prompted interactively if not provided on the command line.

**Example:**

```bash
urika new dht-targeting \
  --data ~/data/dht_scores.csv \
  --question "Which factors predict DHT target selection?" \
  --mode exploratory
```

After project creation, Urika offers to run the first suggested experiment immediately.

---

### `urika list`

List all registered projects.

```
urika list [--prune]
```

```
  my-project    /home/user/urika-projects/my-project
  dht-analysis  /home/user/urika-projects/dht-analysis
```

Projects marked with `?` have a missing directory on disk.

**Options:**

| Option | Description |
|--------|-------------|
| `--prune` | Silently unregister any entries whose folder no longer exists, then print the cleaned list. Useful after manually deleting project directories outside Urika. |

---

### `urika delete`

Move a project to `~/.urika/trash/<name>-<YYYYMMDD-HHMMSS>/` and remove it from the registry. The folder is moved, not deleted, so artifacts are preserved. Empty the trash manually when you're sure (`rm -rf ~/.urika/trash/...`).

```
urika delete NAME [--force] [--json]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--force` / `-f` | Skip the confirmation prompt. |
| `--json` | Emit the trash result as JSON (`name`, `original_path`, `trash_path`, `registry_only`). |

**Behavior:**

- Refuses to trash if a `.lock` file exists anywhere under the project (active run / finalize / evaluate). Stop the run first.
- If the project's folder is already missing on disk, only the registry entry is removed (no second prompt) and the message reflects that.
- A manifest (`.urika-trash-manifest.json`) is written into the trash directory so you can identify it later.
- Each operation appends one JSON line to `~/.urika/deletion-log.jsonl`.

**Example:**

```
$ urika delete my-old-project
Move project 'my-old-project' to ~/.urika/trash/? (files preserved, registry entry removed) [y/N]: y
Moved 'my-old-project' to /home/user/.urika/trash/my-old-project-20260426-153012
```

---

### `urika status`

Show project status including research question, mode, experiment count, per-experiment status, and **data drift** — a SHA-256 hash of every registered data file is captured at `urika new` time and re-checked here. Files whose hash has changed are flagged so you don't accidentally compare runs against drifted data.

```
urika status [NAME] [--json]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `NAME` | Project name (prompted if multiple projects exist) |

**Options:**

| Option | Description |
|--------|-------------|
| `--json` | Emit a JSON envelope with `experiments`, `data_drift`, and `path` fields for scripted callers. Used by the dashboard's project-home page. |

**Example output:**

```
Project: dht-targeting
Question: Which factors predict DHT target selection?
Mode: exploratory
Path: /home/user/urika-projects/dht-targeting
Experiments: 3

  exp-001: baseline-models [completed, 5 runs]
  exp-002: feature-engineering [completed, 4 runs]
  exp-003: ensemble-methods [running, 2 runs]

Data drift:
  ⚠ data/training.csv  hash changed since 2026-04-12 (registered: a3f1…  current: c40b…)
```

The original hashes live in `urika.toml` under `[project.data_hashes]` and are re-computed on every `urika status` and `urika new`. To silence a drift warning after intentionally updating a dataset, run `urika update <project>` and accept the new hashes.

---

### `urika inspect`

Inspect project data: column schema, data types, missing values, and a preview of the first 5 rows.

```
urika inspect [PROJECT] [--data FILE]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--data FILE` | Specific data file to inspect (defaults to first CSV in `data/`) |

**Example output:**

```
Dataset: scores.csv
Rows: 1247
Columns: 18

Schema:
  target_id                      int64
  fov_distance                   float64
  brightness                     float64         (2.1% missing)
  ...

Preview (first 5 rows):
 target_id  fov_distance  brightness  ...
```


### `urika update`

Update a project's description, research question, or mode. Changes are versioned -- previous values are preserved with timestamps in `revisions.json`.

```
urika update [PROJECT] [OPTIONS]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--field [description\|question\|mode]` | Field to update (prompted interactively if omitted) |
| `--value TEXT` | New value (prompted if omitted) |
| `--reason TEXT` | Why this change was made (prompted if omitted) |
| `--history` | Show revision history instead of updating |

When called with no `--field`, shows the current config and prompts you to choose which field to update, enter a new value, and optionally record a reason.

**Examples:**

```bash
# Interactive update (prompts for field, value, reason)
urika update my-study

# Direct update with all options
urika update my-study --field question --value "Does X predict Y?"

# Update with a reason
urika update my-study --field description --reason "Added new variables"

# View revision history
urika update my-study --history
```

**Example history output:**

```
  Revision history for my-study:

  #1  2026-03-20 14:32  [question]
    Old: Which factors predict target selection?
    New: Does X predict Y?
    Why: Refined after initial exploration
```


## See also

- [CLI Reference — Experiments](16b-cli-experiments.md)
- [CLI Reference — Results and Reports](16c-cli-results.md)
- [CLI Reference — Agents](16d-cli-agents.md)
- [CLI Reference — System](16e-cli-system.md)
- [Configuration](14a-project-config.md)
- [Interactive TUI](17-interactive-tui.md)
- [Dashboard](18a-dashboard-pages.md)
