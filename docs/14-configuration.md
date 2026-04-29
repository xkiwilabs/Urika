# Configuration

Urika projects are configured through a combination of files in the project directory and environment variables. This page covers all configuration surfaces.


## urika.toml

The primary project configuration file, created during `urika new`. Lives at the root of every project directory.

### [project] section

```toml
[project]
name = "dht-target-selection"
question = "Which features best predict DHT target selection accuracy?"
mode = "exploratory"
description = "Modelling target selection performance from participant and task features"
data_paths = ["/home/user/data/participants.csv"]
```

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `name` | string | yes | Project identifier, used in the registry and CLI |
| `question` | string | yes | The research question agents are trying to answer |
| `mode` | string | yes | One of `"exploratory"`, `"confirmatory"`, or `"pipeline"` |
| `description` | string | no | Longer description of the project goals |
| `data_paths` | list of strings | no | Paths to the dataset files |
| `success_criteria` | table | no | Initial success criteria (typically set by project_builder) |

**Modes:**

- **exploratory** -- agents freely explore methods and features to understand the data
- **confirmatory** -- agents test specific pre-registered hypotheses
- **pipeline** -- agents build a production-ready analytical pipeline

### [preferences] section

Optional section for controlling experiment behavior:

```toml
[preferences]
max_turns_per_experiment = 5
auto_mode = "checkpoint"
presentation_theme = "light"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_turns_per_experiment` | integer | `5` | Maximum orchestrator turns per experiment run |
| `auto_mode` | string | `"checkpoint"` | How the TUI runs experiments: `"checkpoint"` (pause for confirmation), `"unlimited"` (run all turns), or `"capped"` (run up to max turns) |
| `presentation_theme` | string | `"light"` | Reveal.js theme for generated presentations |

These preferences can be overridden at runtime via CLI flags or TUI prompts.

### [runtime] and [privacy] sections

The `[runtime]` section controls which AI model each agent uses, with a project-wide default and per-agent overrides. The `[privacy]` section defines named endpoints (open, private, trusted) and sets the privacy mode (`open`, `private`, or `hybrid`).

Use `urika config` for interactive setup, or `urika config my-project` to reconfigure an existing project. For advanced per-agent model assignment, edit `urika.toml` directly:

```toml
# Default model for all agents
[runtime]
model = "claude-sonnet-4-5"

# Override specific agents with different models
[runtime.models.task_agent]
model = "claude-opus-4-6"
endpoint = "open"

[runtime.models.evaluator]
model = "claude-haiku-4-5"
endpoint = "open"

# In hybrid mode: data_agent must use a private endpoint
[runtime.models.data_agent]
model = "qwen3:14b"
endpoint = "private"

# tool_builder uses cloud by default in hybrid (doesn't touch raw data)
# override if needed:
# [runtime.models.tool_builder]
# model = "qwen3:14b"
# endpoint = "private"
```

**Privacy mode rules:**

| Mode | data_agent | Other agents | Mixing allowed? |
|------|-----------|-------------|----------------|
| **open** | Cloud only | Cloud only | Different cloud models per agent |
| **private** | Private only | Private only | Different private endpoints/models per agent |
| **hybrid** | **Must be private** (reads raw data) | Cloud or private | Full mix per agent |

See [Models and Privacy](13-models-and-privacy.md) for endpoint configuration details.

### [environment] section

Controls whether the project uses an isolated Python virtual environment:

```toml
[environment]
venv = true    # false = use global environment (default), true = per-project venv
```

