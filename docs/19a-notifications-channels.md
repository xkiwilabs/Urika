# Notifications — Channel Setup

How notifications work, plus full setup walkthroughs for Email, Slack, and Telegram, and how to enable channels per project. See [Remote Commands and Troubleshooting](19b-notifications-remote.md) for remote `/commands`, what gets notified, the credentials reference, troubleshooting, and known caveats.

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


## See also

- [Notifications — Remote Commands and Troubleshooting](19b-notifications-remote.md)
- [CLI Reference](16a-cli-projects.md)
- [Configuration](14b-global-config.md)
- [Dashboard — Settings](18c-dashboard-settings.md)
