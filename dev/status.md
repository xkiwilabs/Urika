# Urika — Current Status

**Date:** 2026-06-14
**Version:** v0.10.0 (pre-1.0 hardening) FEATURE-COMPLETE on dev,
UNRELEASED — all 9 phases built/reviewed (see
`dev/plans/2026-06-14-v0.10.0-pre-1.0-hardening.md`); ships behind the
new pre-release smoke gate. v0.9.1 (report-integrity hotfix) SHIPPED
2026-06-13; v0.9.0 (output polish) 2026-06-13; v0.8.0 (review hardening
+ research scoping) 2026-06-10; v0.7.0 (multi-provider) 2026-06-08;
v0.6.x 2026-05-31..06-01; v0.5.x 2026-05-31; v0.4.5.1 2026-05-26.
**Branch:** `main` on both `origin` and `public` tagged `v0.9.1`.
`dev` carries the unreleased v0.10.0 work (still `version = 0.9.1` in
pyproject; the release flow bumps it).
**Tests:** ~4410 collected; **4340 pass** in the unit suite
(`URIKA_SKIP_SMOKE=1 pytest -q -m "not integration"`), 1 skipped, 70
integration deselected. v0.10.0 P9 makes the real-API e2e smoke a
pre-release gate in `release-to-main.sh`.
**Next focus:** release v0.10.0 (run the now-gated smoke), then the
v1.0.0rc cycle (feature freeze + API audit + migration guide).
Canonical roadmap: `dev/plans/2026-05-02-roadmap-to-v1.0.md`.

The active roadmap is **`dev/plans/2026-05-02-roadmap-to-v1.0.md`** —
covers v0.4.0 → v1.0.0 with cut criteria, release contents, and
testing windows. Single source of truth.

---

## Active plans (`dev/plans/`)

| Plan | Status |
|------|--------|
| `2026-05-02-roadmap-to-v1.0.md` | **Master roadmap** — v0.4.0 → v1.0.0 (v0.4.5 inserted; v0.6/v0.7 swapped 2026-05-04) |
| `2026-06-01-v0.7.0-design.md` | v0.7.0 multi-provider adapters spec — IMPLEMENTED |
| `2026-06-01-v0.7.0-implementation.md` | v0.7.0 implementation plan — 16 tasks + Task #78 rewire, all done; awaiting tag |
| `2026-05-17-v0.5.0-memory-deepening.md` | v0.5.0 spec — SHIPPED 2026-05-31 |
| `2026-05-25-pre-v0.5-hardening-fixes.md` | v0.4.5.1 hardening — SHIPPED 2026-05-26 |
| `2026-05-31-v0.5.0-implementation.md` | v0.5.0 implementation plan — 22 tasks, all done |
| `dev/archive/2026-04-30-github-integration.md` | Full design — implementation in v0.6.0 (GitHub auto-backup) |

Everything else lives under `dev/archive/plans/` — see the
"Plan-doc hygiene rules" section of the master roadmap for the
discipline.

---

## v0.4.x — what shipped (2026-05-02 → 2026-05-25)

The full v0.4 line is out: v0.4.0 (feature-complete), v0.4.3
(prompt-cache + cross-platform CI), the v0.4.4.x hardening hotfixes,
and v0.4.5 (surface parity across CLI/TUI/REPL/dashboard). A pre-v0.5
hardening sweep then landed on `dev` (2026-05-25): brace-balanced
JSON run-record extraction, stop-aware finalize, **default-secure
dashboard** (auto-generated auth token + Origin/CSRF guard + SSRF
blocklist), atomic vault/session writes, shared ANSI scrubber,
fail-closed Slack/Telegram inbound, and REPL `/run --resume` parity.
PyPI: `pip install urika==0.4.5`. The v0.4.0 detail below is retained
as the baseline-feature record.

### Major surfaces (the v0.4 tracks)

- **SecurityPolicy enforcement** — runtime enforcement via the SDK's
  `can_use_tool` callback (was advisory pre-v0.4). Path checks resolve
  symlinks and `..` traversal; Bash commands tokenised with `shlex`
  before allowlist matching; metacharacters rejected outright.
  `urika/agents/permission.py`.
- **Multi-provider thin abstraction** — `urika.runners` Python
  entry-point group + `AgentRunner` ABC + `AgentConfig`. Single
  Anthropic adapter ships in v0.4; the boundary is what the OpenAI
  adapter will plug into in v0.5.
- **Project memory Phase 1** — `<project>/memory/MEMORY.md`-indexed
  directory of structured markdown entries. Auto-capture from
  `<memory type="...">...</memory>` markers. CLI surface
  (`urika memory list/show/add/delete`). Phases 2-4 in v0.5.
- **Experiment comparison view** — `/projects/<n>/compare`.
- **Dataset hash + drift detection** — SHA-256 per data file at
  `urika new`, re-checked on `urika status`. `[project.data_hashes]`
  in `urika.toml`.
