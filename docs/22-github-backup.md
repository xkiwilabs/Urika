# GitHub Backup

GitHub auto-backup turns each Urika project into a git repository and (optionally) auto-pushes after every successful `urika run` / `finalize` / `build-tool`. Shipped in **v0.6.0** (2026-05-31).

**Design philosophy — backup, not collaboration.** Urika never sees a GitHub credential, never calls the GitHub API, and stays provider-agnostic. The `urika github` commands shell out to the system `git` binary (and optionally `gh`) so your existing auth (HTTPS+PAT in a credential helper, SSH key, or `gh auth login`) does all the authentication. Works against GitHub, GitLab, Gitea, Bitbucket, or self-hosted git remotes.

See also [Project Configuration](14a-project-config.md) for the `[github]` block and [CLI Reference — System](16e-cli-system.md#urika-github) for the command summary.


## Quickstart

```bash
# Initialise an existing project as a git repo (no remote yet)
urika github init my-project

# Attach an existing remote you've already created on the host
urika github init my-project --remote https://github.com/you/my-project.git

# Or — one shot via the gh CLI (creates a fresh private repo + pushes)
urika github init my-project --create

# Manual push from then on
urika github push my-project

# Or set [github] auto_push = true in urika.toml and forget about it
```


## Commands

All four subcommands take an optional `PROJECT` argument and resolve the project the same way the rest of the CLI does (prompts when omitted in interactive shells).

### `urika github init`

Initialise the project as a git repo. Writes the researcher-safe `.gitignore` managed block (see [`.gitignore` template](#gitignore-template) below), stages everything, and creates the first commit. Idempotent — re-running on an already-initialised project is safe.

```
urika github init [PROJECT] [--remote URL] [--create] [--public]
```

| Flag | Purpose |
|---|---|
| `--remote URL` | Set `origin` to `URL`. Updates the URL if `origin` already exists. |
| `--create` | Use the `gh` CLI to create a fresh GitHub repo named after the project, set `origin`, and push in one shot (`gh repo create <name> --private --source <dir> --push`). Requires `gh` installed and authenticated; falls back gracefully with an install hint and exit code 2 if not. |
| `--public` | With `--create`: make the new repo public. Default is private. |

When `--create` succeeds the command returns immediately — `gh repo create --push` already lands the initial commit, so the regular `commit_all` step is skipped to avoid duplicates.

### `urika github push`

Stage everything, run the pre-commit secret scanner, commit (with the `urika-event: manual` trailer), and push to `origin`.

```
urika github push [PROJECT]
```

If the scanner finds a known secret pattern the push aborts with exit code 3 before the commit lands, prints `[urika:secret-detected] <file>:<line>` for each match (with a masked preview), and resets the index so your working tree isn't left in a half-staged state. See [Pre-commit secret scanner](#pre-commit-secret-scanner) below for the pattern list.

On push failure the verbatim `git` stderr is printed and the local commit is left intact for you to retry.

### `urika github pull`

Fetch the current branch from `origin` and fast-forward-only merge. Refuses on divergence — if local has commits that aren't on the remote (or the remote has diverged in a non-fast-forward way), the user must resolve it themselves with their own git tooling. Urika does not auto-merge.

```
urika github pull [PROJECT]
```

### `urika github status`

Print a one-screen snapshot of the project's git state — branch, remote URL, dirty file count, last commit, and the five most recent commits with their `urika-event:` tag in brackets when present.

```
urika github status [PROJECT]
```

When the project isn't yet a git repo, prints a hint pointing at `urika github init`.


## Pre-commit secret scanner

Both `urika github push` and the auto-push hook run a regex sweep over the **staged blobs** (read via `git show :<path>`) before the commit lands, catching secrets that are already staged even if you've since removed them from the working tree. Binary files are skipped via a NUL-byte heuristic.

The scanner reports the first match per line — that's enough for the user to find the leak.

| Pattern | Catches |
|---|---|
| `anthropic_api_key` | `sk-ant-` + 32+ alphanum/`_-` |
| `github_pat` | `ghp_` + 36 alphanum |
| `github_oauth` | `gho_` + 36 alphanum |
| `github_user_to_server` | `ghu_` + 36 alphanum |
| `github_server_to_server` | `ghs_` + 36 alphanum |
| `aws_access_key_id` | `AKIA` + 16 uppercase/digit |
| `openai_api_key` | `sk-` + 40+ alphanum (Anthropic shape is tested first so `sk-ant-...` reports as Anthropic) |

On a hit:

- The CLI prints `[urika:secret-detected] <file>:<line> (<pattern>) match: <masked>` per leak (first 8 chars + `...` + last 4 of the token), aborts with **exit code 3**, and resets the index.
- The dashboard `POST /api/projects/<name>/git/push` endpoint returns **HTTP 409** with the same match details.

Remediation: remove the secret from the file or add the file to `.gitignore`, then re-run.


## Auto-push hook

The hook is **opt-in per project** via the `[github]` block in `urika.toml`. When enabled, the tail of `urika run`, `urika finalize`, and `urika build-tool` calls a defensive helper that runs the same scan → commit → push sequence as the CLI's `push` command.

```toml
# urika.toml
[github]
auto_push = true
auto_push_after = ["run", "finalize", "build-tool"]   # default set
gitignore_extra = []                                    # extra patterns appended inside the managed block
```

Each event uses a per-event commit subject and writes a `urika-event: <event>` trailer to the commit body. `urika github status` parses the trailer so you can see which commits were created by which command.

| Event | Commit subject |
|---|---|
| `run` | `urika: experiment run completed` |
| `finalize` | `urika: finalized project` |
| `build-tool` | `urika: added/updated project tool` |
| `manual` | `urika: project state` |

**Failure modes** (the helper is wrapped in a top-level `try/except` so an auto-push problem can never break the host command):

- `auto_push = false` → skipped silently.
- Event not in `auto_push_after` → skipped silently.
- Project not a git repo → warning printed pointing at `urika github init`.
- Secret detected → aborts the push (no commit), prints the same `[urika:secret-detected]` lines as the CLI, and leaves a note to re-run after fixing.
- Push fails → prints the verbatim `git` stderr plus a retry hint pointing at `urika github push`.

Only `run` / `finalize` / `build-tool` are wired today. The `run` wiring covers both the meta-experiment and single-experiment success paths, both gated on `run_status == "completed"` so paused / stopped / failed runs do not trigger.


## At project-creation time

`urika new` accepts opt-in / opt-out flags so the GitHub remote can be created in the same step as the project itself.

```
urika new <name> [--github | --no-github] [--public]
```

Resolution order:

1. Explicit `--github` or `--no-github` wins.
2. Otherwise, the global preference `[preferences] github_auto_create` in `~/.urika/settings.toml` (default `false`) decides.
3. When the preference path is taken and `--public` was not passed, the default visibility comes from `[preferences] github_auto_create_visibility` (default `"private"`).

Failure is **non-fatal** — the project itself was already written, so the error and `gh` install hint are printed and the command returns cleanly.


## Global preferences

```toml
# ~/.urika/settings.toml
[preferences]
github_auto_create = true                  # default for `urika new`
github_auto_create_visibility = "private"  # "private" | "public"
```


## `.gitignore` template

`urika github init` writes a researcher-safe default between managed-block markers:

```
# >>> urika: managed block — do not edit between markers >>>
# Urika internal state — never commit (secrets, sessions, meta)
.urika/
*.lock

# Python
__pycache__/
*.pyc
.venv/
venv/
.tox/

# Credentials / private keys (never commit, even if you remove other
# patterns from this list)
.env
*.pem
*.key
*_rsa
*_ed25519

# Research data — researcher-safe default exclusion. Remove the lines
# below (or override via [github] gitignore_extra in urika.toml) if
# your project's raw data is safe to commit.
data/raw/
*.parquet
*.h5
*.pkl
*.joblib
# <<< urika: managed block <<<
```

Behaviour:

- **Fresh project** — writes a new `.gitignore` containing just the managed block.
- **Existing `.gitignore` without an Urika block** — appends the block at the end, preserving everything you already have.
- **Existing `.gitignore` with an Urika block** — replaces the block in place, preserving content above and below it.

Add project-specific patterns via `[github] gitignore_extra = ["pattern1", "pattern2"]` in `urika.toml`; they get appended inside the managed block on the next `urika github init`.


## `urika-event:` trailer

Every commit Urika creates (via `urika github push`, the auto-push hook, and `--create`) carries a structured trailer in its commit body:

```
urika-event: run
urika-version: 0.6.0
```

`urika github status` and the dashboard Git tab parse this trailer and surface the event as a chip per commit. To filter Urika-created commits from your own commits when working on the project history:

```bash
git log --grep="urika-event:" --oneline
```


## Dashboard Git tab

The dashboard surfaces the same state at `/projects/<name>/git`:

- Branch / remote URL / dirty count / last commit panel
- "Push now" button (POSTs to `/api/projects/<name>/git/push`, same secret-scan semantics; returns HTTP 409 with match details on a hit)
- Recent commits list with the `urika-event:` chip per commit
- "Initialise" form (with optional remote URL) when the project isn't yet a git repo, POSTing to `/api/projects/<name>/git/init`

All state-changing routes go through the v0.4.5.1 CSRF middleware (cross-origin requests return 403). See [Dashboard — Pages](18a-dashboard-pages.md) for the route table and [Dashboard — Operations](18b-dashboard-operations.md) for the broader endpoint reference.


## What's out of scope

- **Device-flow OAuth and a "Connect GitHub" experience** — preserved in `dev/archive/2026-04-30-github-integration.md`, deferred to v1.1+ if real demand surfaces.
- **GitHub-API-driven repo creation** — use `gh` CLI (`--create`) instead.
- **Audit log viewer** in the dashboard.
- **Offline commit queue** + retry-next-event.
- **`dry_run` mode** that stops before push.
- **README auto-management** on every event.
- **Branch-per-experiment / auto-PR workflows.**
- **LFS support** for large artifacts.
- **Multi-remote per project** — Urika manages exactly one `origin`; add more remotes manually with raw `git` if needed.
