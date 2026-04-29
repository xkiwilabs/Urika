# Secrets Vault — Implementation Plan (v0.4)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Ship a generic named-secrets vault so users can manage ANY credential Urika or its agents need — LLM provider keys, HuggingFace tokens, third-party tool credentials, project-specific endpoint creds — through a single dashboard UI without dropping to the terminal.

**Architecture:** Three-tier resolution at lookup time:
1. **Process env** (`os.environ`) — wins; preserves current behavior + standard CI/`export` pattern.
2. **Project-local** `<project>/.urika/secrets.env` (chmod 0600, gitignored) — for project-specific creds.
3. **Global** — OS keyring (preferred) with `~/.urika/secrets.env` (chmod 0600) fallback.

**Tech stack:** Stdlib for the file fallback; `keyring` package as optional dep for OS-level encryption (lazy-imported, graceful degrade if absent). Dashboard UI is FastAPI + HTMX + Alpine, same as the rest of v0.3.

**Companion to:** `dev/plans/2026-04-27-secrets-handling-proposal.md` (the design doc that motivated this plan).

**Out of scope (decided):**
- Master-password encryption beyond what the OS provides.
- Automatic secret rotation, expiry tracking, or revocation.
- Cross-machine sync (the user is responsible for setting on each machine).
- LLM-readable secrets (the agent should never see secret VALUES; only know whether they EXIST by name, see Phase D).

---

## Why a generic vault, not just an "API key manager"

Every credential Urika needs follows the same pattern: store the secret value somewhere safe; give it a name; agents/tools that need it read by name from `os.environ` at runtime. The pattern works for:

| Secret | Used by | Triggered when |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic SDK adapter | Every Claude agent call |
| `OPENAI_API_KEY` | OpenAI adapter (planned v0.5) | Every OpenAI call |
| `GOOGLE_API_KEY` | Google ADK adapter (planned v0.5) | Every Gemini call |
| `HUGGINGFACE_HUB_TOKEN` | Tool builder agent | Downloading gated models / datasets / embeddings |
| `WANDB_API_KEY` | Tool builder | Logging experiments to W&B |
| `KAGGLE_USERNAME` + `KAGGLE_KEY` | Data agent | Pulling competition datasets |
| `OPENROUTER_API_KEY` / `TOGETHER_API_KEY` / `REPLICATE_API_TOKEN` / etc. | Custom agent-built tools | Routing through alt providers |
| `GITHUB_TOKEN` | Literature agent | Pulling private repos |
| `S3_*` / `GCS_*` / `AZURE_STORAGE_*` | Project data sources | Loading data from cloud storage |
| `URIKA_EMAIL_PASSWORD` / `SLACK_BOT_TOKEN` / `TELEGRAM_BOT_TOKEN` / `SLACK_APP_TOKEN` | Notifications subsystem | Already uses this pattern (v0.3) |
| Any custom env-var name | Whatever the tool builder writes | When the agent decides a new tool needs an external API |

The vault doesn't need to know about these specifically — it just stores **arbitrary `KEY=value` pairs** under a single management surface. Discovery + which-tools-need-which is a separate concern handled in Phase D.

---

## Phase A — Storage layer

### Task A.1: `urika.core.vault` module + tiered resolution

**Files:**
- Create: `src/urika/core/vault.py` — module with the API below.
- Create: `tests/test_core/test_vault.py` — full unit coverage of all three tiers.

**API:**

```python
# src/urika/core/vault.py
from pathlib import Path
from typing import Optional, Mapping

class SecretsVault:
    """Tiered secrets resolver: process env → project .env → global store.

    Process env always wins so existing exports / CI patterns keep
    working unchanged. Project-local overrides global.
    """

    def __init__(
        self,
        project_path: Optional[Path] = None,
        global_path: Optional[Path] = None,
    ) -> None: ...

    def get(self, name: str) -> Optional[str]:
        """Resolve a secret by name. Returns None if not set in any tier."""

    def list_keys(self) -> list[str]:
        """Return all secret names known to the vault (union across tiers).
        Values are not returned — names only, for discovery."""

    def list_with_origins(self) -> list[dict]:
        """Return [{name, origin: "process"|"project"|"global", set: bool}, ...].
        The dashboard uses this to render the Secrets tab with origin badges."""

    def set_global(self, name: str, value: str) -> None:
        """Write to the global store. Updates os.environ in-process."""

    def set_project(self, name: str, value: str, project_path: Path) -> None:
        """Write to <project>/.urika/secrets.env."""

    def delete_global(self, name: str) -> bool:
        """Remove from global store. Returns True if present."""

    def delete_project(self, name: str, project_path: Path) -> bool:
        """Remove from project store."""
```