- **Cost-aware budget** — `urika run --budget USD` pauses at next
  turn boundary when accumulated cost crosses threshold; resumable.
- **Shell completion** — `urika completion install/script/uninstall`
  for bash / zsh / fish.
- **Sessions list/export** — `urika sessions list/export`.

### Post-rc2 hardening (the day-of-ship fixes)

- **Bearer-token auth for non-Anthropic private endpoints.** Sets
  `ANTHROPIC_AUTH_TOKEN` (Bearer header) instead of
  `ANTHROPIC_API_KEY` (x-api-key) when the endpoint isn't
  api.anthropic.com. The compliance scrubber now preserves
  deliberately-set values.
- **Trailing-exit-1 tolerance** — system claude CLI v2.1.124+
  exits 1 in streaming mode after a successful run. Adapter detects
  "we already saw a clean ResultMessage / streamed content" and
  returns success regardless. Counter-cases (no content, real auth/
  billing/credit failures) still propagate as failures.
- **Reasoning vs execution model split** — Opus default auto-pins
  4 reasoning agents on Opus and 8 execution agents on Sonnet 4.5.
  ~50-65% cost reduction per experiment, no quality impact. Single
  source of truth in `urika/core/recommended_models.py`.
- **`urika config --reset-models` + dashboard "Reset to recommended
  defaults" button** — re-applies the split to existing settings.
  Idempotent. Hybrid mode preserves data_agent + tool_builder
  private pins.
- **`max_turns_per_experiment` unified at 5** across all five sites
  (was 10).
- **Per-experiment finalize no longer auto-writes the redundant
  project-level narrative** — saved 10-25 min per successful
  experiment. Per-experiment narrative + presentation still written.
  Agent feedback loop unaffected.
- **`urika new` no longer spawns live agent under non-TTY stdin** —
  CliRunner / CI / scripts all safe now.
- **Windows: SSE log streamers tolerate cp1252 bytes**; **Windows:
  stdout/stderr auto-reconfigure to UTF-8** at import time.
- **Doc reorg** — 20 user-facing docs split into 32 focused sub-pages
  (12a/b, 13a/b, 14a/b, 16a-e, 18a-d, 19a/b). Cross-references
  rewritten across the tree.

See `CHANGELOG.md` for the full per-fix accounting.

---

## What's next (per the roadmap)

Post-swap canonical order (v0.6/v0.7 swapped 2026-05-04 so GitHub
backup ships before the multi-provider work):

| Release | Focus | Status |
|---|---|---|
| **v0.5.0** | Project memory deepening — advisor+report inject; curator agent + dry-run auto-trigger; archive + mtime diff; dashboard memory page; auto_capture toggle; cross-surface parity tests | SHIPPED 2026-05-31 |
| **v0.6.0** | GitHub auto-backup (`urika github init --create` shells out to `gh` for one-command repo creation; manual `--remote URL` path also supported; opt-in auto-push hook on event triggers; project-creation wizard offers auto-create; dashboard Git tab) | SHIPPED 2026-05-31 |
| **v0.7.0** | Multi-provider model adapters (OpenAI Agents SDK + others) | SHIPPED 2026-06-08 |
| **v0.8.0** | Review-driven hardening + research-goal builder pipeline + output comprehensibility | SHIPPED 2026-06-10 |
| **v0.9.0** | Output polish — exports (PDF/LaTeX/Jupyter via Pandoc), model-card auto-generation | **on dev** |
| **v0.10.0** | Pre-1.0 hardening — `urika upgrade` migration, builder-session persistence, agent-subprocess env isolation, accessibility pass (templates cut 2026-06-10) | planned |
| **v1.0.0rc1** | Feature freeze + API audit + migration guide | planned |
| **v1.0.0rc2** | RC feedback fixes only | planned |
| **v1.0.0** | OFFICIAL RELEASE — API stability commitment | planned |

**Total: ~32 dev-days over ~7.5 weeks.** No `.x` stabilisation
windows between minors — bug-fix budget is folded into the first
1–2 days of the next minor. Cut criteria are hard — the version is
the contract, the schedule is a guess.

### Cut from 1.0 (deferred to v1.1+)

- **Plugin / extension system** (`urika.tools` / `urika.agents`
  entry points). API commitment problem; wait for real-world
  feedback after 1.0.
- **GitHub thick** — OAuth flow, "Connect GitHub" dashboard button,
  audit log, PR/issue surface. v0.7 auto-backup covers the high-
  frequency case.
- **Mobile-responsive dashboard.** Phone use case = notifications
  (Slack/Telegram inline buttons), already shipped in v0.3.
- **arXiv fetcher**, **Plotly / Bokeh interactive figures**,
  **Optuna hyperopt agent**, **run replay / decision-log viewer**.

---

## Repo / branch hygiene

