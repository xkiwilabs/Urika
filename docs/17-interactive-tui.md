# Interactive TUI

The Urika TUI is a full-screen Textual terminal interface for managing projects, running experiments, and conversing with the orchestrator -- all without leaving the terminal.

## Layout

The TUI has four zones:

- **Output Panel** — scrollable area showing all agent output, command results, and orchestrator responses
- **Input Bar** — type slash commands or free-text questions, with contextual tab completion
- **Activity Bar** — animated spinner showing what the system is doing (agent name, activity verb)
- **Status Bar** — persistent single-line bar showing: project name, model, token count, cost, and processing time

## Launching the TUI

Run `urika` with no subcommand:

```bash
urika
```

On launch, Urika displays the ASCII header, a list of recent projects, and getting-started guidance in the output panel.

A classic prompt-toolkit REPL is also available:

```bash
urika --classic
```


## Loading a Project

Before you can run experiments or use project-specific commands, load a project:

```
urika> /project my-project

  Project: my-project - exploratory
    3 experiments - 2 completed
```

The prompt changes to reflect the loaded project:

```
urika:my-project>
```

Loading a project clears any previous conversation history. Only one project can be loaded at a time.


## Tab Completion

The TUI provides tab completion for:

- **Slash commands** -- type `/` and press Tab to see all available commands
- **Project names** -- after `/project `, Tab completes registered project names
- **Experiment IDs** -- after commands that accept experiments (`/present`, `/logs`, `/evaluate`, `/report`, `/plan`, `/results`, `/resume`), Tab completes experiment IDs from the loaded project


## Status Bar

A persistent status bar at the bottom displays session state in colored text:

```
urika │ my-project │ claude-sonnet-4-20250514 │ 82K tokens · 8 calls │ ~$0.41 │ 12m 34s
```

The status bar updates every 250ms and shows:

| Field | Description |
|-------|-------------|
| Project name | Currently loaded project |
| Model | The Claude model used in the most recent agent call |
| Tokens · Calls | Total tokens consumed and number of agent invocations |
| Cost | Estimated cost at API rates |
| Processing time | Time spent processing (only ticks while an agent is running) |

## Activity Bar

Between the input bar and status bar, the activity bar shows what the system is doing:

```
 ⠹ orchestrator — Thinking…
```

When idle it displays a dim "ready" label. When an agent is running, it shows an animated spinner, the agent name, and a rotating activity verb.


## Free-Text Input

Any input that does not start with `/` is sent to the **orchestrator** as a conversational message. The orchestrator can answer questions about your project, call subagents (advisor, evaluator, data inspector) for quick queries, and recommend slash commands for longer operations:

```
> What methods should I try next given the current results?

  ▸ Read progress.json
  ▸ Bash: CLAUDECODE= urika advisor "my-project" "What should we try next?"

Based on your current results showing linear models plateauing at r2=0.51,
I recommend trying tree-based approaches. Type /run to start the next experiment.
```

The orchestrator has access to project state files (progress, methods, criteria, labbook) and can call subagents via Bash for targeted questions. For long-running operations, it recommends the appropriate slash command.

## Conversation History