**Backend selection logic for global tier:**

```python
def _global_backend() -> "SecretsBackend":
    """Try OS keyring first; fall back to file. Cached per-process."""
    try:
        import keyring
        keyring.get_password("urika", "__probe__")  # exercise the backend
        return KeyringBackend()
    except (ImportError, keyring.errors.KeyringError, Exception):
        return FileBackend()
```

**Two backends:**

```python
class KeyringBackend:
    """OS keyring backend (macOS Keychain / Linux Secret Service / Windows Credential Manager)."""
    SERVICE_NAME = "urika"

    def get(self, name: str) -> Optional[str]:
        return keyring.get_password(self.SERVICE_NAME, name)

    def set(self, name: str, value: str) -> None:
        keyring.set_password(self.SERVICE_NAME, name, value)

    def delete(self, name: str) -> bool:
        try:
            keyring.delete_password(self.SERVICE_NAME, name)
            return True
        except keyring.errors.PasswordDeleteError:
            return False

    def list_keys(self) -> list[str]:
        # Keyring doesn't list — we maintain a sidecar index file at
        # ~/.urika/secrets-index.txt with just the names. Set/delete
        # update it; get/list read from it.
        ...

class FileBackend:
    """KEY=VALUE file at ~/.urika/secrets.env, chmod 0600.
    Reuses existing urika.core.secrets — refactor that module to be the
    file backend for this new vault."""
    ...
```

**Step 1 — Tests (TDD):**

```python
class TestProcessEnvWins:
    def test_returns_value_from_os_environ(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MY_KEY", "from-env")
        vault = SecretsVault(global_path=tmp_path / "global.env")
        # Even with global set, process env wins
        vault.set_global("MY_KEY", "from-global")
        assert vault.get("MY_KEY") == "from-env"


class TestProjectOverridesGlobal:
    def test_project_wins_over_global(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MY_KEY", raising=False)
        proj = tmp_path / "proj"
        proj.mkdir()
        vault = SecretsVault(project_path=proj, global_path=tmp_path / "global.env")
        vault.set_global("MY_KEY", "global-value")
        vault.set_project("MY_KEY", "project-value", project_path=proj)
        assert vault.get("MY_KEY") == "project-value"


class TestGlobalFallback:
    def test_returns_global_when_no_process_or_project(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MY_KEY", raising=False)
        vault = SecretsVault(global_path=tmp_path / "global.env")
        vault.set_global("MY_KEY", "global-value")
        assert vault.get("MY_KEY") == "global-value"


class TestNotFound:
    def test_returns_none_when_unset_everywhere(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MY_KEY", raising=False)
        vault = SecretsVault(global_path=tmp_path / "global.env")
        assert vault.get("MY_KEY") is None


class TestListWithOrigins:
    def test_origin_badges_per_secret(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FROM_ENV", "x")
        vault = SecretsVault(global_path=tmp_path / "global.env")
        vault.set_global("FROM_GLOBAL", "y")
        items = vault.list_with_origins()
        origins = {i["name"]: i["origin"] for i in items}
        assert origins["FROM_ENV"] == "process"
        assert origins["FROM_GLOBAL"] == "global"


class TestKeyringBackendSelection:
    def test_falls_back_to_file_when_keyring_unavailable(self, monkeypatch):
        monkeypatch.setattr("urika.core.vault._keyring_available", lambda: False)
        from urika.core.vault import _global_backend, FileBackend
        assert isinstance(_global_backend(), FileBackend)


class TestPermissions:
    def test_file_backend_chmods_to_0600(self, tmp_path):
        backend = FileBackend(path=tmp_path / "secrets.env")
        backend.set("X", "y")
        assert oct((tmp_path / "secrets.env").stat().st_mode & 0o777) == "0o600"
```

