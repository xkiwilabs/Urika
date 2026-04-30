# Secrets Handling — Where API Keys Should Live

> **Status:** Proposal / discussion. Not yet implemented. Companion to
> the future-feature priorities list — slot in once you're ready.

## Where things stand today

**Urika does NOT load any `.env` file.** No `dotenv` import anywhere in
`src/urika/`. The user's other tooling (`models.py` in
LLM-Response-Coding) uses `python-dotenv`, but Urika doesn't.

What Urika has on disk in `~/.urika/`:

```
~/.urika/
├── projects.json            (registry of projects)
├── settings.toml            (global config, NO secrets)
├── deletion-log.jsonl       (trash audit trail)
└── trash/                   (deleted projects)
```

What Urika reads from environment:

- `URIKA_HOME` — overrides `~/.urika` location
- `URIKA_PROJECTS_DIR` — default project-creation directory
- API keys named in `[privacy.endpoints.<name>].api_key_env` — read at
  agent-spawn time via `os.environ.get(<that name>)`. The TOML stores
  the env var **name**, never the value.
- `ANTHROPIC_API_KEY` (when present) — used by the Claude SDK adapter.
- Anything else the underlying SDK reads.

So **today, secrets live in the user's shell environment**. They get
there via:

1. Manual export: `export URIKA_API_KEY=...`
2. `~/.bashrc` / `~/.zshrc`: persistent across shell sessions
3. systemd / launchd unit files: persistent across reboots
4. The user's other-app `.env` files, IF those happen to be sourced
   before `urika dashboard` starts

## What's wrong with this

It works, but it has friction:

- **Discoverability is bad.** Nothing tells a new user "you need to set
  these N env vars before private mode will work."
- **Setting requires terminal knowledge.** A researcher who installs
  Urika via `pip` and opens the dashboard has no UI path to "configure
  my API key".
- **Multi-SDK migration will multiply this.** If you add Claude API
  keys (for users who don't want subscription), OpenAI, Google, plus
  per-endpoint private keys, that's potentially 5–10 named env vars
  per setup. Telling everyone "open a terminal and `export ...`"
  doesn't scale.
- **No place to store cloud subscription tokens** (if/when Anthropic
  reopens third-party OAuth). Currently the Claude SDK adapter spawns
  the `claude` CLI which uses its own login state — fine, but a future
  direct-API path needs somewhere to put the token.

## Proposed model

Three tiers, from lowest-to-highest preference order at lookup time:

### Tier 1 — Process environment (existing)

`os.environ` is checked first. So a user who already exports
`URIKA_API_KEY=...` in their shell sees zero behavior change. This
preserves backward compat and the standard CI pattern (`env`-injected
secrets).

### Tier 2 — Project-local secrets (new)

`<project>/.env` (chmod 600, gitignored by default). Loaded when a
project is loaded. Overlays Tier 3 globals for that project only.

Use case: project-specific endpoint creds (e.g. one project uses a
shared lab vLLM key, another uses a personal Anthropic key).

### Tier 3 — Global secrets store (new)

Two implementations behind a single interface:

- **Preferred:** OS keyring (`keyring` package — macOS Keychain, Linux
  Secret Service, Windows Credential Manager). Encrypted at rest by
  the OS. No file permission gotchas.
- **Fallback:** `~/.urika/secrets.toml` (chmod 600, never written to
  the regular `settings.toml`). Used when keyring isn't available
  (headless server, no dbus, etc.).

Use case: cloud SDK keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GOOGLE_API_KEY`) and the default private-endpoint key. Set once,
used by every project.

### Lookup helper

```python
def get_secret(name: str, project_path: Path | None = None) -> str | None:
    """Resolve a secret by env-var name. Order: process env → project
    .env → global secrets store."""
    val = os.environ.get(name)
    if val:
        return val
    if project_path:
        val = _read_project_env(project_path).get(name)
        if val:
            return val
    return _read_global_secrets().get(name)
```

Every place that currently does `os.environ.get("URIKA_API_KEY")`
becomes `get_secret("URIKA_API_KEY", project_path)`. The change is
mechanical.

## UI surfaces

### Global Settings → Secrets tab (new)

Lists known secret names (well-known cloud SDKs + any
`api_key_env` referenced by global endpoints). For each:

- Status: `✓ set` / `✗ unset` / `inherited from process env`
- Set / Update button → modal with masked password input, eye-toggle
  to peek
- Clear button → removes from the global store (process env still
  wins if exported)

The "✓ Set" status becomes a green check on the existing Privacy tab
endpoint rows next to the API key env var name.

### Project Settings → Secrets tab (optional, secondary)

Same shape, but writes to `<project>/.env`. Project-scoped overrides.

### "Test endpoint" round-trip (already queued, task #115)

Once secrets are settable from the UI, the Test button can actually
use the configured key to fire a roundtrip prompt — closing the loop
end-to-end without ever asking the user to drop to a terminal.

## What this gives you

- **Single end-to-end UI flow** for "set up private model": configure
  endpoint → set API key (in same UI) → Test → run experiment.
- **Multi-SDK ready:** when you add Codex / Pi adapters, each gets a
  named secret in the global store with the same UI affordance.
- **Subscription vs API key choice for Claude:** users who prefer
  pay-as-you-go set `ANTHROPIC_API_KEY` via UI; users on subscription
  do nothing and the SDK adapter spawns the `claude` CLI as today.
- **Discoverable:** the Secrets tab is a visible inventory of what
  Urika knows about and which ones have values.
- **Safe:** OS keyring is the right primitive; the chmod-600 fallback
  is acceptable for local-only setups.

## Tradeoffs / non-goals

- **`keyring` adds a dependency.** It's well-maintained but introduces
  platform-specific behavior. The `~/.urika/secrets.toml` fallback
  handles the headless case.
- **Project `.env` files can leak into git.** Mitigation: include
  `.env` in the project template's auto-generated `.gitignore`.
- **No automatic secret rotation, no expiry tracking.** Out of scope.
  Users rotate manually if they need to.
- **No master password / encryption beyond OS keyring.** A locked
  `~/.urika/secrets.toml` is only as secure as the user's home
  directory permissions. Acceptable for the personal-tool use case.

## Effort estimate

~1 week:
- Day 1: secrets store interface + keyring/file backends + tests
- Day 2: `get_secret()` helper, replace existing `os.environ.get`
  callsites, backward-compat tests
- Day 3: Global Settings → Secrets tab (UI + API endpoints)
- Day 4: Project Settings → Secrets tab + `.env` loader
- Day 5: Round-trip test endpoint (folds in task #115), docs, smoke
  checklist

## Recommendation

Yes, do this — but not now. Slot it in:

1. **After** orchestrator memory polish (#2 in feature priorities)
2. **Before** project memory + agent instructions (#3)
3. **Before** runtime abstraction (#4) — because each new adapter
   needs its own secret, and the secrets store should exist first

In the meantime: the env-var-only model works. Document the export
commands clearly in `docs/` and the dashboard's inline help text
(already done for the api_key_env field).

This file is the persistent record so we can pick it up cleanly when
the time comes.
