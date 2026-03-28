# Notifications

Urika can send notifications to email, Slack, and Telegram when experiments start, complete, fail, or hit key milestones. Slack and Telegram also support inbound commands -- you can pause or stop a running experiment from your phone or desktop without touching the terminal.


## Quick Setup

Add a `[notifications]` section to your project's `urika.toml` (or to `~/.urika/settings.toml` for global defaults) and configure at least one channel. See the channel sections below for full configuration options.

The next time you run `urika run`, you'll receive notifications at key points. If no `[notifications]` section exists, notifications are off by default.


## Channels

### Email

Email uses Python's built-in `smtplib` -- no extra packages needed. It sends HTML emails with experiment summaries, metrics, and status.

**Configuration:**

```toml
[notifications.email]
to = ["you@lab.edu"]          # List of recipient addresses
smtp_server = "smtp.gmail.com" # SMTP server hostname
smtp_port = 587                # SMTP port (default: 587 for STARTTLS)
from_addr = "urika@lab.edu"   # Sender address
password_env = "URIKA_EMAIL_PASSWORD"  # Environment variable containing the password
username = "urika@lab.edu"    # Optional — defaults to from_addr
```

**How it works:**

- High-priority events (criteria met, experiment failed, experiment completed) are sent immediately
- Low-priority events (turn started, run recorded) are batched and sent together when a higher-priority event occurs or when the run finishes
- This means you typically get 1-2 emails per experiment, not one per turn

**Gmail setup:**

If using Gmail, you'll need an [App Password](https://support.google.com/accounts/answer/185833) (not your regular password). Set it as an environment variable:

```bash
export URIKA_EMAIL_PASSWORD="your-app-password"
```

For institutional SMTP servers that don't require authentication, omit `password_env` -- Urika will connect without login.


### Slack

Slack sends rich Block Kit messages with formatted metrics, status indicators, and interactive Pause/Stop buttons.

**Prerequisites:**

```bash
pip install "urika[notifications]"   # or: pip install slack-sdk
```

**Create a Slack Bot:**

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. Under **OAuth & Permissions**, add these bot token scopes:
   - `chat:write` -- send messages
   - `chat:write.public` -- post to channels the bot hasn't been invited to
3. Install the app to your workspace and copy the **Bot User OAuth Token**
4. For interactive buttons (Pause/Stop), also enable **Socket Mode** and generate an **App-Level Token** with `connections:write` scope

**Configuration:**

```toml
[notifications.slack]
channel = "#urika-results"       # Channel to post to
bot_token_env = "SLACK_BOT_TOKEN"  # Env var with bot token
app_token_env = "SLACK_APP_TOKEN"  # Optional — env var with app token for Socket Mode
```

```bash
export SLACK_BOT_TOKEN="xoxb-your-bot-token"
export SLACK_APP_TOKEN="xapp-your-app-token"   # Only needed for Pause/Stop buttons
```

**What you see in Slack:**

- Experiment started: compact context message
- Turn completed with metrics: context message with Pause/Stop buttons
- Criteria met: rich message with header, metrics fields, and success indicator
- Experiment failed: error message with details
- Paused: status message

**Interactive controls:**

If you configured `app_token_env`, messages include interactive buttons:

- **Pause** -- pauses the experiment after the current turn completes (same as pressing ESC locally)
- **Stop** -- stops the experiment immediately (same as Ctrl+C locally)
- **Status** -- shows project status (experiments, runs, completion state). Available any time.
- **Results** -- shows the leaderboard (top methods and metrics). Available any time.

The bot confirms each action in the channel.


### Telegram

Telegram sends formatted messages with inline keyboard buttons for control and queries.

**Prerequisites:**

```bash
pip install "urika[notifications]"   # or: pip install python-telegram-bot
```

**Create a Telegram Bot:**

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts to create a bot
3. Copy the **bot token**
4. Create a group chat and add your bot to it
5. To get the **chat ID**, add the bot to the group, send a message, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` and look for the `chat.id` field (it's a negative number for groups)

**Configuration:**

```toml
[notifications.telegram]
chat_id = "-100123456789"           # Group chat ID (negative number)
bot_token_env = "TELEGRAM_BOT_TOKEN"  # Env var with bot token
```

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
```

**What you see in Telegram:**

- Formatted messages with emoji indicators for different event types
- Inline keyboard with Pause, Stop, Status, and Results buttons
- Slash commands also work as text commands in the chat

**Interactive controls:**

Both inline buttons and slash commands work:

- **Pause** button or `/pause` -- pauses after current turn
- **Stop** button or `/stop` -- stops immediately
- **Status** button or `/status` -- shows project status. Available any time.
- **Results** button or `/results` -- shows leaderboard. Available any time.


## What Gets Notified

