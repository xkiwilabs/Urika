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

#### `urika config anthropic|openai|google`

Set the auth mode for a cloud LLM provider. Writes `[<provider>] auth = "<mode>"` to `~/.urika/settings.toml`, preserving all other sections. `--mode` is required on the CLI (the REPL/TUI `/config <provider>` form shows the current mode instead — see [Interactive TUI](17-interactive-tui.md)).

```
urika config anthropic --mode <api_key|subscription> [--no-verify]
urika config openai --mode api_key
urika config google --mode api_key
```

| Provider | Accepted modes | Notes |
|----------|----------------|-------|
| `anthropic` | `api_key` (default), `subscription` | `subscription` prints a reminder to run `claude login`, then probes `claude --version` and warns on stderr if the CLI is missing (skip the probe with `--no-verify`; useful in bootstrap scripts). `api_key` prints a hint pointing at `urika config api-key`. |
| `openai` | `api_key` only | `--mode subscription` is rejected up-front with a usage error — ChatGPT Plus is a separate product from the API. Points you at `urika config secret` to store `OPENAI_API_KEY`. |
| `google` | `api_key` only | `--mode subscription` is rejected up-front — Google AI Pro/Ultra Terms of Service forbid third-party SDK use. Points you at `urika config secret` to store `GEMINI_API_KEY`. |

**Examples:**

```bash
urika config anthropic --mode subscription    # opt in to Pro/Max subscription auth
urika config anthropic --mode api_key         # back to the default API-key mode
urika config openai --mode api_key            # record OpenAI API-key mode
```

See [How Urika enforces this](20-security.md#how-urika-enforces-this) for what each Anthropic auth mode changes at runtime.


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

### `urika memory`

Read or edit the project memory directory at `<project>/memory/`. Project memory is structured markdown — a curated `MEMORY.md` index plus per-topic entry files (`feedback_*.md`, `instruction_*.md`, `decision_*.md`, …) — that gets injected into the planner's and advisor's system prompts on every run, so the agents stay aware of past decisions, user preferences, and constraints across experiments. Auto-capture from `<memory type="...">...</memory>` markers in agent output is on by default; manual edits live under this command group.

```
urika memory list    [PROJECT] [--json]
urika memory show    [PROJECT] TOPIC
urika memory add     [PROJECT] TOPIC [--type TYPE] [--from-file PATH | --stdin] [--description TEXT]
urika memory delete  [PROJECT] FILENAME [--force]
urika memory curate  [PROJECT] [--apply]
urika memory archive [PROJECT] [--month YYYY-MM] [--json]
urika memory diff    [PROJECT] FROM_TS TO_TS [--json]
```

**Subcommands:**

| Subcommand | Purpose |
|---|---|
| `list` | List every memory entry. `--json` emits structured output for scripts. |
| `show TOPIC` | Print one entry by filename or slug. Partial matches resolve via prefix glob (`feedback_methods` finds `feedback_methods.md` or `feedback_methods_v2.md`). |
| `add TOPIC` | Write a new entry. `--type` picks one of `user`, `feedback`, `instruction`, `decision`, `reference` (default: `instruction`). Body comes from `--from-file PATH`, `--stdin`, or an interactive editor. |
| `delete FILENAME` | Move the entry to `memory/.trash/` (preserved on disk). Pass `--force` to skip the confirmation prompt. |
| `curate` | Run the `memory_curator` agent over the project memory directory and print proposed merge / archive / flag decisions. **Defaults to dry-run** — re-run with `--apply` to commit the changes to disk. Used both manually and behind the once-per-session soft-cap auto-trigger that fires when memory grows past the configured budget (the auto-trigger is also dry-run by default). |
| `archive` | List archived memory entries (snapshots produced by `curate --apply`). Archives live under `<project>/memory/archive/<YYYY-MM>/`. With no flags, prints one line per entry grouped by month; `--month YYYY-MM` scopes the listing to a single month. `--json` emits the structured form. |
| `diff FROM_TS TO_TS` | mtime-based diff between two memory snapshots — shows which entries were `added`, `archived`, or `trashed` between two timestamps. Timestamps accept ISO 8601 (e.g. `2024-01-15T10:00:00+00:00`) or the relative forms `now`, `yesterday`, `1h ago`, `2d ago`, `1w ago`. Underscores work in place of spaces (`1h_ago`) so the REPL slash command can pass single-token arguments. `--json` for machine output. |

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

# Ask the curator to tidy things up — dry-run first
urika memory curate my-project
urika memory curate my-project --apply

# Browse last month's archived snapshots
urika memory archive my-project --month 2026-05

# What changed in the last week?
urika memory diff my-project "1w_ago" now
```

Soft cap 5 KB per entry (warning), hard cap 20 KB (truncated with marker). Per-project disable via `[memory] auto_capture = false` in `urika.toml`.

---

### `urika github`

Turn a project into a git repo and (optionally) auto-push it to a remote after every successful `urika run` / `finalize` / `build-tool`. Shipped in **v0.6.0**.

Urika never holds a GitHub credential — the commands shell out to the system `git` (and optionally `gh`) so your existing auth (HTTPS+PAT, SSH key, `gh auth login`) does all the work. Works against GitHub, GitLab, Gitea, Bitbucket, or self-hosted remotes.

```
urika github init   [PROJECT] [--remote URL] [--create] [--public]
urika github status [PROJECT]
urika github push   [PROJECT]
urika github pull   [PROJECT]
```

| Subcommand | Purpose |
|---|---|
| `init` | Initialise the project as a git repo, write the researcher-safe `.gitignore` managed block, optionally set `origin`, and create the first commit. Idempotent. With `--create`, uses `gh repo create --push` to provision a fresh private (default) or public (`--public`) GitHub repo in one shot. |
| `status` | Snapshot of branch, remote URL, dirty file count, last commit, and five most recent commits (with `urika-event:` chip per commit). |
| `push` | Stage everything, run the pre-commit secret scanner, commit (with `urika-event: manual` trailer), push to `origin`. Exits 3 if the scanner finds a known secret pattern (Anthropic, GitHub PAT/OAuth, AWS, OpenAI shapes). |
| `pull` | Fetch the current branch from `origin` and fast-forward-only merge. Refuses on divergence. |

The `[github] auto_push = true` opt-in hook in `urika.toml` runs the same scan → commit → push sequence at the tail of `urika run`, `urika finalize`, and `urika build-tool` (the default `auto_push_after` set). Wrapped in defensive `try/except` so auto-push failure can never break the host command.

See [GitHub Backup](22-github-backup.md) for the full guide — secret-scanner pattern list, `.gitignore` template, `urika new --github / --no-github / --public` flags at project-creation time, the `[preferences] github_auto_create` global default, the dashboard Git tab, and the `urika-event:` trailer format.

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
