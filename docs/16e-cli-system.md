# CLI Reference — System

Knowledge, environment, system, and configuration commands plus environment variables and global behaviors. See [Projects](16a-cli-projects.md) for the intro, [Experiments](16b-cli-experiments.md), [Results and Reports](16c-cli-results.md), and [Agents](16d-cli-agents.md) for the rest of the CLI surface.

## Knowledge

### `urika knowledge ingest`

Ingest a file or URL into the project's knowledge store. Supports PDF, text, and URL sources.

```
urika knowledge ingest [PROJECT] SOURCE
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `SOURCE` | Path to file or URL to ingest |

**Example:**

```bash
urika knowledge ingest my-project ~/papers/target-selection-review.pdf
```

---

### `urika knowledge search`

Search the knowledge store by keyword query.

```
urika knowledge search [PROJECT] QUERY
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |
| `QUERY` | Search query string |

---

### `urika knowledge list`

List all entries in the project's knowledge store.

```
urika knowledge list [PROJECT]
```


## Environment

### `urika venv create`

Create an isolated virtual environment for a project. The venv inherits shared base packages (numpy, pandas, scipy, etc.) via `--system-site-packages` so only project-specific packages are installed into it.

```
urika venv create [PROJECT]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |

**Example:**

```bash
urika venv create my-project
```

Creates `.venv/` inside the project directory. Agents will install packages into this venv instead of the global environment.

---

### `urika venv status`

Show the virtual environment status for a project: whether a venv exists, its path, and installed packages.

```
urika venv status [PROJECT]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Project name (prompted if omitted) |

**Example output:**

```
Project: my-project
Venv: /home/user/urika-projects/my-project/.venv
Status: active
Packages: 47 installed (12 project-specific)
```


### `urika config`

Configure privacy mode, models, and endpoints. Works globally or per-project.

```
urika config [PROJECT] [--show] [--json]
```

**Without PROJECT:** Configures global defaults in `~/.urika/settings.toml` (used for new projects).

**With PROJECT:** Configures that project's `urika.toml`.

**Interactive setup** guides you through:

- **Privacy mode** — open, private, or hybrid
- **Open:** Choose a cloud model (Sonnet, Opus, Haiku) for all agents
- **Private:** Configure endpoint (Ollama, LM Studio, or custom server) and model for all agents
- **Hybrid:** Choose cloud model for most agents + private endpoint and model for the data agent

**Warnings:** Switching from private/hybrid to a less private mode triggers a confirmation prompt.

**Privacy mode rules:**

