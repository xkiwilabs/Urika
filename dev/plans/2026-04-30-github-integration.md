# GitHub Integration — v0.4

**Status:** active (design, awaiting thin-vs-thick decision)
**Date:** 2026-04-30
**Track:** 5 (user-named feature)
**Effort:** thin = ~6-8d, thick = ~24d
**Recommendation:** **thin in v0.4, thick in v0.5**.

## Goal

Optional GitHub integration: connect a GitHub account, optionally
create a repo per project, commit on key events (experiment complete,
advisor exchange, etc.), push manually via slash commands or
automatically when configured. Fully optional — users without GitHub
connected continue working unchanged.

## Foundation that already exists

- **`GITHUB_TOKEN` is a known-secret** (`core/known_secrets.py:27`).
  The vault stores it; no schema work.
- **Tiered vault** with project-tier override (`core/vault.py`) lets a
  user scope a token to one project via `<project>/.urika/secrets.env`
  if they want.
- **Stable event stream** from the orchestrator loop's
  `on_progress(event, detail)` (`orchestrator/loop.py:103`) gives clean
  fire points (`phase`, `agent`, `turn`, `result`).
- **Slash command registry pattern** is one decorator
  (`repl/commands_registry.py`) — adding `/git*` is trivial.
- **`urika config secret`** pattern (`cli/config.py:189`) — `urika
  config github` slots in identically.

## Scope decision: thin vs thick

| Scope | Effort | What you get | What you don't |
|---|---|---|---|
| **Thin** (use `gh` CLI as subprocess) | ~6-8d | Local `git init` + remote create via `gh repo create`; auto-commit on event; slash commands; per-project + per-user TOML; secret regex pre-commit; `.gitignore` writer. | No dashboard "Connect GitHub" button (relies on user having `gh` already authenticated); no device-flow OAuth in-Urika; no audit log UI. |
| **Thick** (pygit2 + device-flow OAuth) | ~24d | All of thin, plus dashboard auth UI, device-flow OAuth (no token-pasting), full Integrations tab, Git tab per project, audit-log viewer, queue-and-retry on offline, dry-run mode. | 4× the effort. |

The remainder of this doc describes the **thick** design (the full
spec). Thin is implemented as a subset: skip `auth.py` device flow,
skip dashboard "Connect" UI, shell out to `gh` for repo creation, keep
everything else.

## Architecture (full / thick)

```
src/urika/integrations/
  __init__.py          # tiny: import-safe even if pygit2 missing
  github/
    __init__.py        # GitHubIntegration facade
    auth.py            # token resolution + device-flow OAuth (thick)
    repo.py            # init/clone/commit/push/pull/status (libgit2 or git CLI)
    events.py          # subscribers wired to orchestrator on_progress
    queue.py           # offline commit/push queue at .urika/git_queue.jsonl
    settings.py        # load/save [integrations.github] from urika.toml + global
    slash.py           # /git, /commit, /push, /pull, /remote handlers
    audit.py           # append-only log at .urika/git_audit.jsonl
```

**Dependency:** prefer `pygit2` (libgit2, no shell-out); fall back to
invoking system `git` CLI via `subprocess`. Both share `repo.py`'s
public API (`init`, `add`, `commit`, `push`, `pull`, `status`,
`current_branch`). Listed as `urika[github]` extra so the core install
stays slim.

**Token storage.** Always via `SecretsVault.set_global("GITHUB_TOKEN",
...)`. Never written to `settings.toml`/`urika.toml`. Resolution
follows the existing process → project → global tier.

**Auth path.** Primary: **GitHub Device Flow** (no token pasting,
scope display in browser, refresh-aware). Secondary: **Fine-grained
PAT** for institutional users behind SSO/IDP. Both produce a
`GITHUB_TOKEN` in the vault; integration is agnostic.

## Per-project settings (`urika.toml`)

```toml
[integrations.github]
enabled = true
repo_url = "https://github.com/alice/dht-target.git"   # empty = local-only
branch = "main"
auto_commit = false
auto_push = false                                       # auto_push implies auto_commit
auto_commit_on = ["experiment_complete", "advisor_exchange", "criteria_updated"]
commit_author = "user"                                  # "user" | "urika-bot"
dry_run = false
include_runs = true                                     # commit experiments/*/runs/*?
gitignore_extra = []                                    # extra patterns user adds
```

## Per-user settings (`~/.urika/settings.toml`)

```toml
[integrations.github]
auto_init_on_new_project = false        # offer / auto-init in `urika new`
default_visibility = "private"
default_branch = "main"
auto_commit_default = false
auto_push_default = false
auto_commit_on_default = ["experiment_complete"]
manage_readme = false                   # let Urika rewrite README.md, off by default
audit_log = true
```

## User flows

### First-time setup

