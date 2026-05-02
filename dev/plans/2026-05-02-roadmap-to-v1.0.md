# Roadmap: v0.4.0 → v1.0.0

**Authored:** 2026-05-02 (day v0.4.0 shipped to PyPI).
**Status:** Active — supersedes
`dev/archive/plans/v0.4-shipped/2026-04-30-v0.4-roadmap.md`.
**Total horizon:** ~5–6 months working calendar.

This document is the single source of truth for what ships when
between v0.4.0 (released today) and v1.0.0 (the official, no-pre-
release-suffix milestone). Every release has a defined **focus**, a
**cut criterion**, and explicit **what does and does not ship**.

The discipline:

- **Major-feature releases (.0)** — net-new surfaces, may break
  things subtly, expected to wobble in real use.
- **Hotfix releases (.x)** — bugfixes only, no new features. Each
  major-feature release is followed by a 2–4 week stabilisation
  window before the next major feature batch starts.
- **No version skips** for new features. v0.4 → v0.5 → v0.6 → v0.7
  → v1.0.0rcN → v1.0.0. The gap from v0.4 to v1.0.0 is roughly
  half a year.
- **Feature freeze starts at v0.7.0.** Anything not in v0.7.0
  rolls to v1.1+. The v1.0.0rc cycle is bug-fix only.

---

## v0.4.0 — SHIPPED 2026-05-02

First feature-complete v0.4. Bundles five tracks (SecurityPolicy
enforcement, multi-provider runtime abstraction, project memory
Phase 1, experiment comparison view, dataset hash + drift, cost-
aware budget, shell completion, sessions list/export) plus
post-rc2 hardening (Bearer-token auth for non-Anthropic private
endpoints, trailing-exit-1 tolerance, reasoning/execution model
split, --reset-models flag + dashboard button, max_turns 10→5,
project-narrative removal from per-experiment finalize, Windows
Unicode fixes, doc reorg 20→32 pages).

See `CHANGELOG.md` for the full per-fix accounting.

---

## v0.4.1 — bug-fix hotfix (target: ~1 week, 2026-05-09)

**Focus:** Close known defects discovered immediately after v0.4.0
ship. Driven by `dev/plans/2026-05-02-v0.4.x-bug-backlog.md`.

**Ships:**

1. **Dashboard footer model + agent fields display** — currently
   shows `—` for both during a running experiment. SSE wiring
   issue between the run-log streamer and the status-bar
   subscriber. ~0.5 day.
2. **Prompt-bloat trim + per-endpoint context_window declaration**
   — the work tracked in
   `2026-05-02-prompt-bloat-and-context-budget.md` Layers 1+2.
   Trim duplicated history/methods/criteria from advisor +
   planner system prompts; add `[privacy.endpoints.<n>]
   context_window = N` and `max_output_tokens = N` per-endpoint
   declarations. Unblocks 32K-context private endpoints. ~1.5 days.
3. **SIGTERM-after-criteria-met → exit 0, status `completed-narrative-pending`** — `cli/run.py` cleanup handler currently always exits
   1 with status `stopped`, even when the experiment is already
   complete on disk. Distinguish "agent crashed" from "stopped
   while writing the tail narrative". ~0.5 day.
4. **Per-tool-call Bash timeout** — configurable
   `[preferences].max_method_seconds` (default 24h). Hung
   subprocess fails the method instead of hanging the experiment
   forever. ~0.5 day.
5. **Long-running training cookbook entry** — checkpoint pattern
   docs so a SIGKILL'd 5-hour training run can resume from the
   most recent checkpoint instead of retraining from scratch.
   Docs only. ~0.25 day.

**Cut criterion:** Mike's lab (3-4 testers) and Cathy on Windows
report no fresh blockers from a week of real-world use. Fixed bugs
have regression tests. Full pytest green.

---

## v0.4.2 — tester-driven hotfix (target: ~2 weeks after v0.4.1)

**Focus:** Real user reports from the v0.4.0 / v0.4.1 testing
window. Reserved bucket — don't pre-fill.

