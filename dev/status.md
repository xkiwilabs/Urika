# Urika — Current Status

**Date:** 2026-05-02
**Version:** v0.4.0 (released to PyPI as `urika==0.4.0`)
**Branch:** `dev` synced with `origin/dev`; `main` synced on both
`origin` and `public` and tagged `v0.4.0`.
**Tests:** 1816 passed / 1 skipped / 0 failed in the dashboard-
excluded fast suite.

The active roadmap is **`dev/plans/2026-05-02-roadmap-to-v1.0.md`** —
covers v0.4.0 → v1.0.0 with cut criteria, release contents, and
testing windows. Single source of truth.

---

## Active plans (`dev/plans/`)

| Plan | Status |
|------|--------|
| `2026-05-02-roadmap-to-v1.0.md` | **Master roadmap** — v0.4.0 → v1.0.0 |
| `2026-05-02-v0.4.x-bug-backlog.md` | Bugs queued for v0.4.1 / v0.4.2 |
| `2026-05-02-prompt-bloat-and-context-budget.md` | Layer 1+2 in v0.4.1, Layer 3 in v0.5.x |
| `2026-04-30-github-integration.md` | Full design — implementation in v0.5.0 |

Everything else lives under `dev/archive/plans/` — see the
"Plan-doc hygiene rules" section of the master roadmap for the
discipline.

---

## v0.4.0 — what shipped (2026-05-02)

First feature-complete v0.4 release. PyPI: `pip install urika==0.4.0`.

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

| Release | Focus | Target |
|---|---|---|
| **v0.4.1** | Bug-fix hotfix from v0.4.0 reports (dashboard footer, prompt-bloat trim, sigterm exit, bash timeout, checkpoint docs) | ~1 week (≈ 2026-05-09) |
| **v0.4.2** | Tester-driven hotfix | ~2 weeks after v0.4.1 |
| **v0.5.0** | GitHub integration + OpenAI adapter + Memory Phases 2-4 + Project templates + Plugin system | ~5-7 weeks |
| **v0.5.x** | Stabilisation | 3-4 weeks |
| **v0.6.0** | Output polish (PDF/LaTeX/Jupyter export, arXiv fetcher, Plotly figures, model cards, Optuna agent) | ~4 weeks |
| **v0.6.x** | Stabilisation | 2-3 weeks |
| **v0.7.0** | Final feature work (mobile dashboard, run replay, accessibility, i18n stubs, API audit) — last release before feature freeze | ~3 weeks |
| **v0.7.x** | Final stabilisation before RC cycle | 2-3 weeks |
| **v1.0.0rcN** | Release-candidate cycle, no new features | 2-4 weeks total |
| **v1.0.0** | Official release with API stability commitment | ~5-6 months from today |

Cut criteria are hard — the version is the contract, the schedule is
a guess.

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
│   ├── 2026-05-02-roadmap-to-v1.0.md      # **master**
│   ├── 2026-05-02-v0.4.x-bug-backlog.md
│   ├── 2026-05-02-prompt-bloat-and-context-budget.md
│   └── 2026-04-30-github-integration.md   # for v0.5
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