| Event | When | Priority | Email | Slack | Telegram |
|-------|------|----------|-------|-------|----------|
| Turn started | Beginning of each turn | Low | Batched | Context msg + buttons | Message + buttons |
| Run recorded | Method results saved | Low | Batched | Context msg | Message |
| Criteria met | Evaluator says done | High | Immediate | Rich message | Bold message |
| Experiment completed | After reports generated | High | Immediate | Rich message | Bold message |
| Experiment failed | Agent error | High | Immediate | Error message | Error message |
| Paused | User or remote pause | Medium | Immediate | Status message | Status message |
| Experiment starting | Advisor proposes next | Low | Batched | Context msg | Message |


## Multiple Channels

You can configure multiple channels simultaneously. All configured channels receive all notifications:

```toml
[notifications]
enabled = true

[notifications.email]
to = ["pi@lab.edu"]
smtp_server = "smtp.institution.edu"
from_addr = "urika@institution.edu"

[notifications.slack]
channel = "#urika-team"
bot_token_env = "SLACK_BOT_TOKEN"

[notifications.telegram]
chat_id = "-100123456789"
bot_token_env = "TELEGRAM_BOT_TOKEN"
```

This is useful for teams: Slack for real-time monitoring, email for the PI who wants a summary, Telegram for mobile alerts.


## Remote Commands (REPL only)

Slack and Telegram channels support inbound commands -- you can query project state, control runs, and launch agents without touching the terminal. Remote commands only work when the REPL is running with a project loaded. The CLI (`urika run`, etc.) only sends outbound notifications; it does not accept remote commands.

### Available Commands

| Category | Command | Description |
|----------|---------|-------------|
| **Read-only** | `/status` | Project overview (experiments, runs, completion) |
| | `/results` | Leaderboard -- top methods and metrics |
| | `/methods` | Registered methods |
| | `/criteria` | Success criteria |
| | `/experiments` | List experiments |
| | `/logs` | Recent log entries |
| | `/usage` | Token and cost summary |
| | `/help` | List available commands |
| **Run control** | `/pause` | Pause after the current turn completes |
| | `/stop` | Stop immediately and clear the command queue |
| | `/resume` | Resume a paused run |
| **Agent** | `/run` | Start an experiment run |
| | `/advisor <text>` | Ask the advisor a question |
| | `/evaluate` | Run the evaluator |
| | `/plan` | Run the planning agent |
| | `/report` | Generate a report |
| | `/present` | Generate a presentation |
| | `/finalize` | Run the finalizer |
| | `/build-tool <text>` | Create a new tool |

**Read-only** commands return an instant text response. They never modify project state.

**Run control** commands interact with the PauseController -- the same mechanism used by the local ESC key. `/stop` also clears any queued commands.

**Agent** commands launch agent workflows. If an agent is already running, the command is queued and executes automatically when the current agent finishes (FIFO order). You cannot start a second `/run` while one is in progress -- stop the current run first.

### Queue Behavior

- Agent commands are queued in FIFO order when an agent is busy.
- `/stop` clears the entire queue in addition to stopping the active agent.
- Loading a new project clears the queue.
- Read-only and run-control commands are never queued -- they execute immediately.

### When the Bot Is Offline

If no REPL session is running, the Telegram/Slack bot is not listening. Commands sent while the REPL is offline are not stored -- they are simply lost. The bot comes online when you start the REPL with a project loaded and goes offline when the REPL exits.

Commands that modify global settings or require interactive input (`/config`, `/new`, `/project`, `/quit`, `/inspect`, `/notifications`, `/update`) are rejected with a message directing you to the terminal.


## Global vs Project Config

Notification settings can be configured at two levels:

- **Global defaults** (`~/.urika/settings.toml`) -- apply to all projects unless overridden
- **Project settings** (`urika.toml`) -- override global defaults for this project

Project settings take precedence. This lets you have a default Slack channel for all projects but send specific project notifications to a dedicated channel:

```toml
# ~/.urika/settings.toml (global)
[notifications]
enabled = true
[notifications.slack]
channel = "#urika-general"
bot_token_env = "SLACK_BOT_TOKEN"

# ~/urika-projects/important-study/urika.toml (project)
[notifications]
enabled = true
[notifications.slack]
channel = "#important-study-results"
bot_token_env = "SLACK_BOT_TOKEN"
```


## Disabling Notifications

To disable notifications for a specific project without removing the config:

```toml
[notifications]
enabled = false
```

To disable globally, set the same in `~/.urika/settings.toml`. If the `[notifications]` section is absent entirely, notifications are off by default.


## Security

- **Tokens and passwords are never stored in config files.** All credentials are read from environment variables at runtime.
- **Inbound commands (Pause/Stop) work through the same PauseController as the local ESC key** -- they don't bypass any security boundaries or inject instructions into running agents.
- **Notification failures are logged but never block experiments.** If Slack is down or your email server rejects a message, the experiment continues normally.

---

**Next:** Return to [Documentation Index](README.md)