**Step 2 — Implement** with the Keyring + File backends + the index file. Keep it stdlib-only except for the optional `keyring` import.

**Step 3 — Verify:** `pytest tests/test_core/test_vault.py -v` all green.

**Step 4 — Commit:** `feat(core): tiered secrets vault (process env / project / keyring or file)`

### Task A.2: Backward-compat — refactor `urika.core.secrets` to use the vault

**Files:**
- Modify: `src/urika/core/secrets.py` — `save_secret`, `get_secret`, `load_secrets`, `list_secrets` now delegate to `SecretsVault`.
- Existing tests: should keep passing without change.

The existing module has a chmod-0600 file at `~/.urika/secrets.env`. The new vault uses the same file as its FileBackend. So no migration needed — existing files are picked up by the vault.

`load_secrets()` becomes: read the global FileBackend (or keyring) and populate `os.environ` for keys that aren't already set. Same semantics.

`save_secret(name, value)` becomes: `vault.set_global(name, value)`.

`get_secret(name)` becomes: `vault.get(name)`.

`list_secrets()` becomes: `vault.list_keys()` (with values masked).

**Step 1 — Run all existing tests** that touch `urika.core.secrets`. They should still pass.

**Step 2 — Commit:** `refactor(core): secrets module now delegates to SecretsVault`

---

## Phase B — Dashboard UI

### Task B.1: New Settings → Secrets tab + API endpoints

**Files:**
- Modify: `src/urika/dashboard/templates/global_settings.html` — add a new tab.
- Modify: `src/urika/dashboard/routers/api.py` — new endpoints.
- Modify: `src/urika/dashboard/routers/pages.py` — pass vault state to the template.
- Test: `tests/test_dashboard/test_secrets_tab.py` (new).

**Tab content:**

```
Settings → Secrets

Manage credentials Urika and your agents need (API keys, tokens,
passwords). Values are stored encrypted in your OS keyring when
available, or in a chmod-0600 file at ~/.urika/secrets.env otherwise.
Process environment variables always take precedence — exports in
your shell are never overwritten.

[Add new secret]

┌──────────────────────────────────────────────────────────────┐
│ ANTHROPIC_API_KEY                  [process env] [Test]      │
│ Required for the Anthropic adapter.   sk-ant-***...***WXYZ   │
│                                                  [Clear]     │
├──────────────────────────────────────────────────────────────┤
│ HUGGINGFACE_HUB_TOKEN              [global keyring] [Edit]   │
│ For HuggingFace gated models / datasets.  hf_***...***1234   │
│                                                  [Delete]    │
├──────────────────────────────────────────────────────────────┤
│ MY_CUSTOM_VISION_API           [unset]            [Set]     │
│ Used by tool: vision_caption.py (auto-detected)              │
└──────────────────────────────────────────────────────────────┘
```

**Origin badges:**
- `[process env]` (yellow) — set in shell; cannot be cleared from UI.
- `[global keyring]` / `[global file]` (green) — managed here.
- `[project]` (blue) — set per-project; only shown on project secrets tab.
- `[unset]` (gray) — known name (registered by an agent or a default), no value yet.

**Form for "Add new secret" / "Edit secret":**

```html
<form>
  <div class="form-row">
    <label>Name (env-var name)</label>
    <input type="text" name="secret_name" placeholder="e.g. HUGGINGFACE_HUB_TOKEN" required>
    <small>Uppercase letters, digits, underscores. Same name your agent / tool reads via os.environ.</small>
  </div>
  <div class="form-row">
    <label>Value</label>
    <input type="password" name="secret_value" required>
    <button type="button" onclick="togglePeek()">👁 Show</button>
  </div>
  <div class="form-row">
    <label>Description (optional)</label>
    <input type="text" name="secret_description" placeholder="What is this for?">
    <small>For your records. Stored alongside the name; not the value.</small>
  </div>
  <button type="submit" class="btn btn--primary">Save</button>
</form>
```