| Mode | data_agent | Other agents |
|------|-----------|-------------|
| **open** | Cloud only | Cloud only (different models allowed per agent) |
| **private** | Private only | Private only (different endpoints/models allowed) |
| **hybrid** | Must be private | Cloud or private (user's choice per agent) |

**Examples:**

```bash
urika config                     # interactive global setup
urika config --show              # show global defaults
urika config my-project          # reconfigure a project
urika config my-project --show   # show project settings
```

For per-agent model overrides beyond what the interactive setup provides, edit `urika.toml` directly — see [Configuration](14a-project-config.md).

#### `urika config api-key`

Interactive setup for the Anthropic API key. Saves to `~/.urika/secrets.env` (mode `0600`); the key is loaded into `os.environ["ANTHROPIC_API_KEY"]` on every subsequent CLI invocation.

```
urika config api-key [--test]
```

| Option | Description |
|--------|-------------|
| `--test` | After saving, verify the key by making a real call to `api.anthropic.com`. Reports success/failure with the response body excerpt on error. |

**Examples:**

```bash
urika config api-key             # interactive prompt, saves to vault
urika config api-key --test      # save + verify
```

The same vault is used by every Urika surface (CLI, TUI, dashboard). To set a key per shell instead, export `ANTHROPIC_API_KEY` directly — process-env always wins over the vault.

#### `urika config secret`

Interactive setup for an arbitrary named secret (e.g., a private vLLM API token, a HuggingFace key, a third-party API credential). Saves to the same global secrets vault as `urika config api-key`. Agents and tools read the secret via `os.environ.get(NAME)`.

```
urika config secret
```

The wizard prompts for the secret name (defaults to a curated allowlist of well-known names from `urika.core.known_secrets` if you don't type one), value, and description. Mask preview shown on save.

**Examples:**

```bash
urika config secret              # interactive — pick from known names
urika config secret              # interactive — enter a custom name
```

Names referenced by `[privacy.endpoints.<n>].api_key_env` are auto-discovered and offered as suggestions.


### `urika notifications`

Configure notification channels (Email, Slack, Telegram). Credentials are saved to `~/.urika/secrets.env`. Channel settings live in `~/.urika/settings.toml` (global) or `<project>/urika.toml` (per-project). With no options, launches an interactive setup wizard.

```
urika notifications [OPTIONS]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--show` | Print the current notification configuration (channels, masked credentials, status). |
| `--test` | Send a test notification through every enabled channel. With `--project`, uses the merged project + global config. |
| `--disable` | Disable notifications for the project (project-level only — pair with `--project`). |
| `--project NAME` | Switch to per-project setup: pick channels (allow-list), add extra recipients, override the Telegram chat ID. |

**Behavior:**

- **Global setup** (no `--project`): configure channel-level credentials and `auto_enable` flags for new projects.
- **Project setup** (`--project NAME`): enable/disable individual channels for that project and add per-project overrides on top of the global config.

**Examples:**

```bash
urika notifications                          # interactive global setup
urika notifications --show                   # show current global config
urika notifications --test                   # send a test on every enabled channel
urika notifications --project my-study       # per-project channel allow-list
urika notifications --project my-study --disable
```

See [Notifications](19a-notifications-channels.md) for the full feature guide, including event types, priority levels, and Slack interactive buttons.


## System

### `urika setup`

Check installation status and optionally install missing packages. Useful after first install or when upgrading.

```
urika setup
```

**What it does:**

1. **Package check** -- Shows installed vs missing packages for each category: core, visualization, ML, deep learning, and knowledge pipeline.
2. **Hardware detection** -- Reports CPU cores, available RAM, and GPU presence (NVIDIA via `nvidia-smi`).
3. **Deep learning install** -- If DL packages are missing, offers to install them. Detects whether you have an NVIDIA GPU and chooses the appropriate CPU or CUDA variant automatically.
4. **API key check** -- Verifies that `ANTHROPIC_API_KEY` is set in the environment.

**Example output:**

```
Core packages:        all installed
Visualization:        all installed
Machine learning:     all installed
Knowledge pipeline:   all installed
Deep learning:        not installed

Hardware:
  CPU: 8 cores
  RAM: 32 GB
  GPU: NVIDIA RTX 4090 (24 GB VRAM)

ANTHROPIC_API_KEY: set

Install deep learning packages? [Y/n]
  Detected NVIDIA GPU -- installing CUDA variant...
```

---

### `urika tools`

List all available analysis tools (built-in and project-specific).

```
urika tools [--category CATEGORY] [--project NAME]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--category TEXT` | Filter tools by category |
| `--project NAME` | Include project-specific tools |

**Example output:**

```
  correlation_analysis  [exploration]       Compute correlation matrices
  cross_validation      [preprocessing]     K-fold cross-validation
  linear_regression     [regression]        Fit linear regression models
  visualization         [exploration]       Generate plots and figures
  ...
```

---

### `urika tui`

Explicitly launch the interactive Urika TUI. Equivalent to running bare `urika` with no subcommand, but discoverable via `urika --help` and easy to invoke from scripts.

```
urika tui [PROJECT]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `PROJECT` | Optional project name to auto-load on launch. If omitted, the TUI starts without a project loaded. |

**Examples:**

```bash
urika tui                 # launch the TUI (no project loaded)
urika tui my-study        # launch and auto-load my-study
```

The TUI binary is searched in the following order: the `URIKA_TUI_BIN` environment variable, the system `PATH` (`urika-tui`), the local dev build (`packages/urika-tui/dist/urika-tui`), or run via `bun` from `packages/urika-tui/src/index.ts` if available. See [Interactive TUI](17-interactive-tui.md) for usage.

---

### `urika memory`

Read or edit the project memory directory at `<project>/memory/`. Project memory is structured markdown — a curated `MEMORY.md` index plus per-topic entry files (`feedback_*.md`, `instruction_*.md`, `decision_*.md`, …) — that gets injected into the planner's and advisor's system prompts on every run, so the agents stay aware of past decisions, user preferences, and constraints across experiments. Auto-capture from `<memory type="...">...</memory>` markers in agent output is on by default; manual edits live under this command group.

```
urika memory list   [PROJECT] [--json]
urika memory show   [PROJECT] TOPIC
urika memory add    [PROJECT] TOPIC [--type TYPE] [--from-file PATH | --stdin] [--description TEXT]
urika memory delete [PROJECT] FILENAME [--force]
```

**Subcommands:**

| Subcommand | Purpose |
|---|---|
| `list` | List every memory entry. `--json` emits structured output for scripts. |
| `show TOPIC` | Print one entry by filename or slug. Partial matches resolve via prefix glob (`feedback_methods` finds `feedback_methods.md` or `feedback_methods_v2.md`). |
| `add TOPIC` | Write a new entry. `--type` picks one of `user`, `feedback`, `instruction`, `decision`, `reference` (default: `instruction`). Body comes from `--from-file PATH`, `--stdin`, or an interactive editor. |
| `delete FILENAME` | Move the entry to `memory/.trash/` (preserved on disk). Pass `--force` to skip the confirmation prompt. |

**Examples:**

```bash
# Inspect what the agents are seeing
urika memory list my-project

# Capture a methodological constraint from a piped command
echo "Always cross-validate by subject" | urika memory add my-project cv_strategy --stdin

# Read one entry
urika memory show my-project feedback_methods

# Trash an outdated entry
urika memory delete my-project instruction_old_baseline.md --force
```

Soft cap 5 KB per entry (warning), hard cap 20 KB (truncated with marker). Per-project disable via `[memory] auto_capture = false` in `urika.toml`.

---

### `urika sessions`

List or export persisted orchestrator chat sessions. The TUI's orchestrator chat persists each conversation to `<project>/.urika/sessions/<id>.json` (auto-pruned at 20 sessions). This command surfaces them outside the TUI for sharing or scripted review.

```
urika sessions list   [PROJECT] [--json]
urika sessions export [PROJECT] SESSION_ID [--format md|json] [-o FILE]
```

**Subcommands:**

| Subcommand | Purpose |
|---|---|
| `list` | One row per session: ID, started timestamp, message count, preview of first user message. `--json` emits the full structure. |
| `export SESSION_ID` | Render a session to Markdown (`--format md`, default — sharing) or JSON (`--format json`, full fidelity). Output goes to stdout unless `-o FILE` is provided. |

**Examples:**

```bash
# What conversations does this project have?
urika sessions list my-project

# Share a session as a Markdown gist
urika sessions export my-project 20260501-143022-a4b -o session.md

# Full-fidelity dump for a downstream tool
urika sessions export my-project 20260501-143022-a4b --format json
```

---

### `urika completion`

Manage shell completion for the `urika` CLI. Built on Click 8's native completion machinery — works in bash, zsh, and fish.

```
urika completion install    [SHELL] [--force]
urika completion script     [SHELL]
urika completion uninstall  [SHELL]
```

**Subcommands:**

| Subcommand | Purpose |
|---|---|
| `install` | Generate the completion script and append a sourcing line to your shell's rc file. `--force` overwrites an existing entry. Auto-detects bash / zsh / fish from `$SHELL` if `SHELL` argument is omitted. |
| `script` | Print the completion script to stdout — useful when you want to manage sourcing yourself or place the script in a non-default location. |
| `uninstall` | Remove the sourcing line from your shell's rc file. The completion script file itself is left in place. |

**Examples:**

```bash
# One-liner: install + source on next shell
urika completion install
exec $SHELL -l

# Manual: stash the script wherever you keep your completions
urika completion script bash > ~/.bash_completions/urika.bash
echo 'source ~/.bash_completions/urika.bash' >> ~/.bashrc
```

After installing, `urika <TAB><TAB>` shows the command list, project names complete on `urika status <TAB>`, and so on.

---

### `urika --version`

Show the installed Urika version.

```
urika --version
```


## Environment Variables

| Variable | Description |
|----------|-------------|
| `URIKA_PROJECTS_DIR` | Override the default projects directory (default: `~/urika-projects`) |
| `URIKA_HOME` | Override the global config directory (default: `~/.urika`). Also relocates `~/.urika/secrets.env` and the project registry. |
| `URIKA_TUI_BIN` | Explicit path to the TypeScript TUI binary launched by `urika tui` (overrides PATH search). |
| `URIKA_NO_BUILDER_AGENT` | Set to `1` to skip the project-builder agent loop in `urika new` (for scripted use). The agent loop is also auto-skipped under non-TTY stdin. |
| `URIKA_DASHBOARD_AUTH_TOKEN` | Bearer-token gate for `urika dashboard` (matches the `--auth-token` flag). |
| `ANTHROPIC_API_KEY` | API key for Anthropic-routed agent calls. Required for any cloud-bound run; see [Security → Provider compliance](20-security.md#provider-compliance). |
| `ANTHROPIC_BASE_URL` | Custom OpenAI-compatible endpoint URL (set per-agent via `urika config secret`, not exported manually for global config). |
| `INFERENCE_HUB_KEY` (or whichever name is referenced by your endpoint's `api_key_env`) | Auth token for a configured private endpoint. Loaded from `~/.urika/secrets.env` automatically; only needed manually when shelling out. |
| `NO_COLOR` | Set to disable coloured terminal output (colours are on by default for TTYs). |


## Global Behaviors

- **Project argument**: Most commands accept an optional `PROJECT` argument. If omitted and only one project exists, it is used automatically. If multiple projects exist, you are prompted to select one.
- **Versioned files**: Reports, presentations, and other generated files use versioned writing -- previous versions are backed up with timestamps before overwriting.
- **Ctrl+C handling**: During `urika run`, pressing Ctrl+C cleanly pauses the experiment and removes the lock file. Resume with `urika run --resume`.

---

**Next:** [Interactive TUI](17-interactive-tui.md)


## See also

- [CLI Reference — Projects](16a-cli-projects.md)
- [CLI Reference — Experiments](16b-cli-experiments.md)
- [CLI Reference — Results and Reports](16c-cli-results.md)
- [CLI Reference — Agents](16d-cli-agents.md)
- [Configuration](14a-project-config.md)
- [Interactive TUI](17-interactive-tui.md)
- [Dashboard](18a-dashboard-pages.md)