**Cut criterion:** The next month of tester use surfaces no
blockers; the bug backlog file has zero open P0/P1 entries.

**Ship if reported:** anything that would otherwise burn user
trust before the v0.5 feature surface lands.

---

## v0.5.0 — feature expansion (target: 5–7 weeks after v0.4.2)

**Focus:** Add the new surfaces deferred from v0.4 because v0.4
needed a contained testing target. v0.5 is the broadest feature
batch in the v0.4→v1.0 trajectory.

**Ships:**

1. **GitHub integration (thick)** — pygit2 + device-flow OAuth +
   dashboard "Connect GitHub" button + per-project Git tab + audit-log
   viewer + offline queue-and-retry. Full design preserved at
   `dev/plans/2026-04-30-github-integration.md`. ~24 dev-days.
   Dominates the budget. Enables: experiment-as-commit, project-as-
   repo, automatic backup, multi-machine continuity.
2. **OpenAI Agents SDK adapter end-to-end** — second working agent
   backend on top of v0.4's thin abstraction. Validates the
   `urika.runners` entry-point boundary. ~6–7 days.
3. **Project memory Phases 2–4** — curator agent (auto-organises
   captured `<memory>` markers), archive viewer (browse old
   memory entries), diff view (memory evolution across sessions).
   Phase 1 already shipped in v0.4. ~5 days.
4. **Project templates** — `urika new --template
   behavioral|timeseries|imaging|nlp|ml-baseline` with seeded
   criteria, recommended tools, a 1-2 paper sample knowledge entry,
   and a `data-description.md` skeleton. ~3 days.
5. **Plugin / extension system via Python entry points** — third
   parties (or future-us) ship `urika-plugin-eeg` /
   `urika-tool-fmri` / etc. as installable PyPI packages that
   surface tools, agent roles, or templates without forking. The
   v0.4 `urika.runners` entry-point is the prototype; this expands
   to `urika.tools`, `urika.agents`, `urika.templates`. ~4 days.

**Total:** ~42 dev-days (~6 weeks at sustained pace, longer with
parallel testing).

**Cut criterion:** All five surfaces have full pytest coverage,
GitHub integration has been exercised against a real GitHub
account end-to-end, the OpenAI adapter has run a complete
experiment loop, project-memory diff view renders correctly in
both dashboard and TUI, project-template + plugin generators
produce valid project trees.

---

## v0.5.x — stabilisation (target: 3–4 weeks after v0.5.0)

**Focus:** Bug-fix series. The new surfaces in v0.5.0 will wobble;
this is when. GitHub OAuth in particular is a stress point — it
touches the secret vault, the dashboard authentication, and a
new I/O path with retry semantics.

**Cut criterion:** Two consecutive weeks with zero P0/P1 reports
from active testers. Bug backlog file has zero open P0/P1.

**No new features.** If a feature request arrives during this
window, it goes to v0.6.0 or later.

---

## v0.6.0 — output polish (target: ~4 weeks after v0.5.x stable)

**Focus:** Make the project's outputs publication-ready. v0.4-0.5
prove the agents do good science; v0.6 makes the artifacts
shippable to a paper, a poster, a thesis chapter.

**Ships:**

1. **PDF / LaTeX export** — `urika report --format pdf` /
   `--format latex`. Pandoc-based. Default theme matches the
   existing reveal.js light/dark aesthetic. ~4 days.
2. **Jupyter notebook export** — `urika finalize --jupyter`
   produces a `reproduce.ipynb` alongside `reproduce.sh`. Each
   final method becomes a cell, with markdown intros pulled
   from `findings.json`. ~4 days.
3. **arXiv fetcher in literature agent** — given a query, the
   literature agent fetches abstracts from the arXiv API,
   summarises, and stores the top-N to `knowledge/papers/`. Also
   `urika knowledge fetch arxiv:<query>`. ~3 days.
4. **Plotly / Bokeh interactive figures** — opt-in via
   `[preferences].interactive_figures = true`. Task agent prompt
   gains a "if you build a figure that benefits from interaction
   (zoom, hover, dropdown), use Plotly and save as
   `<artifact>.html` alongside the PNG". ~3 days.
