# Persistent REPL Session with Remote Commands

## Problem

Currently the notification bus (Telegram/Slack/email listeners) only lives during a `urika run` call. When the run completes, pauses, or stops, the bus is destroyed. Telegram/Slack become unresponsive between runs. Users can't chat with the advisor, check status, or start a new run from their phone — they have to go back to the terminal.

The CLI is fire-and-forget: every command starts a process, does its thing, and exits. There's no persistent session to receive remote commands.

## Solution

Move the notification bus lifecycle from per-run to per-project-session. The REPL becomes a long-lived project session where the bus starts on `/project X` and stays alive until `/quit` or project switch. Telegram/Slack listeners persist between runs, enabling remote commands.

## Architecture

### Bus Lifecycle

```
REPL starts
  → /project dht-study
    → build_bus(project_path), bus.start()
    → Telegram/Slack listeners active
    → REPL prompt ready

    → /run → bus passed to orchestrator → run completes → bus still alive
    → advisor chat → bus still alive
    → /run again → bus still alive
    → Telegram /status → responds immediately

  → /project other-study → bus.stop(), new bus for other-study
  → /quit → bus.stop()
```

### Remote Commands

Commands available from Telegram/Slack when REPL has a project loaded:

#### Always available (read-only)
- `/status` — project status summary
- `/results` — leaderboard
- `/methods` — method registry
- `/criteria` — success criteria
- `/experiments` — experiment list
- `/logs [exp]` — run logs (truncated for chat)
- `/usage` — usage stats
- `/help` — list available remote commands

#### Run control (during active run only)
- `/pause` — pause after current turn
- `/stop` — stop immediately
- `/resume` — resume paused/stopped experiment

#### Agent commands (when idle — queued if busy)
- `/run` — start experiment (if run active: "Stop first")
- `/advisor <question>` — ask advisor
- `/evaluate [exp]` — run evaluator
- `/plan [exp]` — run planning agent
- `/report [exp]` — generate report
- `/present [exp]` — generate presentation
- `/finalize` — finalize project
- `/build-tool <text>` — build custom tool

#### Not available remotely
- `/new`, `/project`, `/config`, `/notifications`, `/update`, `/quit` — interactive/terminal-only
- `/inspect`, `/knowledge search` — long output, terminal-only

### State Tracking

ReplSession gains:
- `notification_bus: NotificationBus | None` — the persistent bus
- `agent_active: bool` — is any agent command running
- `active_command: str` — what command is running ("run", "advisor", etc.)
- `remote_command_queue: list[tuple[str, str]]` — queued commands from Telegram/Slack

### Queue Behavior

| Scenario | Behavior |
|----------|----------|
| Agent command while busy | Queued. User notified: "Queued for after [active command]" |
| `/run` while run active | Not queued. "Run in progress. Stop first." |
| `/stop` with queued commands | Queue cleared. "Stopped. Queued commands cleared." |
| `/pause` with queued commands | Queued commands run after pause (advisor questions are why you paused) |
| Read-only command while busy | Executes immediately, never queued |
| REPL drains queue | After every command returns and before every prompt |

### Response Delivery

Remote command results sent back to originating Telegram group / Slack channel:
- Short responses: send directly
- Long responses (advisor, report): truncate at 3000 chars for Telegram (4096 limit), note "[Full response in terminal]"
- Email: not used for command responses (notifications only)

### CLI Behavior

No changes. CLI remains fire-and-forget:
- `urika run` creates and destroys its own bus per-run
- Final CLI notification includes hint: "For remote commands, use REPL"
- No remote command input in CLI mode

### Offline Bot

When no REPL session is active for a project, the Telegram/Slack bot is offline (not polling). The user gets no response. This is documented and acceptable for now. A future `urika listen` daemon could provide always-on responsiveness.

## Components Changed

| Component | Change |
|-----------|--------|
| `repl_session.py` | Add `notification_bus`, `agent_active`, `active_command`, `remote_command_queue` |
| `repl.py` | Start bus on `/project`, drain queue after commands and at prompt |
| `repl_commands.py` | Wrap agent commands with `agent_active` flag |
| `notifications/bus.py` | Add command queue, respond method, command classification |
| `notifications/queries.py` | Add query functions for methods, criteria, experiments, logs, usage |
| `notifications/telegram_channel.py` | Handle all remote commands, classify, queue/execute |
| `notifications/slack_channel.py` | Same expansion |
| `notifications/base.py` | Update listener interface for session reference |

## Not Changed

- CLI behavior (fire-and-forget)
- Orchestrator loop
- Pause/stop mechanism (PauseController)
- Existing REPL commands
- Project creation, configuration flows
