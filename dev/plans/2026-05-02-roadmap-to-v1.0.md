# Roadmap: v0.4.0 → v1.0.0

**Authored:** 2026-05-02 (day v0.4.0 shipped to PyPI).
**Last revised:** 2026-05-02 (compacted to 8-week v1.0 target after
review).
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
- **Feature freeze starts at v1.0.0rc1.** Anything not in v0.9.0
  rolls to v1.1+. The RC cycle is bug-fix only.
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

## v0.5.0 — project memory deepening (target: ~1 week, week 1.5)

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

## v0.6.0 — OpenAI adapter + project templates (target: ~1.5 weeks, week 3)

**Focus:** Two unrelated capabilities that are each small enough to
share a release.

**Ships:**

1. **OpenAI Agents SDK adapter** — second working agent backend on
   top of v0.4's thin abstraction. Validates the `urika.runners`
   entry-point boundary. End-to-end: a project configured with the
   OpenAI runner runs the full experiment loop (planner → task →
   evaluator → advisor) and produces the same artifacts as the
   Anthropic runner. ~6 days.
2. **Project templates** — `urika new --template
   behavioral|timeseries|imaging|nlp|ml-baseline` with seeded
   criteria, recommended tools, sample knowledge entries, and a
   `data-description.md` skeleton. ~3 days.

**Cut criterion:** A complete experiment runs on the OpenAI
adapter end-to-end (behavioural-data fixture). All 5 templates
produce valid project trees with `urika new --template <name>`.
The OpenAI adapter passes the same `tests/test_agents/` battery
as the Anthropic adapter for behaviours that aren't
Anthropic-specific.

---

## v0.7.0 — GitHub auto-backup (target: ~1 week, week 4)

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

## v0.8.0 — output polish (target: ~1.5 weeks, week 5.5)

**Focus:** Make Urika's outputs publication-ready. v0.4–0.7 prove
the agents do good science; v0.8 makes the artifacts shippable to
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

**Cut criterion:** Every export format produces a valid file that
opens in its target reader (Acrobat / Overleaf / JupyterLab).
The Jupyter notebook runs end-to-end on a fresh kernel without
errors. Model cards exist for every finalized method in a real
test project.

---

## v0.9.0 — accessibility + i18n stubs (target: ~3 days, week 6.5)

**Focus:** Last release before feature freeze. The system is
desktop-finished; mobile responsiveness is *not* a 1.0 goal (the
mobile use case is "check on a long-running run while away from
my desk", which is already covered by Slack/Telegram
notifications shipped in v0.3).

**Ships:**

1. **Accessibility pass** — keyboard navigation through every
   form, focus states, ARIA labels on icon-only buttons,
   colour-contrast audit of light + dark themes. ~2 days.
2. **i18n string-extraction stubs** — extract user-facing strings
   into `urika/i18n/en.toml` so future translations are
   mechanical. No actual translations shipped. ~1 day.

**Cut criterion:** axe-core / WAVE accessibility audit returns
zero P0/P1 issues. Every user-facing CLI + dashboard string is in
`en.toml`.

**Explicitly NOT in v1.0:** mobile-responsive dashboard. The phone
use case is the notification (Slack/Telegram inline-keyboard
buttons for pause/stop/resume — already shipped in v0.3). If real
users at v1.0 ask for in-browser mobile experience, it's a v1.1
candidate; the right v1.1 answer might be richer notification
actions instead of a responsive dashboard.

---

## v1.0.0rc1 — first release candidate (target: ~3 days, week 7.5)

**Focus:** Cut a release-candidate from `v0.9.0` and start the RC
cycle. **Feature freeze is hard from this point** — no new features
merge until v1.0.0 ships.

**Ships:**

- Same code as v0.9.0, with `version = "1.0.0rc1"` in
  `pyproject.toml`.
- **Final API audit** — every public function in `urika.core.*`,
  `urika.agents.*`, `urika.tools.*` reviewed. Stable API gets a
  proper docstring; implementation detail moves to `_` prefix.
- **CHANGELOG → migration guide** — extract every "Fixed" /
  "Added" / "Changed" entry from v0.4.0 forward into a
  user-facing upgrade guide.
- **Test matrix expansion** — pytest on Linux + macOS + Windows
  via GitHub Actions, Python 3.11 + 3.12.

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
Week 0     v0.4.0    SHIPPED ✅
Week 0.5   v0.4.1    bug-fix hotfix (5 items)
Week 1.5   v0.5.0    memory phases 2–4
Week 3     v0.6.0    OpenAI adapter + project templates
Week 4     v0.7.0    GitHub auto-backup
Week 5.5   v0.8.0    PDF/LaTeX/Jupyter export + model cards
Week 6.5   v0.9.0    accessibility + i18n stubs
Week 7     v1.0.0rc1 feature freeze + API audit
Week 7.3   v1.0.0rc2 RC feedback fixes only
Week 7.5   v1.0.0    OFFICIAL RELEASE 🎉
```

**Total: ~32 dev-days over ~7.5 weeks** (~4–5 dev-days per week
sustained). Mobile dashboard explicitly cut — the phone use case
is the notification, not the browser.

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
