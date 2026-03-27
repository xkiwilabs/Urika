# Interactive REPL

The Urika REPL is an interactive shell for managing projects, running experiments, and conversing with the advisor agent -- all without leaving the terminal.


## Launching the REPL

Run `urika` with no subcommand:

```bash
urika
```

On launch, Urika displays the ASCII header and a summary of global stats (projects, experiments, methods, SDK version), then drops into the prompt:

```
urika>
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

The REPL provides tab completion for:

- **Slash commands** -- type `/` and press Tab to see all available commands
- **Project names** -- after `/project `, Tab completes registered project names
- **Experiment IDs** -- after commands that accept experiments (`/present`, `/logs`, `/evaluate`, `/report`, `/plan`, `/results`, `/resume`), Tab completes experiment IDs from the loaded project


## Bottom Toolbar

A persistent bottom toolbar displays session state:

```
────────────────────────────────────────────────────────────────────────────────
 urika - my-project - claude-sonnet-4-20250514 - 12m 34s - 82K tokens - 8 calls - ~$0.41
```

The toolbar updates in real time and shows:

| Field | Description |
|-------|-------------|
| Project name | Currently loaded project |
| Model | The Claude model used in the most recent agent call |
| Elapsed time | Time since the REPL session started |
| Tokens | Total tokens consumed (input + output) |
| Agent calls | Number of agent invocations in this session |
| Cost | Estimated cost at API rates |


## Free-Text Input

Any input that does not start with `/` is sent to the **advisor agent** as a conversational message. This lets you ask questions, discuss results, and get guidance without running a formal command:

```
urika:my-project> What methods should I try next given the current results?

  [advisor_agent]
  Based on your current results showing linear models plateauing at r2=0.51,
  I recommend trying tree-based approaches...
```

The advisor receives context about your project including the loaded project name, methods tried, and previous conversation history.


## Conversation History

The REPL maintains a rolling conversation history between you and the advisor agent. Each exchange (your message and the advisor's response) is tracked. When you send a new free-text message, the last 10 exchanges are included as context, giving the advisor continuity across the conversation.

Conversation history is cleared when you load a different project.

The conversation context is also available to the `/run` command -- if you have been discussing strategy with the advisor, those instructions are automatically passed to the orchestrator when you start a run.

For a detailed guide on advisor conversations, the suggestion-to-run flow, and how to use instructions to steer agents, see [Advisor Chat and Instructions](06-advisor-and-instructions.md).


## Slash Commands

### Global Commands

Available at all times, regardless of whether a project is loaded.

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands. Project-specific commands are only shown when a project is loaded. |
| `/list` | List all registered projects. The currently loaded project is marked with a diamond. |
| `/new` | Create a new project using the same interactive builder flow as `urika new`. |
| `/project <name>` | Load a project by name. Shows project mode, experiment count, and completion status. |
| `/quit` | Save session usage data and exit the REPL. |
| `/tools` | List all available analysis tools. If a project is loaded, also includes project-specific tools. |
| `/usage` | Show usage stats. With a loaded project: current session and historical totals. Without: usage across all projects. |

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
| `/finalize [instructions]` | Run the finalization sequence: Finalizer Agent, Report Agent, Presentation Agent, and README update. Produces standalone methods, findings, and reproducibility artifacts. Optional instructions guide the finalizer (e.g., `/finalize focus on the ensemble methods`). |
| `/resume` | Resume a paused or failed experiment. Lists resumable experiments and lets you pick which to continue. |
| `/update` | Update the project description, question, or mode interactively. Shows current values, prompts for field, new value, and optional reason. Changes are versioned in `revisions.json`. |
| `/update history` | Show the revision history for the loaded project: all previous changes with timestamps, old/new values, and reasons. |
| `/config` | Configure privacy mode and models for the current project (or global defaults if no project loaded). Interactive guided setup for open, private, or hybrid mode. |
| `/config show` | Show current configuration (project or global). |
| `/config global` | Configure global defaults (used for new projects). |
| `/config global show` | Show global defaults. |


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


## Session Usage Tracking

The REPL tracks usage throughout the session:
- Total tokens consumed (input + output)
- Estimated cost at API rates
- Number of agent calls
- Session duration

Usage is saved to the project's `usage.json` when you exit (via `/quit`, Ctrl+C, or Ctrl+D). This feeds into the `/usage` command and the `urika usage` CLI command for historical tracking.


## Tips

- Use free-text conversation to discuss strategy with the advisor, then `/run` to execute -- the REPL passes your conversation context as instructions to the orchestrator.
- Use `/results` frequently to check the leaderboard during iterative runs.
- The REPL supports standard readline shortcuts (Ctrl+A, Ctrl+E, arrow keys, command history with up/down arrows).
- Exit cleanly with `/quit` or Ctrl+D to ensure usage data is saved.
