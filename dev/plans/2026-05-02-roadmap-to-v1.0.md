# Roadmap: v0.4.0 → v1.0.0

**Authored:** 2026-05-02 (day v0.4.0 shipped to PyPI).
**Last revised:** 2026-06-10 (two same-day revisions: renumbered
after the review-driven hardening + research-scoping release consumed
the v0.8.0 slot — output polish → v0.9.0, UX polish → v0.10.0; then
**project templates cut entirely** (the v0.8.0 research-scoping
builder covers the pain point they targeted) and v0.10.0 re-scoped to
pre-1.0 hardening: `urika upgrade` migration, builder-session
persistence, agent-subprocess env isolation, accessibility pass.
Original 2026-05-02 revision compacted to the 8-week v1.0 target.)
**Status:** Active — supersedes
`dev/archive/plans/v0.4-shipped/2026-04-30-v0.4-roadmap.md`.
**Total horizon:** ~8 weeks working calendar to v1.0.0.

This document is the single source of truth for what ships when
between v0.4.0 (released today) and v1.0.0 (the official, no-pre-
release-suffix milestone).

The discipline:

- **Small, focused minor releases.** Each `.0` ships ~1 week of work
  and one focused capability. Smaller per-release scope = less
  surface for new bugs to hide in.
- **No `.x` stabilisation windows between minors.** The bug-fix
  budget is folded into the first 1–2 days of the next minor. Works
  because each release's scope is small enough that v0.5 bugs are
  unlikely to masquerade as v0.6 features.
- **Feature freeze starts at v1.0.0rc1.** Anything not in v0.10.0
  (was v0.9.0 pre-renumber) rolls to v1.1+. The RC cycle is bug-fix
  only.
- **Cut criteria are hard.** Every release has a verification list
  it must satisfy before shipping. Calendar dates are *targets*, not
  deadlines. v1.0.0 by week 8 is irrelevant if v1.0.0 has known
  P0/P1 defects — the version number is the contract.

---

## v0.4.0 — SHIPPED 2026-05-02

First feature-complete v0.4 release. PyPI: `pip install urika==0.4.0`.

Bundles five tracks (SecurityPolicy enforcement, multi-provider
runtime abstraction, project memory Phase 1, experiment comparison
view, dataset hash + drift detection, cost-aware budget, shell
completion, sessions list/export) plus post-rc2 hardening.

See `CHANGELOG.md` and `dev/status.md` for the full per-fix
accounting.

---

## v0.4.1 — bug-fix hotfix (target: ~4 days, week 0.5)

**Focus:** Close known defects discovered in v0.4.0 testing.

**Ships:**

1. **Dashboard footer model + agent fields** — currently shows `—`
   during running experiments. SSE wiring fix between the run-log
   streamer and the status-bar subscriber. ~0.5 day.
2. **Prompt-bloat trim** — reduce duplication between
   `methods.json`, `advisor-history.json`, `advisor-context.md`,
   knowledge-store, and dataset profile in agent prompts. Halves
   typical advisor / planner prompt size. ~1 day.
3. **Per-endpoint `context_window` declaration + output-token clamp**
   — `[privacy.endpoints.<n>] context_window = N` and
   `max_output_tokens = N` keys, plumbed through to the SDK. Fixes
   32K-context private endpoints. ~0.5 day.
4. **SIGTERM-after-criteria-met exits 0** — `cli/run.py` cleanup
   handler distinguishes "agent crashed" (exit 1, status `stopped`)
   from "killed during post-criteria narrative tail" (exit 0,
   status `completed-narrative-pending`). ~0.5 day.
5. **Per-tool-call Bash timeout** — configurable
   `[preferences].max_method_seconds` (default 24h). Hung subprocess
   fails the method instead of hanging the experiment. ~0.5 day.

**Cut criterion:** Five fixes have regression tests. Full pytest
green. Dashboard footer renders the agent + model in real time
across at least one user-tested project.

---

## v0.4.5 — surface parity track (target: ~5 dev-days, inserted 2026-05-17)