The TUI maintains a rolling conversation history between you and the orchestrator. Each exchange (your message and the orchestrator's response) is tracked. When you send a new message, the last 20 exchanges are included as context, giving the orchestrator continuity across the conversation.

Conversation history is cleared when you load a different project.

For a detailed guide on advisor conversations, the suggestion-to-run flow, and how to use instructions to steer agents, see [Advisor Chat and Instructions](07-advisor-and-instructions.md).

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Tab` | Accept the current tab completion suggestion |
| `Ctrl+C` | Cancel a running agent, or quit if idle |
| `Ctrl+Q` | Quit the TUI |
| `Ctrl+D` | Quit the TUI |
| `Enter` | Submit input; when an agent is waiting for input (click.prompt), submits the response |


## Slash Commands

### Global Commands

Available at all times, regardless of whether a project is loaded.

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands. Project-specific commands are only shown when a project is loaded. |
| `/list` | List all registered projects. The currently loaded project is marked with a diamond. |
| `/new` | Create a new project using the same interactive builder flow as `urika new`. |
| `/project <name>` | Load a project by name. Shows project mode, experiment count, and completion status. |
| `/delete <name>` | Move a project to `~/.urika/trash/` and remove it from the registry. Prompts for confirmation. Refuses if any `.lock` is present. If the deleted project is currently loaded, the session context is cleared. |
| `/quit` | Save session usage data and exit. |
| `/tools` | List all available analysis tools. If a project is loaded, also includes project-specific tools. |
| `/usage` | Show usage stats. With a loaded project: current session and historical totals. Without: usage across all projects. |
| `/copy [N]` | Copy the last `N` output-panel lines to the clipboard via `pyperclip` (default `N = 40`). On headless Linux without `xclip`/`xsel`, prints the text inline so you can copy it manually. |
| `/notifications [show\|test\|disable]` | Open the notification setup wizard from inside the TUI (same flow as `urika notifications`). Sub-args mirror the CLI: `show`, `test`, or `disable`. With a project loaded, runs project-scoped; otherwise global. |

### Project Commands

These require a project to be loaded first. Running them without a project shows an error message.

| Command | Description |
|---------|-------------|
| `/status` | Show project status: name, question, mode, path, experiment list with statuses and run counts. |
| `/run` | Run the next experiment. Shows current settings (max turns, auto mode, instructions from conversation), then offers to run with defaults, custom settings, or skip. Checks for lock files from already-running experiments. |
| `/experiments` | List all experiments with their status and run count. |
| `/methods` | Show the methods table: all agent-created methods with status and key metrics. |
| `/results` | Show the project leaderboard (ranked methods by primary metric). Falls back to showing runs from the most recent experiment if no leaderboard exists. |
| `/criteria` | Show current success criteria: version, type, and primary threshold target. |
| `/inspect [file]` | Inspect the project dataset: schema, dtypes, missing values, and a 5-row preview. Optionally specify a data file. |
| `/logs [experiment_id]` | Show detailed run logs for an experiment with hypotheses, observations, and next steps. |
| `/knowledge [query]` | With a query: search the knowledge base. Without: list all knowledge entries. |
| `/advisor <text>` | Ask the advisor agent a question. Equivalent to typing free text, but explicit. |
| `/evaluate [experiment_id]` | Run the evaluator agent on an experiment (defaults to most recent). |
| `/plan [experiment_id]` | Run the planning agent to design the next method. Includes conversation context if available. |
| `/present [experiment_id]` | Generate a reveal.js presentation. Prompts to choose: specific experiment, all experiments, or project-level. |
| `/report [experiment_id]` | Generate labbook reports. Prompts to choose: specific experiment, all experiments, or project-level. Produces notes, summary, and agent-written narrative. |
| `/build-tool <instructions>` | Build a custom tool. E.g., `/build-tool create an EEG epoch extractor using MNE` or `/build-tool install mediapipe and add a tool that extracts facial pose data from video`. |
| `/finalize [--draft] [instructions]` | Run the finalization sequence: Finalizer Agent, Report Agent, Presentation Agent, and README update. Produces standalone methods, findings, and reproducibility artifacts. Optional instructions guide the finalizer (e.g., `/finalize focus on the ensemble methods`). Use `--draft` for an interim summary that outputs to `projectbook/draft/` without overwriting final outputs. |
| `/resume` | Resume a paused or failed experiment. Lists resumable experiments and lets you pick which to continue. |
| `/update` | Update the project description, question, or mode interactively. Shows current values, prompts for field, new value, and optional reason. Changes are versioned in `revisions.json`. |
| `/update history` | Show the revision history for the loaded project: all previous changes with timestamps, old/new values, and reasons. |
| `/config` | Configure privacy mode and models for the current project (or global defaults if no project loaded). Interactive guided setup for open, private, or hybrid mode. |
| `/config show` | Show current configuration (project or global). |
| `/config global` | Configure global defaults (used for new projects). |
| `/config global show` | Show global defaults. |
| `/dashboard [--port PORT]` | Open the project dashboard in your browser. Use `/dashboard stop` to shut it down, or `/dashboard` again to restart with fresh content. See [Dashboard](18-dashboard.md) for pages, run launcher, and auth. |
| `/pause` | Request a pause of the running experiment. The orchestrator pauses cleanly after the current subagent finishes its turn. Writes `<project>/.urika/pause_requested` (contents: `pause`). Resume with `/run` or `/resume`. |
| `/stop` | Request an immediate stop of the running agent or experiment. Writes `<project>/.urika/pause_requested` (contents: `stop`); the orchestrator's pause controller picks it up at the next loop boundary. Use this when you want the run to end now rather than continue to the next experiment. |
| `/delete-experiment <exp_id>` | Move an experiment to `<project>/trash/`. Mirrors `urika experiment delete`. Prompts for confirmation. Refuses if the experiment has a `.lock` file (active run). |


## Run Settings

The `/run` command presents current settings before starting:

```
  Run settings:
    Max turns: 5
    Auto mode: checkpoint
    Instructions: (from your conversation, or none)

  Proceed?
    1. Run with defaults
    2. Custom settings
    3. Skip
```

Choosing **Custom settings** lets you configure:

- **Max turns** -- maximum orchestrator turns per experiment
- **Auto mode**:
  - **Checkpoint** -- pause between experiments for review (default)
  - **Capped** -- run up to N experiments with no pauses
  - **Unlimited** -- run until criteria are met or the advisor says done
- **Instructions** -- custom guidance for the experiment
- **Re-evaluate criteria if met** -- advisor reviews criteria when met, may raise the bar


## Session Memory

Urika persists each orchestrator chat session to
``<project>/.urika/sessions/<id>.json`` so you can pick up a conversation
later. The TUI/REPL is the canonical write surface; the dashboard
provides read access via the **Sessions** sidebar tab.

### How sessions are created

Every chat with the orchestrator (whether free-text or a slash command
that invokes the orchestrator) is part of a session. New sessions start
when:

- You launch a fresh `urika`.
- You explicitly type `/new-session` to start a fresh session without
  exiting the TUI. This is useful when the previous conversation has
  strayed off-topic and you want a clean slate without losing the
  previous session's transcript (it remains on disk and can be resumed).

### Resume on launch

When you launch `urika` and switch into a project that has a recent
session, the REPL prints a one-line hint:

```
Project myproject loaded.
  Previous session from 2 hours ago: "Why are tree counts so skewed…"
  Type /resume-session to continue.
```

Inside the running TUI, type:

- `/resume-session` — pick from a list of recent sessions for the
  current project (1-indexed, newest first).
- `/resume-session <number>` — load the session at that position from
  the list.

Or browse and resume from the dashboard's **Sessions** tab.

### Listing sessions

- TUI/REPL: `/resume` lists recent sessions for the current project,
  newest first.
- Dashboard: navigate to **Sessions** in the project sidebar.

### Resume on the dashboard

The dashboard cannot run an interactive REPL. Instead, the **Resume**
button on a session row links to
``/projects/<n>/advisor?session_id=<id>``. The advisor page renders the
prior session's messages as a read-only "Prior session" panel above the
advisor transcript, so you can see what was discussed before and ask a
follow-up via the advisor composer. **New advisor exchanges append to
advisor history, not back to the original orchestrator session** — to
continue writing into the original session, launch `urika` in the
terminal and run ``/resume-session`` (or ``/resume-session <number>``
for a specific one; 1-indexed by recency).

### Session retention

Sessions auto-prune to the most recent **20 per project** when
``save_session`` is called. Older sessions are deleted from disk.

### Deleting a session

- Dashboard: **Delete** button on each session row.
- CLI: not yet exposed (planned). For now, manually delete
  ``<project>/.urika/sessions/<id>.json``.


## Session Usage Tracking

The TUI tracks usage throughout the session:
- Total tokens consumed (input + output)
- Estimated cost at API rates
- Number of agent calls
- Session duration

Usage is saved to the project's `usage.json` when you exit (via `/quit`, Ctrl+C, or Ctrl+D). This feeds into the `/usage` command and the `urika usage` CLI command for historical tracking.


## Tips

- Use free-text conversation to discuss strategy with the orchestrator, then `/run` to execute.
- Use `/results` frequently to check the leaderboard during iterative runs.
- Tab completion suggests commands by frequency of use (most common first), project names by most recently modified, and experiment IDs for relevant commands.
- Exit cleanly with `/quit`, Ctrl+Q, or Ctrl+D to ensure usage data is saved.