**CLI:** `urika config github`
1. Prints current state (token present? remote scope OK?).
2. Asks: device flow / paste a PAT / cancel.
3. Device flow: prints `https://github.com/login/device` and a code,
   polls `oauth/access_token`, writes `GITHUB_TOKEN` via vault.
   Required scopes: `repo` and `read:user`.
4. Verifies via `GET /user`; shows `Connected as <login>`.
5. Offers: "Set this user's defaults?" — writes `[integrations.github]`
   to `~/.urika/settings.toml`.

**Dashboard:** Settings → new "Integrations" tab next to "Secrets".
Connect button → `POST /api/integrations/github/auth/start`, polls
`GET /api/integrations/github/auth/status` until done.

### New project + repo

- **CLI:** `urika new --git` flag, OR a new interactive step. When yes
  and a token is present → also offer "Create a GitHub remote?" with
  name (defaults to project slug) and visibility.
- **Dashboard:** New Project modal gains `Initialise Git repo` checkbox
  + sub-row `Create remote on GitHub` shown only when token configured.
- Hook point: end of `ProjectBuilder.write_project()` in
  `core/project_builder.py:240` and the same point in
  `dashboard/routers/api.py:179`. Call `integrations.github.repo.init(
  project_dir, ...)` after `write_project` returns.

### Auto-commit on event

Event names — stable enum in `events.py`:

| Event | Fires when | Default in list? |
|---|---|---|
| `experiment_start` | first turn of a new experiment | no (chatty) |
| `turn_complete` | after each orchestrator turn | no |
| `experiment_complete` | `complete_session()` returns | **yes** |
| `experiment_failed` | session ends in `failed` | yes |
| `advisor_exchange` | advisor agent produces a reply | no |
| `criteria_updated` | criteria.append fires | yes |
| `method_registered` | new method recorded | no |
| `report_written` | report agent finishes | yes |
| `presentation_written` | presentation agent finishes | yes |
| `finalize_complete` | finalizer agent finishes | yes |
| `manual` | user typed `/commit` | always |

Subscriber wiring: `events.py` exposes `wrap_progress(callback,
project_dir)` that returns a `(event, detail) → None` callable.
`cli/run.py` and `dashboard/routers/api.py` (the run handler) wrap
their existing `on_progress` callback with it. The wrapper inspects
`progress("phase", "Experiment completed")` etc. and translates to
integration events. **The orchestrator stays untouched** — no API
change.

### Commit-message format

```
[urika:experiment_complete] exp-<id> — <one-line method/result>

Project: <name>
Turn: <n>/<max>
Cost: $<x>  Tokens: in/<>/out/<>
URL: urika://<project>/experiments/<exp_id>

Co-Authored-By: Urika Bot <urika-bot@noreply.urika.dev>
```

`commit_author = "user"` uses `git config user.email` (recommended);
`"urika-bot"` uses a synthetic identity. Co-author trailer always
added.

### Slash commands

| Command | Description |
|---|---|
| `/git` | Show status: connected user, remote, branch, dirty count, queue depth, last 5 commits |
| `/git status` | Verbose status |
| `/git commit "<msg>"` | Stage + commit everything Urika manages, no push |
| `/git push` | Push current branch; surfaces non-fast-forward errors verbatim |
| `/git pull` | Fetch + ff-only merge; refuse if local diverges |
| `/git remote add <url>` | Set/replace `origin` |
| `/git remote create <name>` | Create on GitHub via API, set as origin |
| `/git auto on/off` | Toggle `auto_commit`/`auto_push` for current project |
| `/git log` | Last 20 Urika-authored commits |

Aliases: `/commit` = `/git commit`, `/push` = `/git push`. Both
REPL/TUI and dashboard get equivalents. Dashboard routes:
`GET /api/projects/<n>/git/status`, `POST /api/projects/<n>/git/{commit,
push,pull,remote}`. New "Git" tab on the project page surfaces status,
recent commits, queue, settings toggles, and a manual commit button.

### Conflict handling

| Failure | Behaviour |
|---|---|
| Offline (DNS/connect fail) | Commit succeeds locally; push appended to `.urika/git_queue.jsonl`. Retry on next event or `/git push`. |
| Auth expired (`401`) | Queue, mark project as `auth_required`; show banner in dashboard + `print_warning` in CLI. Disable subsequent auto-push. |
| Push rejected non-ff | Refuse to auto-merge. Notify; user runs `/git pull` manually. |
| Repo not initialized + auto-commit on | Initialise on first event (logged, not silent); skip remote until configured. |
| Token lacks scope | Local commit still works; remote ops skipped with one-shot warning. |
| Network slow | 10s timeout; queue. |

Queue format: one JSON object per line. A single retry pass runs at
the start of every event handler.

### Privacy / never-commit

Hard-coded in `.gitignore` writer, not user-overridable:
- `**/.urika/secrets.env`, `**/.urika/secrets-meta.toml`,
  `**/.urika/secrets-index.txt`.