**Inserted 2026-05-17** between v0.4.4 (shipped) and v0.5.0 (planned).
Closes the surface-parity gaps surfaced by the 2026-05-17 audit so
v0.5.0 memory deepening lands on stable surfaces (rather than
shipping features that immediately need parity backfill, one feature
at a time).

Detailed plan: `dev/plans/2026-05-17-v0.4.5-parity-track.md`.

**Ships (summary):**

1. **Dashboard `POST /api/projects` runs the builder-agent Q&A loop.**
   Closes the one blocker — today the endpoint scaffolds but
   explicitly skips the interactive loop. ~2-3 days.
2. **TUI ports of `/inspect`, `/unlock`, `/update`, `/secret`.**
   None of these exist on TUI today (verified by grep). REPL
   already has the first two. ~1.5 days.
3. **Dashboard unlock endpoint + UI** + REPL `cmd_unlock`. ~0.5 day.
4. **Five new cross-surface parity tests** extending
   `tests/test_cross_interface_parity.py` — builder-loop
   invocation, pause-flag path, settings cascade, criteria-met
   exit, notification auto-seed. ~1 day.

**Cut criterion:** Dashboard new-project produces the same builder
artifacts as `urika new`; all four TUI commands exist and use
shared helpers (no parallel implementations); REPL `cmd_unlock`
exists; five new parity tests pass on the full 6-job matrix; full
3395-test suite green under both populated and empty `URIKA_HOME`.

**Calendar impact:** Pushes v0.5.0 (originally week 1.5) by ~1 week.

---

## v0.5.0 — project memory deepening (target: ~1 week, was week 1.5; now shifted +1wk by v0.4.5)

**Focus:** Make project memory the actual cross-experiment knowledge
backbone it was designed to be. v0.4 shipped Phase 1 (auto-capture
from `<memory>` markers + manual CRUD). v0.5 closes Phases 2–4.

**Ships:**

