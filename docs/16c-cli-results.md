# CLI Reference — Results and Reports

Viewing, results, reports, presentations, criteria, and usage commands. See [Projects](16a-cli-projects.md) for the intro, [Experiments](16b-cli-experiments.md), [Agents](16d-cli-agents.md), and [System](16e-cli-system.md) for the rest of the CLI surface.

## Viewing

### `urika dashboard [PROJECT] [OPTIONS]`

Open a browser-based read-only dashboard for a project. Displays experiments, reports, figures, methods, and criteria in an interactive web interface.

**Options:**

| Option | Description |
|--------|-------------|
| `--port PORT` | Server port (default: a random free port) |
| `--auth-token TOKEN` | Require this bearer token on all requests (`Authorization: Bearer <token>`). `/healthz` and `/static` are exempt. See [Dashboard](18c-dashboard-settings.md) for the full auth flow. |

The dashboard shows:
- **Sidebar** — Curated project tree: experiments (with labbook, artifacts, presentations), projectbook, methods, criteria
- **Content area** — Rendered markdown, syntax-highlighted JSON/Python, zoomable images
- **Footer** — Project stats at a glance

Click any figure to zoom. Presentations open in a new tab. Light/dark mode toggle in the header.

The server runs on localhost only and stops when you exit.

---

## Results and Reports

### `urika results`

Show project results -- either the project leaderboard or runs for a specific experiment.

```
urika results [PROJECT] [--experiment ID]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--experiment ID` | Show runs for a specific experiment instead of the leaderboard |

---

### `urika methods`

List all agent-created methods in a project with their status and top metrics.

```
urika methods [PROJECT]
```

---

### `urika logs`

Show detailed experiment run logs with hypotheses, observations, and next steps.

```
urika logs [PROJECT] [--experiment ID]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--experiment ID` | Specific experiment (prompted if multiple exist) |

---

### `urika report`

Generate labbook reports. Produces notes, summaries, and agent-written narratives.

```
urika report [PROJECT] [--experiment ID]
```

**Options:**

| Option | Description |
|--------|-------------|
| `--experiment ID` | Generate report for a specific experiment |
| `--audience [novice\|standard\|expert]` | Control explanation depth (default: standard) |

When no experiment is specified, you are prompted to choose: a specific experiment, all experiments, or project-level reports.

See [Viewing Results](08-viewing-results.md) for details on report types.

---

### `urika present`

Generate a reveal.js presentation from experiment results.

```
urika present [PROJECT]
```

Prompts you to choose: a specific experiment, all experiments, or a project-level presentation.

**Options:**

| Option | Description |
|--------|-------------|
| `--audience [novice\|standard\|expert]` | Control explanation depth (default: standard) |

---

### `urika criteria`

Show current project success criteria, including version, type, and primary threshold.

```
urika criteria [PROJECT]
```

---

### `urika usage`

Show usage statistics: sessions, tokens, estimated costs, and agent calls.

```
urika usage [PROJECT]
```

Without a project argument, shows totals across all registered projects.


## See also

- [CLI Reference — Projects](16a-cli-projects.md)
- [CLI Reference — Experiments](16b-cli-experiments.md)
- [CLI Reference — Agents](16d-cli-agents.md)
- [CLI Reference — System](16e-cli-system.md)
- [Configuration](14a-project-config.md)
- [Interactive TUI](17-interactive-tui.md)
- [Dashboard](18a-dashboard-pages.md)