5. **Model-card auto-generation** — each finalized method gets a
   `methods/<method>_model_card.md` describing assumptions, data
   used, train/test split, intended use, and known limitations.
   The Hugging Face model-card template, adapted. ~3 days.
6. **Optuna hyperopt agent** — new agent role
   `hyperopt_agent` that wraps Optuna for systematic
   hyperparameter search. Triggered when the planning agent flags
   "I'd like to tune `n_estimators` × `max_depth` × `learning_rate`
   for this method". ~5 days.

**Total:** ~22 dev-days (~3-4 weeks).

**Cut criterion:** Each export format produces a valid file that
opens in its target reader. arXiv fetcher hits the live API
without rate-limit issues over a 50-query test. Plotly figures
render in both the dashboard and a downloaded HTML file. Optuna
agent runs a 20-trial sweep on a Stroop-sized dataset within
30 min.

---

## v0.6.x — stabilisation (target: 2–3 weeks after v0.6.0)

**Focus:** Bug-fix series for v0.6.0 surfaces.

**Cut criterion:** Same as v0.5.x — two clean weeks, zero P0/P1
backlog.

---

## v0.7.0 — UX polish + final feature work (target: ~3 weeks)

**Focus:** Feature-complete the v1.0.0 surface. After v0.7.0,
**no new features** until v1.1.0 ships post-1.0.

**Ships:**

1. **Mobile-responsive dashboard** — the dashboard already works
   on tablets but breaks below ~600px width. Make it usable on
   a phone for the "watch a long autonomous run from anywhere"
   case. ~3 days.
2. **Run replay / decision-log export** — given a completed
   experiment, replay the agent decisions chronologically as a
   self-contained HTML viewer. Useful for teaching, reviews, and
   reproducibility audits. ~4 days.
3. **Accessibility pass** — keyboard navigation through every
   dashboard form, focus states, ARIA labels on icon-only buttons,
   colour-contrast audit of light + dark themes. ~3 days.
4. **i18n stubs** — extract user-facing strings into a single
   `urika/i18n/en.toml` so future translations are mechanical.
   Don't ship any actual translations in v0.7. ~2 days.
5. **Final API audit** — every public function in
   `urika.core.*`, `urika.agents.*`, `urika.tools.*` gets a
   stability review. Stuff users will rely on at v1.0 gets a
   proper docstring; stuff that's an implementation detail moves
   to a `_` prefix. ~3 days.
6. **CHANGELOG → release notes** — extract every "Fixed" /
   "Added" / "Changed" entry from v0.4.0 forward into a
   user-facing migration guide. ~1 day.

**Total:** ~16 dev-days (~3 weeks).

**Cut criterion:** Mobile dashboard works on iPhone Safari +
Android Chrome. Every public function has a docstring. The
migration guide reads cleanly to a new user.

---

## v0.7.x — final stabilisation (target: 2–3 weeks)

**Focus:** Last bug-fix window before the v1.0.0 release-candidate
cycle starts.

**Cut criterion:** Two consecutive weeks of zero P0/P1 reports.
Test suite ≥ 95% coverage on every public-API module. Full pytest
green on Python 3.11 + 3.12 + 3.13. Documentation cross-reference
sweep clean.

---

## v1.0.0rc1 — first release candidate (target: ~1 week)

**Focus:** Cut a release-candidate from `v0.7.x` and start the RC
cycle. **Feature freeze is hard from this point** — no new
features merge until v1.0.0 ships.

**Ships:**

- Same code as the latest v0.7.x patch, with `version =
  "1.0.0rc1"` in `pyproject.toml`.
- Migration guide finalised.
- Public API documented end-to-end.
- Test matrix expanded: pytest on Linux + macOS + Windows + GitHub
  Actions.
- Docker image (`xkiwilabs/urika:1.0.0rc1`) for CI / cloud-run
  cases.

**Cut criterion:** Tester pool (5–10 people) installs rc1 from
PyPI, runs through the getting-started + 3-experiment flow on
their own real data, no blockers reported.

---