1. **Curator agent** — auto-organises captured memory entries,
   merges near-duplicates, flags contradictions ("user said
   `cv_strategy` should be subject-wise in entry 12, but entry 47
   says session-wise — needs review"), promotes high-value
   feedback into pinned `instruction_*` entries. Runs on a
   user-triggered `urika memory curate` or after every N agent
   exchanges (configurable). ~2 days.
2. **Archive viewer (CLI + dashboard)** — `urika memory archive`
   browses old/superseded entries; dashboard memory tab gains a
   "show archived" toggle. ~1 day.
3. **Diff view** — `urika memory diff <from> <to>` shows how the
   memory directory evolved between two timestamps; dashboard
   timeline view of memory growth. ~1 day.
4. **Planner + advisor read-rule refinement** — confirm both roles
   see the curator-organised memory consistently; cap memory
   injection at a token budget so curator-grown memory doesn't
   re-introduce the v0.4 prompt-bloat. ~1 day.

**Cut criterion:** A project that runs 10+ experiments has its
memory directory readable and decision-useful — not a sea of
duplicates. Curator agent's merges + flagged contradictions
verified against a hand-built test corpus. Memory injection token
cost stays under budget set in v0.4.1.

---

## v0.6.0 — GitHub auto-backup (target: ~1.2 weeks, week 3)

**Reordered 2026-05-04:** swapped with the original v0.7.0 to ship
GitHub backup before the multi-provider work. Discrete, smaller
surface, immediately useful — landing it sooner gives users the
"my work is safe" payoff while the bigger multi-provider work cooks.

**Focus:** Each project becomes a git repo automatically backed up
to a user-configured remote. Scope is **backup**, not
collaboration — no OAuth, no audit log, no PR flows. The thicker
"Connect GitHub" experience is a v1.1+ surface.

**Important: Urika never talks to the GitHub API.** The user creates
the remote repository manually on GitHub (or via the `gh` CLI / web
UI / GitHub Desktop / whatever), copies the URL, and hands that
URL to Urika. Urika is purely a `git` shell-out wrapper from that
point forward — `git init`, `git remote add`, `git push`. The user's
existing `git` authentication (HTTPS+PAT in OS keyring, SSH keys,
gh-stored creds — whatever already makes `git push` work on the
machine) handles authentication.

This is a deliberate scope choice:
- Zero auth surface for Urika to manage. We never see, ask for, or
  store GitHub credentials.
- Works against any git remote — public/private GitHub, GitHub
  Enterprise, GitLab, Bitbucket, self-hosted Gitea — because we
  don't know it's GitHub. The `urika github` namespace is a UX
  nicety; the implementation is provider-agnostic.
- Public-repo creation requires explicit human intent — making a
  public repo is irreversible if you'd accidentally automate it on
  a project with sensitive data.

**Ships:**

1. **`urika github init <project> --remote <url>`** — wraps
   `git init` (if needed) + `git remote add origin <url>`.
   Initialises `.gitignore` with sensible defaults (`.urika/`
   internal state, `.lock` files, `__pycache__`, large-binary
   artifacts). Pre-condition: the user has already created the
   empty remote repo on GitHub (or wherever) and has a working
   URL. ~1 day.
1b. **`urika github init <project> --create [--public]`** — uses
   the `gh` CLI (if installed and authed) to create a fresh
   private GitHub repo named after the project, set the remote,
   and do the first push in one shot. Wraps
   `gh repo create <name> --private --source <dir> --push`.
   Falls back gracefully if `gh` isn't installed/authed: prints
   a one-line install hint and tells the user to either create
   the remote manually or install `gh`. **Urika never sees a
   GitHub credential** — `gh`'s own stored token does the work.
   ~0.5 day.
1c. **Auto-create at project-creation time.** Two opt-ins:
   - **Per-invocation:** `urika new my-project --github` (private
     by default) or `--github --public`. Project wizard's
     interactive flow gains a "Create a private GitHub repo for
     this project? [Y/n]" question if `gh` is detected.
   - **Global default:** `[preferences] github_auto_create = true`
     and `github_auto_create_visibility = "private"|"public"` in
     `~/.urika/settings.toml` so every `urika new` defaults to
     creating a remote without re-prompting. Override with
     `--no-github`. Dashboard New Project modal gets a checkbox
     + visibility selector wired to the same path.
   ~0.5 day.
2. **`urika github push <project>` / `urika github status <project>` /
   `urika github pull <project>`** — manual push wraps
   `git add -A && git commit -m "<auto-message>" && git push`.
   Auto-message templates ("urika: experiment exp-003 completed",
   "urika: 4 new methods registered"). ~1 day.
3. **Auto-push hook** — opt-in via
   `[github] auto_push = true` and
   `[github] auto_push_after = ["run", "finalize", "build-tool"]`
   in `urika.toml`. Fires at the end of each listed CLI command
   so a project always has a recent push on the configured
   remote. ~1 day.
4. **Dashboard Git tab** — read-only panel per project: remote URL,
   last-push timestamp, recent commit log (last 10), uncommitted-
   changes indicator, manual "Push now" button. ~1 day.

**Cut criterion:** A project initialised with `urika github init`
and configured with `auto_push = true` has every successful
`urika run` reflected as a commit on the remote within 60s of
the run completing. Manual `urika github push` works against an
existing remote. The dashboard Git tab renders correctly across
the open / hybrid / private project shapes.

---

## v0.7.0 — multi-provider model adapters (target: ~2 weeks, week 5)

**Reordered + scope-expanded 2026-05-04:** swapped with the original
v0.6 OpenAI work (now lands later because GitHub backup ships first),
and **added a Google Gen AI / Gemini adapter alongside OpenAI** so
v0.7 ships with three working backends instead of two. Project
templates were originally bundled here; moved to v0.9 as UX polish.

**Focus:** Ship two new agent-runtime backends on top of v0.4's thin
abstraction. After this release, the same Urika project can run
experiments against Anthropic, OpenAI, OR Google models — and users
can mix providers per agent role (e.g., Opus for the planner, GPT-4
for task work, Gemini for the advisor). Validates the
`urika.runners` entry-point boundary against two independent SDKs
before v1.0 freezes the public API.

**Ships:**

1. **OpenAI Agents SDK adapter** — second working agent backend.
   End-to-end: a project configured with the OpenAI runner runs the
   full experiment loop (planner → task → evaluator → advisor) and
   produces the same artifacts as the Anthropic runner. Passes the
   same `tests/test_agents/` battery for behaviours that aren't
   Anthropic-specific. ~6 days.
2. **Google Gen AI SDK adapter** — third working agent backend.
   Same end-to-end requirement as OpenAI. ~6 days.
3. **Per-agent cross-provider routing** — `urika config` and the
   dashboard Models tab gain provider-aware dropdowns so users can
   pick a different backend per agent role (e.g., planner=Anthropic
   Opus, task=OpenAI GPT-4, advisor=Google Gemini). The runtime
   already supports per-agent endpoints; this just makes the
   provider dimension explicit in the UI. ~2 days.

**Cut criterion:** A complete experiment runs end-to-end on each of
the three backends (Anthropic, OpenAI, Google) against the same
behavioural-data fixture, producing equivalent artifact sets. A
mixed-provider project (e.g., planner=Anthropic, task=OpenAI,
advisor=Google) runs a 5-turn experiment without errors and
records correct usage / cost per backend.

---

## v0.8.0 — review hardening + research scoping (SHIPPED 2026-06-10)

**Inserted 2026-06-10, unplanned.** A comprehensive codebase review
(bugs, cross-surface parity, agent outcomes, test suite) turned into
a ~58-commit release that consumed the v0.8.0 slot: corrupt-JSON
tolerance, OpenAI/Google adapter parity (timeouts, error categories,
scrub, max_method_seconds), structural real-import SDK tests (caught
a live OpenAI $0-usage bug), surface parity (REPL provider auth,
dashboard plan agent + git pull), canonical best-run selection,
builder research-goal pipeline (feasibility check, preferences /
hypotheses / constraints elicitation, criteria co-drafting, dashboard
wizard), output comprehensibility (metric interpretation,
assumptions_detail, run-id traceability, audience-aware labbook),
June-15-2026 subscription credit-pool policy refresh, and three
release-gate smoke fixes (SDK 0.2.91 max-turns tolerance + pin,
`urika present` honesty, durable run-record contract). Tag `v0.8.0`
at `b912b939`; full detail in `CHANGELOG.md` and
`dev/plans/2026-06-10-v0.7.1-review-hardening-and-v0.8-foundations.md`.
Downstream releases renumbered: output polish → v0.9.0, UX polish →
v0.10.0.

---

## v0.9.0 — output polish (target: ~1.5 weeks; was v0.8.0 pre-renumber)

**Focus:** Make Urika's outputs publication-ready. v0.4–0.8 prove
the agents do good science; v0.9 makes the artifacts shippable to
a paper, a poster, a thesis chapter.

**Ships:**

1. **PDF / LaTeX export** — `urika report --format pdf|latex` and
   `urika finalize --format pdf|latex`. Pandoc-based; default
   theme matches the existing reveal.js light/dark aesthetic.
   ~3 days.
2. **Jupyter notebook export** — `urika finalize --jupyter`
   produces a `reproduce.ipynb` alongside `reproduce.sh`. Each
   final method becomes a cell, with markdown intros pulled from
   `findings.json`. Runnable end-to-end on a fresh kernel.
   ~3 days.
3. **Model-card auto-generation** — each finalized method gets a
   `methods/<method>_model_card.md` (Hugging Face template
   adapted) describing assumptions, data used, train/test split,
   intended use, and known limitations. ~1 day.
4. **Uncertainty reporting** *(added 2026-06-10 — publication-ready
   output must report uncertainty)* — `IMetric.compute_with_ci()`
   (bootstrap default), `RunRecord` carries optional
   `metrics_with_uncertainty`, reports/labbook render
   "R²=0.75 [95% CI 0.72–0.78]". Builds directly on v0.8.0's
   `metric_interpretation` + `assumptions_detail` plumbing. ~2 days.
5. **`projectbook/METRICS.md` glossary** *(added 2026-06-10)* —
   finalizer emits a per-project metrics glossary (range,
   interpretation, observed values across runs), reusing
   `core/method_glossary.py` patterns. ~0.5 day.

**Cut criterion:** Every export format produces a valid file that
opens in its target reader (Acrobat / Overleaf / JupyterLab).
The Jupyter notebook runs end-to-end on a fresh kernel without
errors. Model cards exist for every finalized method in a real
test project. At least one metric in the e2e smoke project renders
with a confidence interval in report + labbook.

---

## v0.10.0 — pre-1.0 hardening (target: ~2.5 weeks; expanded 2026-06-14)

**Full detailed plan: `dev/plans/2026-06-14-v0.10.0-pre-1.0-hardening.md`**
(authored after a 5-dimension deep review). Project templates CUT
2026-06-10. Last release before the rc feature freeze. i18n + mobile
remain non-goals.

**Expanded 2026-06-14:** the deep review surfaced real, in-class gaps
worth fixing before the freeze (notably more "producer writes it /
dashboard never surfaces it" bugs — the same class as the v0.9.1
Final-report-link fix — and "agent output not validated" cases). The
schema review also showed `urika upgrade` is *smaller* than feared
(most formats are already load-time tolerant). Net scope grew to ~9
phases / ~12 dev-days. Phases are independently shippable; trim from
the bottom if time-boxed.

**Phases (see the detailed plan for findings + acceptance per phase):**

1. **`urika upgrade`** — idempotent v0.x migration. Mostly a
   `schema_version` stamp + a couple of cosmetic on-disk rewrites
   (leaderboard `entries→ranking`, labbook notes regen) + version
   detection + new fixtures — most schemas are already load-tolerant.
   Required by v1.0 promise 2. ~2 days.
2. **Dashboard surfaces the v0.9 artifacts** (HIGH) — METRICS.md,
   model cards, reproduce.ipynb, and per-experiment evaluation.json
   are written but invisible in the dashboard (same bug class as the
   v0.9.1 report link). Add render routes + links. ~1.5 days.
3. **Agent-subprocess environment isolation** (HIGH) — stop the
   operator's `~/.claude/` settings/plugins/skills/**hooks** loading
   into spawned agent workers (observed: a SessionStart hook burned
   task-agent turns). Force the bundled CLI into a clean config
   context + extend the env scrub. ~1 day.
4. **Finalize integrity validation** — deterministic post-finalize
   checks (findings.json script paths exist; run_id/experiment_id
   resolve in the *named* experiment; reproduce.sh ↔ findings
   consistency) surfaced as warnings, so agent hallucinations don't
   ship as broken reproducibility silently. ~1 day.
5. **Atomic state writes + evaluator-narration guard** — make the
   remaining non-atomic writes (experiment.json/progress.json create,
   leaderboard.json, memory) atomic; legible signal when an evaluator
   narrates. ~0.5 day.
6. **Builder-session persistence** — dashboard wizard survives a
   server restart (persist to `<project>/.urika/builder/`). ~1.5 days.
7. **Cross-surface parity + docs** — dashboard finalize `--format`
   picker; CLI help + docs enumerate the v0.9 artifacts. ~0.5 day.
8. **Accessibility pass** — light-theme contrast (WCAG AA), form
   labels, aria on icon buttons, keyboard nav; axe-core/WAVE clean.
   ~2 days.
9. **Release engineering** — make the e2e smoke a **pre-release gate**
   (it would have caught this session's bugs); transient-API-failure
   tolerance in the smoke (the v0.9.1 stream-timeout flake); migrate
   off the deprecated httpx `TestClient`. ~1 day.

Test hardening is woven through the phases (each ships its regression
pins) plus a mocked-agent finalize-sequence integration test and
parametrized dashboard artifact-route tests for the recurring bug
class.

**Cut criterion:** a real v0.4-era tree upgrades via `urika upgrade`
and passes `status`/`inspect`/`run` cleanly, upgrade-twice is a no-op;
every finalize artifact is reachable + rendered in the dashboard; an
agent-worker transcript on a plugin-laden machine has zero operator
plugin/hook content; a dashboard-wizard session survives a restart;
`release-to-main.sh` refuses to tag on a real smoke FAIL (transient
API hangs distinguished from real failures); axe-core/WAVE zero P0/P1.

**Explicitly NOT in v1.0:** mobile-responsive dashboard. The phone
use case is the notification (Slack/Telegram inline-keyboard
buttons for pause/stop/resume — already shipped in v0.3). If real
users at v1.0 ask for in-browser mobile experience, it's a v1.1
candidate; the right v1.1 answer might be richer notification
actions instead of a responsive dashboard.

---

## v1.0.0rc1 — first release candidate (target: ~3 days, week 7.5)

**Focus:** Cut a release-candidate from `v0.10.0` and start the RC
cycle. **Feature freeze is hard from this point** — no new features
merge until v1.0.0 ships.

**Ships:**

- Same code as v0.10.0, with `version = "1.0.0rc1"` in
  `pyproject.toml`.
- **Final API audit** — every public function in `urika.core.*`,
  `urika.agents.*`, `urika.tools.*` reviewed. Stable API gets a
  proper docstring; implementation detail moves to `_` prefix.
- **CHANGELOG → migration guide** — extract every "Fixed" /
  "Added" / "Changed" entry from v0.4.0 forward into a
  user-facing upgrade guide.
- **Test matrix verification** — the 6-job Linux/macOS/Windows ×
  3.11/3.12 matrix has been green since v0.4.3; rc1 verifies it
  against the rc tag and adds the real-API e2e smoke as a
  release-gated job (the v0.8.0 release validation showed the
  cheap smoke catches real bugs the unit suite can't).

**Cut criterion:** Tester pool (4–6 people) installs rc1 from
PyPI, runs through the getting-started + 3-experiment flow on
their own real data, no blockers reported.

---

## v1.0.0rc2 — RC iteration (target: ~3 days, week 7.8)

Driven by rc1 tester reports. Zero new features.

**Cut criterion:** No P0/P1 reports for 48h after the last
rc-cycle commit. Documentation final. Compatibility matrix
verified across Python versions.

If rc2 produces fresh issues → rc3, etc. The version bumps until
the cut criterion is met. Don't ship 1.0.0 with known P0/P1.

---

## v1.0.0 — official release (target: week 8)

**Focus:** First stable release. Public API is committed —
breaking changes go in v2.x with a deprecation cycle.

**Promises Urika makes at v1.0:**

1. **Semantic versioning is binding.** v1.x.x = no breaking changes
   to documented public API. v2.0 telegraphs deprecations ≥ 6
   months in advance.
2. **Project file format stable.** `urika.toml`, `criteria.json`,
   `methods.json`, `progress.json`, `findings.json`,
   `memory/MEMORY.md` schemas don't break across v1.x. v0.x
   projects upgrade via `urika upgrade` (auto-migrate, idempotent).
3. **CLI command surface stable.** Existing commands keep their
   flags + behaviour. New commands may be added in v1.x; no
   command removed without v2 + deprecation cycle.
4. **Dashboard URL surface stable.** Existing routes keep their
   paths. Additions only in v1.x.
5. **Test coverage** — full pytest green on Linux + macOS +
   Windows + Python 3.11 / 3.12.
6. **Documentation comprehensive** — every command, every agent
   role, every config key documented in `docs/`.
7. **Security model documented** — clear threat model and
   permission boundaries.

---

## Cut from 1.0 — deferred to v1.1+

Documented here so they don't accidentally creep back in:

- **Project templates** (`urika new --template behavioral|...`).
  Cut 2026-06-10: the v0.8.0 research-scoping builder (feasibility
  check, preference/hypotheses/constraints elicitation, criteria
  co-drafting) solves the same "scope my project quickly and
  sensibly" problem with real elicitation rather than canned
  domain defaults — and the canned defaults risked anchoring users
  to the wrong analysis. Revisit post-1.0 only if users ask for
  one-command non-interactive starts; the likely v1.1 shape is
  saved answer-profiles for the existing builder, not static
  templates.
- **Plugin / extension system** (`urika.tools` / `urika.agents`
  entry points). API commitment problem — once you advertise a
  plugin API you can't break it without v2. Wait for real-world
  feedback after 1.0 to design it properly. v1.1 candidate.
- **GitHub thick** — OAuth flow, "Connect GitHub" dashboard
  button, audit log viewer, offline queue-and-retry, PR/issue
  surface. v0.7's auto-backup covers the high-frequency case;
  the thick experience is a v1.1+ feature.
- **arXiv fetcher** in literature agent. v1.1.
- **Plotly / Bokeh interactive figures.** v1.1.
- **Optuna hyperopt agent** as a new agent role. v1.1.
- **Run replay / decision-log HTML viewer.** v1.1 if requested.
- **Mobile-responsive dashboard.** Phone use case is covered by
  notifications (Slack/Telegram inline buttons for pause/stop/
  resume). v1.1 candidate only if users explicitly ask; the
  right v1.1 answer might be richer notification actions rather
  than a responsive dashboard.
- **Automatic model deployment** (HF Spaces, Modal, etc.). v2 at
  earliest.

## Off the runway entirely

Per the cross-cutting feature audit:

- **Multi-user / collaboration features.** Urika is single-user
  by design; collaboration happens via GitHub.
- **Telemetry / analytics on user data.** Privacy is the whole
  point.
- **Public-sharing button.** GitHub Pages from a Urika project
  is the path; we don't host content.
- **Deep CodaLab / BinderHub integration.** Use them via
  reproduce scripts; we don't own those surfaces.
- **AutoML platform integrations.** Off-positioning — agents are
  the strategy, not pre-baked AutoML.

---

## Calendar at a glance

```
Week 0     v0.4.0    SHIPPED ✅ 2026-05-02
Week 0.5   v0.4.x    hotfix/hardening train       SHIPPED ✅ (…v0.4.5.1)
Week 1.5   v0.5.0    memory phases 2–4            SHIPPED ✅ 2026-05-31
Week 3     v0.6.0    GitHub auto-backup           SHIPPED ✅ 2026-05-31 (order swapped 05-04)
Week 4     v0.7.0    multi-provider adapters      SHIPPED ✅ 2026-06-08
Week 5     v0.8.0    review hardening + scoping   SHIPPED ✅ 2026-06-10 (unplanned insertion)
Week 5.5   v0.9.0    PDF/LaTeX/Jupyter export + model cards + CIs   ← NEXT (~2 wks)
Week 7.5   v0.10.0   urika upgrade + wizard persistence + env isolation + a11y (~1 wk)
Week 8.5   v1.0.0rc1 feature freeze + API audit + migration guide
Week 9     v1.0.0rc2 RC feedback fixes only
Week 9.5   v1.0.0    OFFICIAL RELEASE 🎉
```

(Weeks re-baselined 2026-06-10 from the v0.8.0 ship date; at the
~4–5 dev-days/week cadence that puts v1.0.0 around mid-July 2026.
Templates cut; `urika upgrade` + pre-1.0 hardening take the slot.)

**Remaining from v0.8.0: ~18 dev-days over ~4 weeks** (~4–5
dev-days per week sustained). Mobile dashboard and project
templates explicitly cut — the phone use case is the notification,
not the browser, and the scoping use case is the v0.8.0 builder,
not canned defaults. v0.6 includes optional
`--create` shell-out to the `gh` CLI for one-command repo
creation; Urika never manages GitHub credentials directly.

---

## Cut-criterion philosophy

Every release ships only when its cut criterion is met. v1.0.0
in week 8 is irrelevant if v1.0.0 has P0/P1 defects — the version
number is the contract, the schedule is a guess.

This protects the v1.0.0 commitment. Real users at v1.0 expect
real stability; releasing on schedule with known bugs would burn
trust permanently.

---

## Plan-doc hygiene rules

To stop `dev/plans/` drifting again:

1. **Active plans live in `dev/plans/`** — at most one plan per
   in-flight release. Once a release ships, its plan moves to
   `dev/archive/plans/<release>-shipped/` in the same commit
   that bumps the version.
2. **One roadmap doc only** — this file. Each shipped release
   gets a "✅ SHIPPED" annotation here; the file is not
   duplicated.
3. **Bug backlog is one file** —
   `dev/plans/v0.X.x-bug-backlog.md` refreshed per release
   window, archived alongside the release when the window closes.
4. **Cut-from-1.0 list is binding** — items in "Cut from 1.0"
   are not implemented before 1.0 without a documented
   re-evaluation. Don't accidentally resurrect a deferred item.