**API endpoints:**

```python
@router.get("/api/secrets")
async def api_list_secrets() -> JSONResponse:
    """Return [{name, origin, set, description, last_modified, masked_preview}, ...].
    Values are NEVER returned. Masked preview is "sk-ant-***...***ABCD" — last 4 chars only."""

@router.post("/api/secrets")
async def api_set_secret(request: Request) -> JSONResponse:
    """Set or update a secret in the global store.
    Body: {name, value, description}. Returns success + masked preview."""

@router.delete("/api/secrets/{name}")
async def api_delete_secret(name: str) -> Response:
    """Remove from global store. 204 on success, 404 if not present."""

@router.post("/api/secrets/{name}/test")
async def api_test_secret(name: str) -> JSONResponse:
    """For known credential types (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.),
    fire a real round-trip test. Returns {ok, message}.
    For arbitrary names, returns {ok: null, message: "no test available"}."""
```

**Mask format helper:** `_mask_secret(value)` returns `value[:6] + "***...***" + value[-4:]` if `len(value) >= 12`, else just `***`. Already used by `urika config api-key --test`; extract to `urika.core.vault.mask_value()` so dashboard reuses.

**Step 1 — Failing tests** for the GET/POST/DELETE/test endpoints.

**Step 2 — Implement** — endpoint logic + template + Alpine state for the form.

**Step 3 — Tests:** dashboard renders Secrets tab; round-trip set → list → delete; existing process-env secrets show the right origin badge; ANTHROPIC_API_KEY test button works.

**Step 4 — Commit:** `feat(dashboard): Settings → Secrets tab with origin badges + add/edit/delete + per-secret test`

### Task B.2: Per-project Secrets tab

**Files:**
- Modify: `src/urika/dashboard/templates/project_settings.html` — add Secrets tab.
- Modify: `src/urika/dashboard/routers/api.py` — `/api/projects/<n>/secrets` CRUD.
- Test: `tests/test_dashboard/test_project_secrets.py` (new).

Same UI pattern as global, but writes to `<project>/.urika/secrets.env`. Project-tab list shows BOTH project-level secrets AND global ones (with their origin badges) so the user can see the full effective set for a project.

Project tab must also show inheritance: if a global secret exists, project tab shows "Override?" button alongside it; clicking opens the form pre-populated with the global value (masked).

**Step 4 — Commit:** `feat(dashboard): per-project Secrets tab with override-from-global flow`

---

## Phase C — Migration + reuse for existing flows

### Task C.1: Notifications setup uses the vault

**Files:**
- Modify: `src/urika/cli/config_notifications.py` — `save_secret` calls go through the vault.
- Modify: `src/urika/dashboard/routers/api.py` notifications endpoints — same.

The notifications subsystem already uses the env-var-name indirection pattern. This task just routes the underlying writes through the vault so they show up in the new Secrets tab alongside everything else.

No behaviour change for users — the existing `~/.urika/secrets.env` file is the vault's FileBackend, so values read by `EmailChannel`, `SlackChannel`, `TelegramChannel` continue to work unchanged.

**Step 4 — Commit:** `refactor(notifications): credential writes go through SecretsVault`

### Task C.2: `urika config api-key` uses the vault

**Files:**
- Modify: `src/urika/cli/config.py` — the api-key command now uses vault directly.

Same migration as C.1, no user-visible change.

**Step 4 — Commit:** `refactor(cli): config api-key uses SecretsVault`

### Task C.3: Privacy endpoint test button uses the vault + closes #115

**Files:**
- Modify: `src/urika/dashboard/routers/api.py` `/api/settings/test-endpoint` endpoint.

The Privacy tab already has a per-endpoint Test button that probes reachability (`_probe_endpoint`). Task #115 was to make it ALSO fire a real chat-completion request to verify the endpoint works end-to-end with the configured key.