- `dev` is the working branch; daily commits go here.
- `dev/scripts/release-to-main.sh` syncs `dev` → `main` on both
  `origin` (urika-dev) and `public` (Urika), checks out only public-
  facing files, commits "release: sync from dev (<sha>)", pushes
  both remotes.
- GitHub Release published on `xkiwilabs/Urika` (public) — fires
  the `Publish to PyPI` workflow which trusted-publishes (no token
  needed).
- Tags: `vMAJOR.MINOR.PATCH` (e.g. `v0.4.0`).

### v0.10.0 Phase 9 — release engineering (2026-06-14)

- **e2e smoke is now a pre-release gate.** `release-to-main.sh` runs
  two gates after the "clean tree" check and before the header regen:
  (1) the fast unit suite (`URIKA_SKIP_SMOKE=1 pytest -m "not
  integration"`), always; (2) the real-API e2e smoke
  (`smoke-v04-e2e-open.sh`), unless `URIKA_SKIP_SMOKE=1` (loud yellow
  warning when skipped). No `ANTHROPIC_API_KEY` + not skipped → abort
  with a `urika config api-key` pointer. Closes the gap where bugs
  shipped past a green unit suite because the smoke was never wired
  into the release flow.
- **Transient-API-failure tolerance in the smoke.** `run_step_with_
  timeout` now classifies a failed step via `_is_transient_failure`
  (stream timeout / 429 / RESOURCE_EXHAUSTED / overloaded / 503 / 529,
  with AssertionError/KeyError/TypeError/SyntaxError/ModuleNotFound and
  non-timeout urika tracebacks disqualifying). A transient failure
  retries the command ONCE; pass-on-retry → PASS, persistent-transient
  → new non-fatal `TRANSIENT` outcome (does NOT affect `exit $FAIL`),
  real failure → `FAIL` immediately. Fixes the v0.9.1 hard-fail on the
  `RuntimeError: Agent stream timeout` flake.
- **httpx TestClient deprecation — RESOLVED, not deferred.** The
  `StarletteDeprecationWarning: Using httpx with starlette.testclient
  is deprecated; install httpx2 instead` came from starlette 1.2.1 /
  fastapi 0.136.3, whose `TestClient` prefers `httpx2` (the httpx 2.x
  line, a *separate* PyPI distribution) and only falls back to legacy
  `httpx` with a one-shot warning. `httpx` itself stays — it's a hard
  runtime dep of anthropic / openai / google-adk / mcp (all pin
  `httpx<1`); `httpx2` coexists (distinct `httpx2` / `httpcore2` dist
  + import names). Fix: added `httpx2>=2.0` to the `dev` extra in
  `pyproject.toml` (test-only, NOT in `[all]`). Dashboard suite (1073
  tests) passes with zero warnings under httpx2.

---

## Test data

`dev/test-datasets/` contains the canonical fixture projects used
by the smoke harness:

- `stroop` — 50 rows × 4 cols, paired t-test (confirmatory). Used by
  open-mode E2E.
- `marketing` — 400 rows × 8 cols, unsupervised clustering
  (exploratory). Used by hybrid-mode E2E.
- `depression` — 500 rows × 10 cols, regression / feature
  importance (exploratory). Used by private-mode E2E.
- `housing`, `eeg`, `climate`, `gene-expression`, `text-sentiment`,
  `images`, `energy-forecast` — additional fixtures for
  domain-specific test runs.

The smoke harness in `dev/scripts/smoke-v04-e2e-{open,hybrid,
private,all}.sh` drives the full pipeline against real LLMs (no
`--dry-run`).

---

## Working tree

```
dev/
├── archive/
│   ├── plans/
│   │   └── v0.4-shipped/            # all v0.4 plan docs after ship
│   ├── option-{a,b,c}-*.md          # historical adapter options
│   ├── 2026-04-27-tester-checklist.md
│   └── typescript-tui/              # 186MB, untracked, can be `rm -rf`d
├── plans/
│   ├── 2026-05-02-roadmap-to-v1.0.md           # **master**
│   ├── 2026-05-17-v0.5.0-memory-deepening.md   # next release
│   ├── 2026-05-25-pre-v0.5-hardening-fixes.md  # landed on dev
│   └── ... (shipped-release plans pending archive)
│   # github-integration design archived at dev/archive/ (for v0.6)
├── scripts/
│   ├── release-to-main.sh
│   ├── smoke-v04-e2e-{open,hybrid,private,all}.sh
│   ├── smoke-v04-e2e-common.sh
│   ├── smoke-v04-cli.sh
│   ├── smoke-v04-multi.sh
│   └── ... (other dev tooling)
├── test-datasets/                    # canonical fixtures
├── contributing-an-adapter.md        # contributor doc (moved from docs/)
├── status.md                         # this file
├── testing-plan.md
└── tutorials-01-project-setup-walkthrough.md
```