- `*.pem`, `*.key`, `*_rsa`, `*_ed25519`, `.env`.

Defaults users can override (`gitignore_extra`):
- `data/raw/` (often PHI/PII or huge).
- `*.parquet`, `*.h5`, `*.pkl` over a configurable size.

**Pre-commit hardening:** `repo.py:commit()` runs a regex sweep for
high-entropy strings on staged blobs (`sk-...`, `ghp_...`, `gho_...`,
AWS-key shape) and aborts with `[urika:secret-detected]` if any match.
Same regexes the dashboard already knows about (`mask_value`).

### Disconnect / disable

- `urika config github --disconnect` deletes the vault key, clears the
  project's `[integrations.github]` block, leaves `.git/` and the
  local repo untouched.
- Per-project disable: `enabled = false` in `urika.toml`.
- Global disable: `auto_init_on_new_project = false` plus
  `auto_commit_default = false`.

## Security

- Token in vault only; `mask_value` on any display surface.
- Minimum scopes: `repo` (private + public) and `read:user`. Never
  request `admin:org`, `delete_repo`, `gist`.
- Audit log `.urika/git_audit.jsonl` records every action with
  timestamp, sha, branch, remote, success/error. Visible in
  dashboard's Git tab; never auto-pushed.
- Per-project `enabled = false` overrides global defaults.
- `dry_run = true` performs every step but stops at `git push` (and
  writes the planned message into the audit log) so users can verify
  cycles before flipping `auto_push`.

## Effort estimate (thick)

| Component | Days |
|---|---|
| `repo.py` (init/commit/push/pull/status, both pygit2 + CLI fallbacks, secret-scan) | 4 |
| `auth.py` (device flow + PAT + scope check) | 2 |
| `events.py` + `queue.py` (event mapping, retry queue, dry-run) | 2 |
| `settings.py` plus `urika.toml` + global TOML schema integration | 1 |
| CLI surface: `urika config github`, `urika new --git`, `--create-remote` | 2 |
| Slash commands `/git*` (REPL + TUI wiring) | 1.5 |
| Dashboard: API routes (8) | 2 |
| Dashboard: Integrations tab + Project Git tab + New-project checkbox | 3 |
| `audit.py` + Git audit viewer in dashboard | 1 |
| `.gitignore` writer + secret regex sweep | 0.5 |
| Tests (unit + integration with a tmp git remote, fakes for GitHub API) | 4 |
| Docs (`docs/integrations/github.md`, CHANGELOG, screenshots) | 1 |
| **Total** | **~24 dev-days** |

## Effort estimate (thin)

Strip `auth.py` device flow (~2d), strip dashboard auth UI (~3d), strip
audit log UI (~1d), use `gh` CLI subprocess for repo creation
(~half-day net change). Approximately **~6-8 days**.

## Open questions

1. **Commit cadence default.** `experiment_complete` only (clean) vs
   include `turn_complete` (chatty but full). Recommendation: clean by
   default, opt-in chatty via `auto_commit_on`.
2. **Default visibility.** Recommendation: private — researchers
   default to confidential.
3. **README management.** Off by default; opt-in `manage_readme = true`
   to let `readme_generator.write_readme` rewrite on every
   `experiment_complete`.
4. **Branching.** Recommendation: commit to `main` directly, but offer
   `branch_per_experiment = false` flag so heavy users can flip to one
   branch per experiment with auto-PR to `main` on
   `experiment_complete`.
5. **Multi-remote.** Out of scope for v0.4. Architecture is
   provider-agnostic in `repo.py` (plain Git ops); only `auth.py` and
   `events.py:create_remote` are GitHub-specific. Add `gitlab/`,
   `gitea/` siblings in v0.5+.
6. **Large artifacts.** v0.4: exclude raw data; commit small figures
   only. Add `lfs.enabled` flag in v0.5 once Git LFS install
   requirement is documented.

## Files referenced

- `src/urika/core/workspace.py` — hook point at end of
  `create_project_workspace`.
- `src/urika/core/project_builder.py:240` — hook point after
  `write_project()` returns.
- `src/urika/cli/project_new.py:308-323` — where `--git` interactive
  prompt lands.
- `src/urika/cli/run.py:133` — wrap `on_progress` here for events.
- `src/urika/orchestrator/loop.py:103,608,772,786` — `progress(...)`
  callsites.
- `src/urika/core/vault.py:558` — `set_global` is the only token-write
  path.
- `src/urika/core/known_secrets.py:27` — `GITHUB_TOKEN` already
  declared; description should be updated.
- `src/urika/cli/config.py:189-205` — pattern to follow for `urika
  config github`.
- `src/urika/dashboard/routers/api.py:84,179,1957` — locations to add
  git routes and the New-project hook.
- `src/urika/dashboard/templates/global_settings.html:159` — add
  `Integrations` tab next to `Secrets`.
- `src/urika/repl/commands_registry.py` — register slash commands.