When enabled, a `.venv/` directory is created inside the project with `--system-site-packages`, inheriting the global base packages. Agents install project-specific packages into this venv. See [Creating Projects](04-creating-projects.md#isolated-environments) for details.


## Audience Mode

Control the level of explanation in reports and presentations:

```toml
[preferences]
audience = "standard"    # or "novice", "expert"
```

- **standard** (default) — Verbose speaker notes for presentations and balanced explanation depth in reports. Sits between expert (terse, assumes domain expertise) and novice (full plain-English walkthrough). Targets a senior undergraduate or early Masters/PhD student who has heard of common methods but doesn't know their specifics.
- **novice** — Explains every method in plain language. Adds "What this means" explainer slides before results, defines technical terms on first use, and walks through results step by step. Presentations include extra slides explaining approaches conceptually.
- **expert** — Concise; assumes domain expertise; uses technical terminology freely. Use when writing for a paper-review audience.

Override per-command with `--audience`:

```bash
urika report --audience novice
urika present --audience novice
urika run --audience novice
urika finalize --audience novice
```


## criteria.json

Versioned criteria that define what "good enough" looks like for the project. Criteria evolve over the course of experimentation as agents learn more about the data and problem.

### Structure

```json
{
  "versions": [
    {
      "version": 1,
      "set_by": "project_builder",
      "turn": 0,
      "rationale": "Initial criteria based on exploratory analysis goals",
      "criteria": {
        "method_validity": "Method must be appropriate for the data type",
        "parameter_adequacy": "Hyperparameters must be justified",
        "quality": "R2 > 0.3 for regression tasks",
        "completeness": "Must report train and test metrics"
      }
    },
    {
      "version": 2,
      "set_by": "advisor_agent",
      "turn": 8,
      "rationale": "Raising bar after baseline models exceeded initial threshold",
      "criteria": {
        "method_validity": "Method must be appropriate for the data type",
        "parameter_adequacy": "Hyperparameters must be tuned via cross-validation",
        "quality": "R2 > 0.5 with cross-validated estimate",
        "completeness": "Must report train, validation, and test metrics",
        "threshold": "Improvement over best baseline by at least 5%",
        "comparative": "Must compare against at least 2 previous methods"
      }
    }
  ]
}
```

### CriteriaVersion fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | integer | Sequential version number (1, 2, 3, ...) |
| `set_by` | string | Agent that set this version (`"project_builder"`, `"advisor_agent"`) |
| `turn` | integer | Orchestrator turn when criteria were updated |
| `rationale` | string | Why the criteria changed |
| `criteria` | dict | Named criteria with descriptions or thresholds |

### Criteria types

Criteria are freeform key-value pairs, but commonly include:

| Key | Purpose |
|-----|---------|
| `method_validity` | Is the analytical method appropriate for this data and question? |
| `parameter_adequacy` | Are hyperparameters and settings properly justified or tuned? |
| `quality` | Numeric performance thresholds (e.g., R2, accuracy, RMSE) |
| `completeness` | What must be reported (metrics, splits, confidence intervals) |
| `threshold` | Minimum improvement over previous best |
| `comparative` | Requirements for comparing against baselines |

### How criteria evolve

1. The **project_builder** sets initial criteria during `urika new`, based on the research question and data profile
2. The **evaluator** scores each run against the current criteria
3. The **advisor_agent** can update criteria between experiments -- typically raising the bar after initial baselines are established
4. All versions are preserved, creating an audit trail of how standards evolved

### Viewing criteria

```bash
urika criteria <project>
```

Shows the current criteria version and its history.

### API

```python
from urika.core.criteria import load_criteria, load_criteria_history, append_criteria

# Get current (latest) criteria
current = load_criteria(project_dir)  # Returns CriteriaVersion or None

# Get full history
history = load_criteria_history(project_dir)  # Returns list[CriteriaVersion]

# Add a new version
append_criteria(
    project_dir,
    criteria={"quality": "R2 > 0.6"},
    set_by="advisor_agent",
    turn=12,
    rationale="Previous threshold exceeded consistently",
)
```


## methods.json

Tracks all analytical methods created by agents during experiments. Located at the project root.

```json
{
  "methods": [
    {
      "name": "baseline_linear",
      "description": "OLS linear regression with all numeric features",
      "script": "methods/baseline_linear.py",
      "created_by": "task_agent",
      "experiment": "exp-001-baseline-models",
      "turn": 2,
      "metrics": {"r2": 0.42, "rmse": 1.23},
      "status": "active",
      "superseded_by": null
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `name` | Unique method identifier |
| `description` | What the method does |
| `script` | Path to the Python script (relative to project root) |
| `created_by` | Always `"task_agent"` |
| `experiment` | Experiment ID where this method was created |
| `turn` | Orchestrator turn number |
| `metrics` | Best metrics achieved by this method |
| `status` | `"active"` or `"superseded"` |
| `superseded_by` | Name of the method that replaced this one (if superseded) |

View registered methods with:

```bash
urika methods <project>
```


## usage.json

Tracks session-level resource usage per project. Updated automatically after each experiment run.

```json
{
  "sessions": [
    {
      "started": "2026-03-15T10:00:00+00:00",
      "ended": "2026-03-15T10:12:30+00:00",
      "duration_ms": 750000,
      "tokens_in": 45000,
      "tokens_out": 12000,
      "cost_usd": 0.315,
      "agent_calls": 18,
      "experiments_run": 1
    }
  ],
  "totals": {
    "sessions": 1,
    "total_duration_ms": 750000,
    "total_tokens_in": 45000,
    "total_tokens_out": 12000,
    "total_cost_usd": 0.315,
    "total_agent_calls": 18,
    "total_experiments": 1
  }
}
```

View usage with:

```bash
urika usage <project>
```

Cost estimates use Claude API pricing (Sonnet by default; adjusts for Opus and Haiku).


## Global configuration files

The files described above (`urika.toml`, `criteria.json`, `methods.json`, `usage.json`) are *per-project* — each one lives at the root of one project directory. Urika also keeps two *global* (user-level) files under `~/.urika/`. These hold settings that apply across every project: shared LLM endpoints, default preferences, notification channel definitions, and credentials.

The user-level config directory is `~/.urika/` by default, or whatever `URIKA_HOME` points to (see [Environment Variables](#environment-variables)). A project's `urika.toml` always wins over global defaults — globals only fill in fields the project hasn't set.

### `~/.urika/settings.toml`

User-level configuration. Edited interactively via `urika config` (no project argument), the dashboard's Settings page, or by hand. It is plain TOML and committed to nothing — the file lives outside any project tree.

```toml
[privacy.endpoints.open]
base_url = "https://api.anthropic.com"
api_key_env = "ANTHROPIC_API_KEY"
default_model = "claude-opus-4-7"

[privacy.endpoints.private]
base_url = "http://localhost:11434"
api_key_env = ""                      # local Ollama needs no key
default_model = "qwen3:14b"

[privacy.endpoints.trusted]           # arbitrary additional endpoints
base_url = "https://inference.example.org/v1"
api_key_env = "INFERENCE_HUB_KEY"
default_model = "llama3.1:70b"

[runtime.modes.open]
model = "claude-opus-4-7"

[runtime.modes.private]
model = "qwen3:14b"

[runtime.modes.hybrid]
model = "claude-opus-4-7"

[runtime.modes.hybrid.models.data_agent]
model = "qwen3:14b"
endpoint = "private"

[preferences]
default_audience = "standard"
max_turns_per_experiment = 10
auto_mode = "checkpoint"
venv = true

[notifications.email]
from_addr = "bot@example.com"
to = ["alice@example.com"]
smtp_server = "smtp.gmail.com"
smtp_port = 587
username = "bot@example.com"          # optional, defaults to from_addr
password_env = "URIKA_EMAIL_PASSWORD" # NAME of env var holding the password
auto_enable = true                    # auto-enable on new projects

[notifications.slack]
channel = "#urika-runs"
bot_token_env = "SLACK_BOT_TOKEN"
app_token_env = "SLACK_APP_TOKEN"     # optional, for inbound Socket Mode
allowed_channels = ["#urika-runs"]    # optional inbound allowlist
allowed_users = ["U01ABC234"]         # optional inbound user allowlist
auto_enable = true

[notifications.telegram]
chat_id = "8667664079"
bot_token_env = "TELEGRAM_BOT_TOKEN"
auto_enable = true
```

What each top-level table does:

| Table | Purpose |
|-------|---------|
| `[privacy.endpoints.<name>]` | Named LLM endpoints reusable across projects. `base_url` is required; `api_key_env` and `default_model` are optional. The endpoint name (`open`, `private`, `trusted`, or anything else) is what `[runtime.modes.<mode>.models.<agent>].endpoint` refers to. |
| `[runtime.modes.<mode>]` | Default model for each privacy mode (`open`, `private`, `hybrid`). New projects in this mode inherit the `model` field unless overridden. |
| `[runtime.modes.<mode>.models.<agent>]` | Per-agent model + endpoint defaults that apply only when a project is in this mode. The classic example is `[runtime.modes.hybrid.models.data_agent]` pinning the data agent to a private endpoint. |
| `[preferences]` | Default values for new projects: `default_audience`, `max_turns_per_experiment`, `auto_mode`, `venv`, etc. Each project's own `[preferences]` block overrides these. |
| `[notifications.<channel>]` | Channel definition for `email`, `slack`, and `telegram`. Servers, addresses, channel IDs, and the *names* of env vars holding credentials. `auto_enable` is a creation-time hint: when true, new projects start with this channel listed in their `notifications.channels`. |

**Important: the env-var-name indirection.** Notification channels never hold raw passwords or tokens in `settings.toml`. Instead they store the *name* of an environment variable — fields like `password_env`, `bot_token_env`, `app_token_env`, `api_key_env`. At runtime, the channel reads `os.environ[<name>]` to get the actual secret. The actual values live in [`~/.urika/secrets.env`](#urikasecrets-env) (or the user's shell environment). This way `settings.toml` is safe to copy between machines, paste into a bug report, or share with a collaborator; only `secrets.env` is sensitive.

See [Notifications](19-notifications.md) for a deeper walkthrough of the channel configuration and the per-project `urika.toml` overrides that select which channels each project uses.

### `~/.urika/secrets.env`

A user-level credential store. The file is a plain `KEY=VALUE` text file with comments allowed; it is created by `urika config notifications`, `urika config api-key`, or `save_secret` from Python at permissions `0600` (owner read/write only). Don't commit it.

> **`ANTHROPIC_API_KEY` is required.** Urika uses the Claude Agent SDK,
> which under Anthropic's Consumer Terms (§3.7) and the April 2026
> Agent SDK clarification cannot be authenticated via a Claude Pro/Max
> subscription. Set `ANTHROPIC_API_KEY` in `~/.urika/secrets.env`,
> export it in your shell, or run `urika config api-key` for an
> interactive setup. See [Security § Provider compliance](20-security.md#provider-compliance)
> for the full rationale.

```env
# Anthropic / model providers
ANTHROPIC_API_KEY=sk-ant-...

# Notification credentials referenced by name from settings.toml
URIKA_EMAIL_PASSWORD=abcd-efgh-ijkl-mnop
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
TELEGRAM_BOT_TOKEN=123456789:ABC...
```

**Loading.** `urika.core.secrets.load_secrets()` runs at the start of every CLI invocation. It walks the file line by line and sets `os.environ[KEY] = VALUE` *only if the key is not already in the environment*. Anything you `export` from your shell — or anything inherited from your service manager — takes precedence.

**The indirection pattern, end to end.** `settings.toml` records `password_env = "URIKA_EMAIL_PASSWORD"` and `secrets.env` records `URIKA_EMAIL_PASSWORD=actual-app-password`. When the email channel runs, it reads the env-var *name* from settings, then reads the *value* from `os.environ` (populated from `secrets.env` at startup). The two files are kept apart on purpose: configuration is shareable; credentials are not.

For the trust model behind this split — including how it interacts with agent-generated code and dashboard auth — see [Security Model](20-security.md#secrets).

### Per-project state files

Each project also maintains its own state files at the project root. Most are documented above (`urika.toml`, `criteria.json`, `methods.json`, `usage.json`). For completeness, the full set:

| File | Scope | Owner | Notes |
|------|-------|-------|-------|
| `urika.toml` | Project root | User / project_builder | Configuration. Documented above. |
| `criteria.json` | Project root | project_builder, advisor_agent | Versioned success criteria. Documented above. |
| `methods.json` | Project root | task_agent | Method registry. Documented above. |
| `usage.json` | Project root | Orchestrator | Token + cost totals. Documented above. |
| `revisions.json` | Project root | `urika update` | Audit trail of project edits made through the update command. |
| `experiments/<id>/progress.json` | Per experiment | task_agent, evaluator | Append-only run log. |
| `experiments/<id>/session.json` | Per experiment | Orchestrator | Turn-by-turn experiment state. |
| `.urika/sessions/<id>.json` | Per project | Orchestrator chat | Conversational session memory for the TUI / `urika chat`. |

For the full directory layout, including `experiments/`, `methods/`, `tools/`, `knowledge/`, and `projectbook/`, see [Project Structure](15-project-structure.md).


## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (none) | Claude API key. **Required** for any cloud-touching Urika command — Anthropic's Consumer Terms §3.7 and the April 2026 Agent SDK clarification prohibit using a Pro/Max subscription to authenticate the Agent SDK. Read at runtime; can live in the shell or in `secrets.env`. Run `urika config api-key` for an interactive setup. |
| `URIKA_ACK_API_KEY_REQUIRED` | (unset) | When set to any value, silences the one-time startup warning that fires whenever `ANTHROPIC_API_KEY` is unset. Set this only after acknowledging the requirement (e.g. you are running purely in private mode and have no need for the cloud key). |
| `URIKA_HOME` | `~/.urika` | Location of the global Urika config directory (`settings.toml`, `secrets.env`, `projects.json` registry, session memory). |
| `URIKA_PROJECTS_DIR` | `~/urika-projects` | Default directory where `urika new` creates project directories. |
| `URIKA_EMAIL_PASSWORD` | (none) | Conventional name for the email channel's SMTP password. The actual variable name is whatever you set in `[notifications.email].password_env`. |
| `SLACK_BOT_TOKEN` | (none) | Conventional name for the Slack bot token. The actual variable name is whatever you set in `[notifications.slack].bot_token_env`. |
| `SLACK_APP_TOKEN` | (none) | Conventional name for the Slack app-level token used by Socket Mode (inbound interactions). Pointed to by `[notifications.slack].app_token_env`. |
| `TELEGRAM_BOT_TOKEN` | (none) | Conventional name for the Telegram bot token. Pointed to by `[notifications.telegram].bot_token_env`. |
| `<api_key_env>` | (none) | Per-endpoint API key. The env-var name is whatever you set in `[privacy.endpoints.<name>].api_key_env` — e.g. `INFERENCE_HUB_KEY` for a custom hub. |
| `NO_COLOR` | (unset) | When set to any value, disables all terminal colors and formatting. Follows the [no-color.org](https://no-color.org) convention. |
| `URIKA_REPL` | (unset) | Set internally when running inside the REPL. Used to prevent nested REPL sessions and adjust CLI behavior. |

Colors are enabled by default when stdout is a TTY. Setting `NO_COLOR=1` disables them. When stdout is not a TTY (e.g., piped output), colors are automatically disabled.

The notification and endpoint variables above are *conventional* — Urika never hardcodes their names. Each channel and endpoint config has a `*_env` field that names the variable to read at runtime. You can rename or reuse them freely; just keep the `_env` field in sync. Values themselves can sit in [`~/.urika/secrets.env`](#urikasecrets-env) (recommended for shared workstations) or be exported from your shell (recommended for ephemeral sessions). Shell exports take precedence.

---

**Next:** [Project Structure](15-project-structure.md)