## v1.0.0rc2 … rcN — RC iterations (target: 2–4 weeks total)

**Focus:** Driven by RC tester reports. Each rc bump fixes the
issues from the previous one. Zero new features.

**Cut criterion for the final rc:** No P0/P1 reports for one full
week from the last rc. Documentation is final. Compatibility
matrix verified.

---

## v1.0.0 — official release (target: ~5–6 months from today)

**Focus:** The first stable release. Public API is committed —
breaking changes go in v2.x with a deprecation cycle.

**Promises Urika makes at v1.0:**

1. **Semantic versioning is binding.** v1.x.x = no breaking changes
   to documented public API. v2.0 will telegraph deprecations
   ≥ 6 months in advance.
2. **Project file format stable.** `urika.toml`, `criteria.json`,
   `methods.json`, `progress.json`, `findings.json`,
   `memory/MEMORY.md` schemas don't break across v1.x. v0.x
   projects upgrade via `urika upgrade` (auto-migrate, idempotent).
3. **CLI command surface stable.** Existing commands keep their
   flags + behaviour. New commands may be added; no command
   removed without v2 + deprecation cycle.
4. **Dashboard URL surface stable.** Existing routes
   (`/projects/<n>/...`) keep their URLs. New routes may be
   added; no route removed without v2 + deprecation cycle.
5. **Test coverage ≥ 95%** on public-API modules; pytest green
   on Linux + macOS + Windows + Python 3.11 / 3.12 / 3.13.
6. **Documentation comprehensive** — every command, every agent
   role, every config key documented in user-facing
   `docs/`.
7. **Security model documented and audited** — third-party
   review of the SecurityPolicy + secret-vault paths.

---

## Off the runway (skipped entirely)

Documented here so they don't get re-litigated:

- **Multi-user / collaboration features.** Urika is single-user
  by design; collaboration happens via GitHub.
- **Telemetry / analytics on user data.** Privacy is the whole
  point; nothing leaves the user's machine without their action.
- **Public-sharing button.** GitHub Pages from a Urika project
  is the path; we don't host content.
- **Deep CodaLab / BinderHub integration.** Use them via the
  reproduce script; we don't own those surfaces.
- **AutoML platform integrations** (Auto-sklearn, FLAML, H2O).
  Off-positioning — agents are the strategy, not pre-baked
  AutoML.

---

## v1.1+ — after the freeze

Backlog reset at v1.0.0. The first v1.1 features are then driven
by what real-world v1.0 users ask for, not what we predict today.
Plausible early v1.1 candidates (don't commit yet):

- Multi-provider parity audit (Google ADK, Mistral, local
  llama.cpp).
- Notebook-driven workflows (run a Urika experiment from a
  Jupyter cell).
- Project-comparison view (cross-project leaderboard).
- Long-form research-paper drafting agent.

These are illustrative, not promises.

---

## Cut-criterion philosophy

**Every release in this roadmap has a single hard rule:** the
release does not ship until its cut criterion is met, even if
the calendar slips. Calendar dates above are *targets*, not
deadlines. v1.0.0 by month X is irrelevant if v1.0.0 has known
P0/P1 defects — the version number is the contract, the schedule
is a guess.

This protects the v1.0.0 commitment. Real users at v1.0 expect
real stability; releasing on schedule with known bugs would burn
that trust permanently.

---

## Plan-doc hygiene rules

To stop the dev/plans/ directory drifting again:

1. **Active plans live in `dev/plans/`** — at most one plan per
   in-flight release. Once a release ships, its plan moves to
   `dev/archive/plans/<release>-shipped/` in the same commit
   that bumps the version.
2. **One roadmap doc only** — this file. When v0.5.0 ships, this
   file's v0.5 section gets a "✅ SHIPPED" annotation; the file
   is not duplicated.
3. **Bug backlog is one file** — `dev/plans/v0.X.x-bug-backlog.md`
   refreshed per release window, archived alongside the release
   when the window closes.
4. **Off-runway list is binding** — items here are not implemented
   without a documented re-evaluation. Don't accidentally
   resurrect a skip-list item.
