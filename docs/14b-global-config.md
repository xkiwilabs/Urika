# Configuration — Global

Global (user-level) configuration: `~/.urika/settings.toml`, the `~/.urika/secrets.env` vault, and environment variables. See [Per-Project Configuration](14a-project-config.md) for `urika.toml`, criteria, methods, usage, and the per-project state-files table.

## Global configuration files

The files described in [Per-Project Configuration](14a-project-config.md) (`urika.toml`, `criteria.json`, `methods.json`, `usage.json`) are *per-project* — each one lives at the root of one project directory. Urika also keeps two *global* (user-level) files under `~/.urika/`. These hold settings that apply across every project: shared LLM endpoints, default preferences, notification channel definitions, and credentials.

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

See [Notifications](19a-notifications-channels.md) for a deeper walkthrough of the channel configuration and the per-project `urika.toml` overrides that select which channels each project uses.

### `~/.urika/secrets.env`

A user-level credential store. The file is a plain `KEY=VALUE` text file with comments allowed; it is created by `urika config notifications`, `urika config api-key`, or `save_secret` from Python at permissions `0600` (owner read/write only). Don't commit it.

> **`ANTHROPIC_API_KEY` is required.** Urika uses the Claude Agent SDK,
> which under Anthropic's Consumer Terms (§3.7) and the April 2026
> Agent SDK clarification cannot be authenticated via a Claude Pro/Max
> subscription. Set `ANTHROPIC_API_KEY` in `~/.urika/secrets.env`,
> export it in your shell, or run `urika config api-key` for an
> interactive setup. After saving, verify the key with
> `urika config api-key --test` — it sends a minimal request to
> `api.anthropic.com` and reports success or the exact failure
> (401 unauthorized, 429 rate-limited, etc.). See
> [Security § Provider compliance](20-security.md#provider-compliance)
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


## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (none) | Claude API key. **Required** for any cloud-touching Urika command — Anthropic's Consumer Terms §3.7 and the April 2026 Agent SDK clarification prohibit using a Pro/Max subscription to authenticate the Agent SDK. Read at runtime; can live in the shell or in `secrets.env`. Run `urika config api-key` for an interactive setup, then `urika config api-key --test` to verify the key works against `api.anthropic.com`. |
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


## See also

- [Per-Project Configuration](14a-project-config.md)
- [Models and Privacy](13a-models-and-privacy.md)
- [Security Model](20-security.md)
- [Notifications](19a-notifications-channels.md)