This task implements that:
1. After reachability check passes, the test endpoint reads the api_key_env value via the vault.
2. Constructs a minimal chat completion request (use `urika.core.anthropic_check.verify_anthropic_api_key` if endpoint is Anthropic; for OpenAI-compatible endpoints, use a similar minimal `/chat/completions` POST with `max_tokens=5`).
3. Returns `{reachable, api_key_set, round_trip_ok, model, latency_ms}`.

**Step 4 — Commit:** `feat(dashboard): privacy endpoint test does real round-trip via SecretsVault (#115)`

---

## Phase D — Agent discoverability

The most subtle but highest-value phase: **agents need to know what secrets exist** without seeing their values.

### Task D.1: Agent-facing `list_secrets()` capability

**Files:**
- Modify: `src/urika/agents/runner.py` or wherever the AgentConfig is built — inject the vault's `list_keys()` (NAMES only, no values) into the agent's system-prompt context.
- Modify: relevant agent system prompts under `src/urika/agents/roles/prompts/` — add a section explaining "available credentials".

**The system-prompt addition** (added to planning_agent, tool_builder, task_agent system prompts):

```
## Available credentials

The following named secrets are configured for this project. You can
write Python code that reads them via ``os.environ.get(name)``; the
values are loaded at run time. You will never see the values
themselves. Use this list to:

- Pick tools / approaches whose required credentials are present.
- If a needed credential is missing, request it via the response with
  ``needs_secret: NAME (purpose)``; the orchestrator surfaces this to
  the user as a "configure NAME and rerun" prompt.

Currently available:
- ANTHROPIC_API_KEY (Claude API)
- HUGGINGFACE_HUB_TOKEN (HuggingFace gated models)
- WANDB_API_KEY (W&B logging)
- ... [populated from vault.list_keys() at agent-spawn time]

Currently MISSING but commonly useful:
- OPENAI_API_KEY (OpenAI / GPT models)
- KAGGLE_USERNAME, KAGGLE_KEY (Kaggle datasets)
- ... [populated from a known-defaults registry]
```

The "currently missing" list comes from a small registry at `src/urika/core/known_secrets.py` — names + descriptions for well-known credentials. The dashboard's Secrets tab also uses this registry to suggest entries with descriptions when adding.

### Task D.2: `needs_secret` orchestrator response handling

**Files:**
- Modify: `src/urika/orchestrator/loop.py` — when an agent returns `needs_secret: NAME (purpose)`, the orchestrator pauses and surfaces a notification ("Agent needs HUGGINGFACE_HUB_TOKEN — configure it and resume").
- Modify: dashboard run-log page — when the run is paused with a `needs_secret` flag, show a banner with a "Configure secret" button that opens the Settings → Secrets modal pre-filled with the requested name.

**Step 4 — Commit:** `feat(orchestrator): agents can request secrets via needs_secret response; user is prompted`

### Task D.3: Tool builder discovers + registers required secrets

**Files:**
- Modify: `src/urika/agents/roles/prompts/tool_builder_system.md` — when tool builder writes a tool that needs an external API, it MUST include in the tool's docstring a `Requires:` line listing the env vars it reads.
- Modify: `src/urika/tools/registry.py` — when a project tool is discovered, parse its docstring for `Requires:` and surface in `urika tools` output + dashboard tools page.

This means the dashboard can show: "tool `vision_caption` requires `OPENAI_API_KEY` — currently set ✓" or "currently missing ✗". Closes the loop on the user's mental model: "I added a tool, do I need to set up any new secrets?"

**Step 4 — Commit:** `feat(tool-builder): tools self-document required secrets via docstring`

---

## Phase E — Smoke + docs + release

### Task E.1: Smoke checklist

Create `dev/plans/2026-04-29-secrets-vault-smoke.md`:

