# Interfaces Overview

Urika has three first-class interfaces — CLI, TUI, and dashboard. They share the same project state on disk, so anything you do in one shows up in the others. Pick the one that matches the moment.

## Three interfaces, one set of commands

### CLI — `urika <command>`

For scripts, batch jobs, automation, and quick one-off invocations from a terminal you already have open. Returns plain text by default; `--json` gives you machine-readable output for piping into other tools.

```bash
urika new my-study --data data.csv --question "What predicts X?" --mode hybrid
urika run my-study
urika results my-study
```

When to reach for it: scripting a multi-project sweep, CI integration, remote sessions where you don't want a TUI redrawing.

See [CLI Reference](16-cli-reference.md).

### TUI — `urika`

For exploratory conversation with the orchestrator. Free-text questions, slash commands, persistent chat sessions. Backed by a four-zone Textual layout with live status, agent activity, and tab completion.

```bash
urika
> what should I try first?
> /run
> /pause
> /resume-session
```

When to reach for it: thinking through approach with the advisor, watching a run with rich activity feedback, free-text exploration.

See [Interactive TUI](17-interactive-tui.md).

### Dashboard — `urika dashboard [PROJECT]`

For watching long runs, reviewing results visually, and editing settings through forms. FastAPI + HTMX + Alpine. By default the server picks a free port and prints the URL on startup; override with `--port`. Read-friendly: experiment timelines, leaderboards, log streams, advisor chat, sessions, knowledge browser, methods catalogue.

```bash
urika dashboard my-study
# Console prints e.g. → http://127.0.0.1:54321/projects/my-study
urika dashboard my-study --port 8000   # pin the port
```

When to reach for it: monitoring an autonomous run, sharing results with a collaborator, configuring credentials with a form, picking up a paused session from another machine.

See [Dashboard](18-dashboard.md).

## Common tasks across all three

The cheat sheet — every common task with its CLI / TUI / dashboard equivalent.

| Task                    | CLI                              | TUI                       | Dashboard                  |
|-------------------------|----------------------------------|---------------------------|----------------------------|
| Create a project        | `urika new my-study --data X`    | `/new`                    | + New project (modal)      |
| Run an experiment       | `urika run my-study`             | `/run`                    | + New experiment (modal)   |
| Pause a run             | Ctrl+C (graceful)                | `/pause`                  | Pause button on log page   |
| Stop a run              | Ctrl+C twice                     | `/stop`                   | Stop button on log page    |
| Resume a paused run     | `urika run --resume`             | `/resume`                 | Resume action on experiment|
| Talk to the advisor     | `urika advisor my-study "Q"`     | type plain text or `/advisor` | /projects/<n>/advisor   |
| Resume a chat session   | —                                | `/resume-session [N]`     | Sessions tab → Resume      |
| View leaderboard        | `urika results my-study`         | `/results`                | Project home / Methods page|
| Generate a report       | `urika report my-study`          | `/report`                 | Generate report button     |
| Generate a presentation | `urika present my-study`         | `/present`                | Generate presentation button|
| Finalize the project    | `urika finalize my-study`        | `/finalize`               | Finalize project button    |
| Inspect data            | `urika inspect my-study`         | `/inspect`                | /projects/<n>/data         |
| Configure notifications | `urika notifications`            | `/notifications`          | Settings → Notifications   |
| Send a test alert       | `urika notifications --test`     | —                         | Send test notification button|
| Trash a project         | `urika delete my-study`          | `/delete my-study`        | Settings → Danger zone     |
| Trash an experiment     | `urika experiment delete <id>`   | `/delete-experiment <id>` | Experiment ⋮ menu          |

## How they interoperate

All three read and write the same files under `<project>/`:

- Experiments live at `experiments/<id>/`. Anyone reading them sees the same data — CLI, TUI, dashboard.
- Settings are split: per-project in `urika.toml`, global in `~/.urika/settings.toml`.
- Credentials live in `~/.urika/secrets.env` (or shell env vars).
- Chat sessions are written by REPL/TUI orchestrator chat to `<project>/.urika/sessions/<id>.json`. The dashboard reads them read-only via the Sessions tab.
- The advisor's transcript at `projectbook/advisor-history.json` is shared between CLI `urika advisor`, TUI `/advisor`, and dashboard `/projects/<n>/advisor`.

This means you can fluidly mix: start a run from the CLI, watch it from the dashboard, send `/pause` to a Slack notification button. Each interface is a different lens on the same project state.

## When to use which (rules of thumb)

- **Scripting? CLI.** Plain `urika run` with `--json` is the only thing you need.
- **Exploring?** TUI. Free-text orchestrator chat is what you want.
- **Long-running multi-experiment runs?** Start from CLI or TUI, monitor from dashboard. The dashboard's log streaming + per-agent footer is purpose-built for this.
- **Onboarding a collaborator?** Dashboard. Browser-shareable, no terminal required.
- **Configuring credentials?** Dashboard or `urika notifications`. Either works; dashboard has the **Send test notification** button for instant feedback.

The interfaces are designed to feel like one system. Pick the one that fits, switch when convenient.

---

**Next:** [Core Concepts](03-core-concepts.md)
