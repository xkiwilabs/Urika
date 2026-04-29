# Notifications

Urika can send notifications to email, Slack, and Telegram when experiments start, complete, fail, or hit key milestones. Slack and Telegram also support remote commands -- you can check project status, ask the advisor questions, pause or stop runs, and more, all from your phone without touching the terminal.


## How It Works

Notifications have two parts:

1. **Global channel setup** (`~/.urika/settings.toml`) -- configure your email server, Slack bot, or Telegram bot once. These settings apply across all projects.

2. **Per-project opt-in** (each project's `urika.toml`) -- choose which channels to enable for each project. Notifications are **off by default** -- you must explicitly enable them per project.

Run `urika notifications` to set up channels interactively, or edit the config files directly.


## Setting Up Channels

### Email

Email uses Python's built-in SMTP library -- no extra packages needed. It sends HTML emails with experiment summaries, metrics, and status.

#### Step 1: Run the setup command

```bash
urika notifications
```

Choose **Email** and enter:
- **SMTP server** -- your email provider's SMTP server (e.g., `smtp.gmail.com` for Gmail, `smtp.office365.com` for Microsoft 365)
- **SMTP port** -- usually `587` for STARTTLS (the default)
- **From address** -- the email account sending notifications
- **To addresses** -- who receives them (comma-separated for multiple recipients)
- **App password** -- an app-specific password (NOT your regular login password)

The password is saved to `~/.urika/secrets.env` (owner-read-only, never in config files).

#### Step 2: Get an app password

Most email providers require an app password when using SMTP:

**Gmail:**
1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** if not already on
3. Go to https://myaccount.google.com/apppasswords
4. Create an app password named "Urika"
5. Copy the 16-character code -- this is your app password

**Microsoft 365 / Outlook:**
1. Go to https://mysignins.microsoft.com/security-info
2. Add sign-in method -> **App password**
3. If "App password" is not available, your organization has disabled it -- use a Gmail account instead

**Institutional SMTP servers** that don't require authentication: leave the app password blank during setup.

#### Step 3: Enable for a project

```bash
urika notifications --project my-study
```

Select email when prompted. Your project's `urika.toml` will get:

```toml
[notifications]
channels = ["email"]
```

That's it. The next time you run an experiment on this project, you'll receive emails.

#### How email batching works

- **High-priority events** (criteria met, experiment completed, experiment failed) are sent **immediately**
- **Low-priority events** (turn started, run recorded) are **batched** -- held in memory until a high-priority event triggers a send
- This means you typically get **1-2 emails per experiment**, not one per turn
- When a run finishes (or is paused/stopped), any remaining batched events are flushed


### Slack

Slack sends rich messages with formatted metrics, status indicators, and interactive buttons.

#### Step 1: Create a Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** -> **From scratch**
3. Name it "Urika" (or anything you like), pick your workspace
4. Click **Create App**

#### Step 2: Add permissions

1. In the left sidebar, click **OAuth & Permissions**
2. Scroll to **Scopes** -> **Bot Token Scopes**
3. Add these scopes:
   - `chat:write` -- send messages
   - `chat:write.public` -- post to any public channel
   - `app_mentions:read` -- read messages where the bot is `@`-mentioned
   - `channels:history` -- read messages in public channels the bot has been added to (needed for inbound `/commands`)
   - `groups:history` -- same, for private channels
   - `im:history` -- same, for direct messages to the bot

The last three (`*:history`) are required for inbound commands like
`/status`, `/pause`, `/results`. Without them, the bot can post
notifications but cannot read commands you type back.

#### Step 3: Install to workspace

1. Scroll back to **OAuth Tokens** at the top
2. Click **Install to Workspace** -> Authorize
3. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

#### Step 4: Configure in Urika

```bash
urika notifications
```

Choose **Slack** and enter:
- **Channel** -- e.g., `#urika-results` (create the channel in Slack first)
- **Bot token** -- paste the `xoxb-...` token

#### Step 5 (optional): Enable interactive buttons

For Pause/Stop/Status/Results buttons in Slack messages:

1. In your Slack app settings, click **Socket Mode** in the sidebar -> **Enable**
2. Click **Generate Token**, name it "Urika", give it `connections:write` scope
3. Copy the **App-Level Token** (starts with `xapp-`)
4. Go to **Interactivity & Shortcuts** -> turn **On**
5. In Urika setup, enter the app token when prompted

Without this step, you still get all notification messages -- you just won't have clickable buttons.

#### Step 5b: Subscribe to message events (so the bot can read commands)

For inbound commands (`/status`, `/pause`, free-text questions), the
Slack app must subscribe to message events:

1. In your Slack app settings, click **Event Subscriptions** in the sidebar -> **Enable Events**
2. Under **Subscribe to bot events**, add:
   - `message.channels` -- public channel messages
   - `message.groups` -- private channel messages
   - `message.im` -- direct messages to the bot
   - `app_mention` -- so `@your-bot status` also works
3. Save changes. Slack may prompt you to reinstall the app -- do so to pick up the new scopes.

Socket Mode (Step 5) must be enabled for these events to reach Urika
without a public webhook URL.

#### How Slack commands work in Urika (NOT via Slack's Slash Commands API)

Urika's Slack bot reads regular **channel messages**. When you type a
message that starts with `/` (e.g. `/status`, `/pause`) in a channel
where the bot is a member, the bot receives it as a normal message
event, recognises the leading `/`, and routes it to Urika's command
handler.

**Do NOT register these commands in the Slack app's "Slash Commands"
page.** Slack's native slash command machinery routes commands through
a different Socket Mode envelope (`slash_commands`) that Urika does
not currently listen to. If you register `/status` as a real Slack
slash command, Slack will intercept it before the bot's message
listener sees it, and the command will appear to do nothing.

The required Slack app configuration is:

1. **Bot Token Scopes** (Step 2 above): `chat:write`, `chat:write.public`, `app_mentions:read`, `channels:history`, `groups:history`, `im:history`.
2. **Event Subscriptions** (Step 5b above): `message.channels`, `message.groups`, `message.im`, `app_mention`.
3. **Socket Mode** (Step 5 above): enabled, with an app-level token (`xapp-...`).
4. **Interactivity & Shortcuts** (Step 5 above): on — for the Pause/Stop/Status/Results buttons on `experiment_started` notifications.
5. **NO entries on the "Slash Commands" page.** Leave that page empty.
6. **Bot invited** to the channel (`/invite @your-bot-name` from inside the Slack channel).

Available bot commands (just type them as regular messages in the
channel where the bot is a member -- no Slack-side registration
needed):

| Command | What it does |
|---|---|
| `/status` | Project status |
| `/results` | Top methods leaderboard |
| `/methods` | Recently registered methods |
| `/criteria` | Current success criteria |
| `/experiments` | Recent experiments |
| `/logs` | Recent run logs |
| `/usage` | Token + cost summary |
| `/pause` | Pause active run |
| `/stop` | Stop active run |
| `/resume` | Resume run |
| `/help` | List of all available bot commands |

Free text (no leading `/`) is routed to the orchestrator as an `ask`
command, so you can have a conversation with the bot without using a
slash prefix.

Inline buttons (Pause / Stop / Status / Results) on `experiment_started`
notifications use Slack's **interactivity** (Block Kit button) API,
which Urika DOES handle. Those work whether or not slash commands are
registered, as long as Step 5 (Socket Mode + Interactivity) is on.

A future release may add native Slack slash command support (via the
`slash_commands` Socket Mode envelope). For now, use the
regular-message convention above.

#### Restricting who can control the bot

By default, **any user in your Slack workspace** who can see the Urika channel can click the Pause/Stop/Status/Results buttons or send `/commands` to the bot. For most solo researchers this is fine, but for shared workspaces you'll want to restrict control to specific channels or people.

Add `allowed_channels` and/or `allowed_users` to the Slack section of `~/.urika/settings.toml`:

```toml
[notifications.slack]
channel = "#urika-results"
bot_token_env = "SLACK_BOT_TOKEN"
app_token_env = "SLACK_APP_TOKEN"

# Only accept interactions from these channel IDs
allowed_channels = ["C0123456789"]

# Only accept interactions from these user IDs
allowed_users = ["U0ABCDEFGHI"]
```

Rules:
- If both keys are **unset**, all interactions are accepted (back-compat) and a warning is logged at startup.
- If `allowed_channels` is set, interactions from any other channel are dropped.
- If `allowed_users` is set, interactions from any other user are dropped.
- If both are set, both must match.
- Drops are fail-closed: a payload missing the relevant id is rejected when the corresponding list is set. Rejected interactions are logged as warnings and never dispatched.

You can find channel and user IDs in Slack: right-click a channel or user -> **View channel details** / **View profile** -> the ID is in the footer (starts with `C` for channels, `U` for users).

#### Step 6: Enable for a project

```bash
urika notifications --project my-study
```

Select Slack when prompted.


### Telegram

Telegram sends formatted messages with inline keyboard buttons. You can also type commands directly in the chat.

#### Step 1: Install Telegram

Download the Telegram app on your phone or desktop and create an account (free, requires a phone number).

#### Step 2: Create a bot

1. Open Telegram and search for **@BotFather** (it's Telegram's official bot-creation tool, with a blue checkmark)
2. Tap on it and send `/start`
3. Send `/newbot`
4. Enter a name for your bot (e.g., "Urika Notifications")
5. Enter a username (must end in `bot`, e.g., `urika_lab_bot`)
6. BotFather replies with a **token** -- copy it (looks like `123456789:ABCdefGHI-jklMNO`)

#### Step 3: Get your chat ID

For **personal notifications** (just you):
1. Search for your bot's username in Telegram (e.g., `@urika_lab_bot`)
2. Tap **Start**, then send any message (e.g., "hi")
3. Open this URL in a browser (replace `<TOKEN>` with your bot token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   Make sure there's no space between `bot` and the token.
4. Look for `"chat":{"id":` in the JSON response -- the number after it is your chat ID (a positive number for direct messages)

For **team notifications** (a group):
1. Create a group in Telegram and add your bot to it
2. Send a message in the group
3. Visit the same `getUpdates` URL
4. The chat ID for groups is a **negative number** (e.g., `-100123456789`)

If `getUpdates` returns `{"ok":true,"result":[]}`, send another message to the bot and reload the URL.

#### Step 4: Configure in Urika

```bash
urika notifications
```

Choose **Telegram** and enter:
- **Chat ID** -- the number from step 3
- **Bot token** -- the token from BotFather

#### Step 5: Enable for a project

```bash
urika notifications --project my-study
```

Select Telegram when prompted.


## Enabling Notifications for a Project

Global setup configures the channels. Each project decides which channels to use:

```bash
urika notifications --project my-study
```

This adds to the project's `urika.toml`:

```toml
[notifications]
channels = ["email", "telegram"]
```

You can enable any combination: just email, just Telegram, all three, etc.

### Adding extra recipients per project

A project can add email recipients beyond the global defaults:

```toml
[notifications]
channels = ["email"]

[notifications.email]
to = ["collaborator@university.edu"]
```

These are **added to** the global recipients, not replacing them.

### Per-project Telegram groups

Each project can send to a different Telegram group:

```toml
[notifications]
channels = ["telegram"]

[notifications.telegram]
chat_id = "-100999888"
```

This overrides the global chat ID for this project only. The bot token still comes from global settings.


## Remote Commands

When Urika is running with a project loaded, Slack and Telegram become interactive -- you can send commands and get responses.

### How it works

1. Launch Urika: `urika`
2. Load a project: `/project my-study`
3. The bot starts listening
4. Send commands from Telegram/Slack
5. Bot responds with results
6. Bot stops when you exit Urika or switch projects

### Available commands

Type `/help` in Telegram/Slack to see all commands. Type `/help <command>` for details on a specific command.

**Always available (instant response):**

| Command | Description |
|---------|-------------|
| `/status` | Project overview -- experiments, runs, completion state |
| `/results` | Leaderboard -- top methods ranked by primary metric |
| `/methods` | Last 10 registered methods with status and metrics |
| `/criteria` | Current success criteria |
| `/experiments` | Last 10 experiments with status and run counts |
| `/logs` | Last 5 run logs from the most recent experiment |
| `/usage` | Token counts, cost, agent calls |
| `/help` | List all commands (or `/help run` for details on a specific command) |

**Run control (during active run):**

| Command | Description |
|---------|-------------|
| `/pause` | Pause after the current turn completes |
| `/stop` | Stop immediately and clear queued commands |
| `/resume` | Resume a paused or stopped experiment |

**Agent commands (run when idle, queued when busy):**

| Command | Description |
|---------|-------------|
| `/run` | Start an experiment (default settings) |
| `/advisor <question>` | Ask the advisor a question |
| `/evaluate` | Run the evaluator on the most recent experiment |
| `/plan` | Run the planning agent |
| `/report` | Generate a report |
| `/present` | Generate a presentation |
| `/finalize` | Run the finalizer |
| `/build-tool <description>` | Create a custom tool |

Agent commands take time to complete (seconds to minutes). You'll get a message like "Running /advisor (thinking -- may take a few minutes)..." followed by the result when it's ready.

If an agent is already running, your command is queued and runs automatically when the current one finishes. `/stop` clears the queue.

### Commands not available remotely

These require interactive terminal input: `/new`, `/project`, `/config`, `/notifications`, `/update`, `/inspect`, `/knowledge`, `/quit`.

### When the bot is offline

The bot only listens when Urika is running with a project loaded. If you send a command while Urika is closed, the bot won't respond. Launch Urika and load the project to bring the bot online.

All remote commands are shown in the TUI terminal with a `[Remote]` tag so you can see what's happening.


## What Gets Notified

Notifications are experiment-level only -- no per-turn noise. You get notified at key milestones:

| Event | When | What you see |
|-------|------|-------------|
| Experiment started | New experiment created (autonomous mode) | Name and description |
| Criteria met | Evaluator says success criteria satisfied | Criteria met message |
| Experiment completed | After reports generated | Runs, methods, best result (e.g. "5 runs, 3 methods. Best: random_forest r2=82.3%") |
| Experiment failed | Agent error | Error details |
| Paused | ESC or remote `/pause` | Turn count and current results |
| Stopped | Ctrl+C or remote `/stop` | Turn count and current results |


## Credentials and Security

- **All tokens and passwords are stored in `~/.urika/secrets.env`** (file permissions: owner-read-only). They are never written to config files.
- You can also set credentials as regular environment variables -- these take precedence over `secrets.env`.
- **Remote commands use the same PauseController as the local ESC key** -- they don't bypass any security boundaries.
- **Notification failures never block experiments.** If email/Slack/Telegram is down, the experiment continues normally. Errors are logged.


## Configuration Reference

### Global settings (`~/.urika/settings.toml`)

Channel configuration -- shared across all projects:

```toml
[notifications.email]
smtp_server = "smtp.gmail.com"
smtp_port = 587
from_addr = "you@gmail.com"
username = "you@gmail.com"
to = ["you@gmail.com", "team@lab.edu"]
password_env = "URIKA_EMAIL_PASSWORD"

[notifications.slack]
channel = "#urika-results"
bot_token_env = "SLACK_BOT_TOKEN"
app_token_env = "SLACK_APP_TOKEN"

[notifications.telegram]
chat_id = "123456789"
bot_token_env = "TELEGRAM_BOT_TOKEN"
```

### Project settings (`urika.toml`)

Select which channels to enable and optional overrides:

```toml
[notifications]
channels = ["email", "telegram"]

# Optional: extra email recipients for this project
[notifications.email]
to = ["collaborator@university.edu"]

# Optional: different Telegram group for this project
[notifications.telegram]
chat_id = "-100999888"
```

### Credential store (`~/.urika/secrets.env`)

```
URIKA_EMAIL_PASSWORD=xxxx xxxx xxxx xxxx
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
TELEGRAM_BOT_TOKEN=123456789:ABC...
```

## Troubleshooting

When a channel isn't delivering, the dashboard's **Send test notification** button
on Settings → Notifications is the fastest diagnostic — it sends one event
through every configured channel and reports per-channel success or the
specific error message returned by the channel's SDK.

For each channel, the most common failures are:

### Email

| Symptom | Likely cause | Fix |
|---|---|---|
| `Authentication failed (535)` | App password wrong or 2FA app password not generated | Regenerate the Google / Outlook app password and update `SMTP_PASSWORD` |
| `[Errno 111] Connection refused` | SMTP host or port wrong | Verify host (`smtp.gmail.com` for Gmail; `smtp.office365.com` for Outlook) and port (587 for STARTTLS) |
| `getaddrinfo failed` | Hostname typo, DNS issue | Verify the SMTP host string |
| `STARTTLS extension not supported` | Server requires SSL not TLS | Switch to port 465 with SSL — currently Urika uses STARTTLS only; file an issue if you need SSL |
| Tests pass but no email arrives | Mail filter, wrong `to` address | Check spam folder; verify `to` field |

### Slack

| Symptom | Likely cause | Fix |
|---|---|---|
| `invalid_auth` | Bot token revoked or wrong env var | Re-issue the bot token in your Slack app settings; update the env var |
| `not_in_channel` | Bot was never invited to the channel | In Slack, run `/invite @YourBotName` in the channel |
| `channel_not_found` | Wrong channel name or private channel without access | Verify channel name; bot must be a member of private channels |
| Inbound commands don't work | App token (Socket Mode) not configured | Set `SLACK_APP_TOKEN` env var and the **App token env var** field on the dashboard; ensure Socket Mode is enabled in app settings |
| `missing_scope` | Bot missing OAuth scope | Add `chat:write`, `chat:write.public`, and `app_mentions:read` scopes; reinstall app |

### Telegram

| Symptom | Likely cause | Fix |
|---|---|---|
| `Unauthorized` / `InvalidToken` | Bot token wrong or revoked | Get a fresh token from @BotFather |
| `chat not found` | Wrong chat ID or bot never messaged the chat | Open the chat with the bot and send `/start`; re-fetch the chat ID via `getUpdates` |
| `Forbidden: bot was blocked by the user` | User blocked the bot | Unblock in Telegram client |
| Inline buttons don't respond | Polling stopped after error | Check Urika logs; restart Urika to re-establish polling |

### General diagnostics

- **No notifications at all:** confirm the project's `notifications` config has at least one channel set to `enabled = true` (`urika notifications --show` or the project's Notifications tab).
- **Some events deliver, others don't:** Slack and Telegram apply per-event-type formatting based on the canonical event vocabulary. Unknown event types fall through to a default ℹ icon — if you're seeing the default icon for events that should have specific formatting, check `urika.toml` for stale event-type strings.
- **Channel logs as "failed health check" at startup:** the channel's auth probe failed before any event was sent. The bus excludes failing channels from dispatch — fix the credential issue and restart Urika.

## Caveats

A few behaviours worth knowing about up front:

- **Pause / Stop / Resume buttons (Telegram inline keyboard) only appear on `experiment_started` events.** Mid-experiment notifications don't carry the keyboard — for fine-grained control during an active run, use the bot's `/pause`, `/stop`, `/resume` slash commands directly.
- **Email batches low-priority events.** Events with `priority="low"` are queued and flushed only when a `medium` or `high` event arrives, or at shutdown. This avoids inbox flooding for routine progress events. Slack and Telegram do not batch — every event sends immediately.
- **Per-channel priority filtering is not yet user-configurable.** Today, every enabled channel receives every event the bus emits. A future release will add per-event-type opt-in (issue #TBD).
- **Health check on bad credentials excludes a channel from dispatch for the entire process lifetime.** Updating credentials in env vars does NOT re-probe the running bus — restart Urika so the next `bus.start()` re-runs the health check. The dashboard's Send-test button builds a fresh bus from un-saved form data and probes each channel directly, so use it to confirm fixes before restarting.
- **Test sends count toward your channel's rate limits.** Slack rate-limits ~1 message/sec/channel; Telegram rate-limits ~30 messages/sec; Gmail rate-limits ~100/day on free SMTP. Don't spam the test button.
- **Inbound Slack commands require Socket Mode + an app token in addition to the bot token.** Outbound notifications work with just the bot token; inbound (slash commands, button taps) needs the app-token env var set.
- **`experiment_paused` and `paused` are different events.** `experiment_paused` is end-of-experiment ("the entire experiment was paused after turn N"). `paused` is a generic mid-loop pause (e.g., autonomous-mode pause between experiments). Both are notified separately so you can wire them differently if needed.

---

**Next:** [Security Model](20-security.md)