- Configure ANTHROPIC_API_KEY via Settings → Secrets → see green ✓.
- Click Test button → real round-trip succeeds; cost ≈ $0.0001.
- Add HUGGINGFACE_HUB_TOKEN; verify it shows up.
- Delete a secret; verify file/keyring is updated.
- Set a process-env secret in the shell that launches the dashboard; verify it shows with `[process env]` badge and no Clear button.
- Per-project: add a project-only secret; verify project agent sees it but other projects don't.
- Restart dashboard; verify all set secrets persist.
- Pull `OPENAI_API_KEY` from secrets.env file; verify backend fall-through (keyring missing → file fallback).
- Run an experiment; verify agents don't see values in their prompt context (only names).
- Trigger a `needs_secret` from a tool builder run; verify the dashboard banner + modal flow.

### Task E.2: Documentation

- New `docs/14-configuration.md` section: "Secrets vault — UI, tiers, file format, keyring backend".
- Update `docs/18-dashboard.md` with the new Settings → Secrets tab.
- Update `docs/20-security.md` — secrets are stored encrypted in OS keyring or chmod-0600 file; never in `settings.toml`; never in agent prompts; tier resolution rules.
- Update `docs/16-cli-reference.md` — add `urika secrets list / set / delete / test` commands (mirror dashboard CRUD).

### Task E.3: New `urika secrets` CLI commands

Mirror the dashboard CRUD in CLI for scriptability:

```bash
urika secrets list                    # list names + origin badges
urika secrets set HUGGINGFACE_HUB_TOKEN --from-stdin
urika secrets delete OPENAI_API_KEY
urika secrets test ANTHROPIC_API_KEY  # round-trip
```

`urika config api-key` becomes a thin alias for `urika secrets set ANTHROPIC_API_KEY` (keep the alias for discoverability).

### Task E.4: CHANGELOG + version bump

- `[Unreleased]` → `[0.4.0] - YYYY-MM-DD`.
- Bump `pyproject.toml` 0.3.0 → 0.4.0.
- New `[Unreleased]` section above for future commits.

---

## Effort

| Phase | What | Effort |
|---|---|---|
| A | Storage layer (vault + keyring/file backends + tests) | ~1 day |
| B | Dashboard Secrets tabs (global + per-project + endpoints) | ~2 days |
| C | Migrate notifications + api-key + privacy-test #115 | ~1 day |
| D | Agent discoverability (system-prompt injection + needs_secret + tool docstrings) | ~1.5 days |
| E | Smoke + docs + CLI + release prep | ~1 day |

**Total: ~6.5 days** of focused work for v0.4.

---

## Open questions (raise before starting)

1. **`keyring` as a hard dep or extras?** The package is widely installed via pip but introduces platform-specific behavior. Recommend extras: `pip install urika[keyring]` enables the keyring backend; default install gets the file backend. This keeps the lean dep surface for headless / Docker / CI users.

2. **Secret descriptions: stored where?** Two options:
   - (a) Sidecar in `~/.urika/secrets-meta.toml` — descriptions + last-modified + which tool registered it.
   - (b) In the keyring's "comment" field where supported, file's leading `#` comment otherwise.
   
   Recommend (a) — cleaner, doesn't depend on backend quirks. Sidecar is plain text; descriptions are metadata not secrets.

3. **Project `.env` discovery — opt-in or auto?** Recommend auto: when a project is loaded, the vault automatically reads `<project>/.urika/secrets.env`. No opt-in needed; the file's mere presence is the opt-in signal. The dashboard offers a "create per-project secret" button that creates the file if absent.

4. **Should the vault unset `os.environ` on `delete_global`?** The vault writes to `os.environ` on `set_global` so the value is immediately available. Symmetrically, `delete_global` should unset it. But process-env-set values (Tier 1) should NOT be touched. Distinguish by tracking which keys WE wrote.

5. **Migration from existing `~/.urika/secrets.env`?** None needed — the vault uses the same file as its FileBackend. Existing keys are picked up automatically.

---

## Recommendation

Phase A (storage layer) is the minimum-viable foundation; everything else builds on it. Start there, test thoroughly, then dispatch B/C/D in parallel since they're independent (B = dashboard UI, C = migrations, D = agent integration).

After Phase E lands, **v0.4 = Secrets Vault** — single-theme release. Then v0.5 picks up multi-provider runtime, with each new adapter (OpenAI, Google, Pi) registering its own default secret via the registry.
