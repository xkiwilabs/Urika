# Urika test layers — what each is for, where to add coverage

This is the map of the test stack. The recurring failure mode in
v0.4.x has been "a regression shipped because no layer was watching the
thing that broke." When you add a feature, find the layer(s) below that
should cover it and add the test *there* — not just a unit test that
mocks away the very thing that breaks.

`dev/testing-plan.md` is a different doc: it lists the 10 real-data
scenario projects the e2e smoke exercises. This doc is about the
*structure* of the test suite.

---

## The layers

### 1. Unit tests — `tests/test_*/` (default `pytest`)

Pure-Python correctness. The Claude SDK / agent subprocess is **not**
real here — orchestrator/agent tests inject a `FakeRunner` /
`FailingRunner` / `_ScriptedRunner` that returns canned text. So unit
tests **cannot** catch: prompt/parser drift, sandbox denials in a real
run, what a *messy* real LLM response does, or the content of
agent-written files. Don't rely on them for those.

Run the unit suite with:

```bash
URIKA_SKIP_SMOKE=1 pytest -q -m "not integration"
```

> ⚠️ A bare `pytest -q` (no `-m` filter) **also runs the
> `@pytest.mark.integration` tests, including the real-API e2e smoke**
> (`tests/test_smoke/`), which costs money and takes ~30–60 min.
> Always pass `-m "not integration"` (and `URIKA_SKIP_SMOKE=1`) for the
> fast loop. CI runs the unit matrix this way; `e2e-smoke.yml` runs the
> integration tier separately on a schedule.

### 2. Prompt ↔ parser contract — `tests/test_agents/test_prompt_parser_contract.py`

Extracts the ` ```json ` example block from each role's prompt
(`src/urika/agents/roles/prompts/<role>_system.md`) and asserts the
matching parser in `orchestrator/parsing.py` accepts it. **Edit a
prompt's output schema and a test goes red.** This is the cheapest
guard against the "prompt drift silently breaks every real run"
failure. When you add a parser or change a role's output JSON, update
this.

### 3. Orchestrator-loop behaviour — `tests/test_orchestrator/`

`test_loop.py` (happy path + lifecycle), `test_loop_messy_output.py`
(no fence / truncated / empty / error-string / wrong-schema agent
output → `warning` event + `failed`, never silent `completed`),
`test_loop_golden.py` (replays the realistic `tests/fixtures/transcripts/`
corpus through the loop — prose-around-the-JSON, exact prompt schema —
so prompt/parser drift breaks here), `test_loop_criteria.py`,
`test_meta.py` (the autonomous/meta loop + the fresh-project "seed a
baseline" safety net; the `urika run` non-`--auto` mirror lives in
`tests/test_cli/test_run_planning_seed_baseline.py`),
`test_finalize.py` / `test_loop_finalize.py` (the finalize sequence —
which artifacts get written, under what guards). Pause-vs-fail policy
(`_is_recoverable_failure`) is pinned here. Any new way the loop can
terminate, or a new "if it doesn't parse, fall back" branch, needs a
test here.

### 4. Interface-flow tests (still mostly mocked at the agent boundary)

- **Dashboard HTTP** — `tests/test_dashboard/` (FastAPI `TestClient`):
  request shaping, form validation, kwarg forwarding to
  `spawn_experiment_run`, the SSE-stream terminal-status logic.
- **Dashboard browser** — `tests/test_smoke/test_smoke_dashboard.py`
  (Playwright, `@pytest.mark.integration`, skipped if chromium absent):
  real browser + real uvicorn, agent subprocess stubbed. Covers the
  full "+ New project → enriched project on disk" (the modal is filled
  via the `_fill_new_project_form` test helper / `_NEW_PROJECT_EXAMPLE`
  — there is no "fill example" affordance in the production UI),
  "+ New experiment → run → SSE log page → terminal status (incl.
  launch-failed → `failed`)", and the page-render / vendored-asset
  checks. **This is the layer that catches UI plumbing bugs and
  browser-side JS errors** (e.g. the invalid `pattern` regex).
- **Seed a project from a real dataset (no LLM)** —
  `tests/test_integration_seed_from_dataset.py` (`@pytest.mark.integration`,
  skipped if `dev/test-datasets/` absent): runs
  `create_project_workspace` + `enrich_workspace` against a bundled
  test dataset directory (`dev/test-datasets/stroop`, `…/depression`)
  and asserts the resulting project is real — `[data]` block + drift
  hashes, seeded criteria, regenerated README, the `data-description.md`
  ingested into the knowledge store. Same path the dashboard's
  `POST /api/projects` uses.
- **CLI `urika run` outcomes** — `tests/test_cli_run_launcher.py`:
  with the orchestrator stubbed, a `failed` / `paused` / unknown run
  status is *visibly* reported. The TUI/REPL invoke this same command,
  so they inherit it.
- **TUI worker** — `tests/test_tui/test_agent_worker.py`: a blocking
  command that prints an error or raises surfaces it in the
  `OutputPanel` and clears the agent-running flag (no swallowed
  failures).
- **Interactive `urika new` builder loop** —
  `tests/test_cli/test_builder_loop.py` + `test_builder_usage.py`:
  drives `_run_builder_agent_loop` with a scripted fake runner +
  monkeypatched prompts. Covers the clarifying-question loop, advisor
  suggestions, planning, **messy planning-agent output doesn't crash
  the loop** (list-valued `metrics` etc.), and usage recording. This
  path is TTY-only and is *not* exercised by the e2e smoke (which uses
  `urika new --json`), so it needs its own coverage — three v0.4.4.1
  bugs lived here.

### 5. E2E smoke — `dev/scripts/smoke-v04-e2e-{open,hybrid,private}.sh`

Real Anthropic API (and, for hybrid/private, a real local endpoint).
Drives the *whole* pipeline: `urika new` → status/inspect → advisor →
build-tool → `urika run` → `urika run --max-experiments 2` → evaluate →
report → present → finalize. Cheap config by default (sonnet + haiku,
reduced turns, ~$0.50, ~10–15 min); `URIKA_SMOKE_REAL=1` flips to the
full-fidelity config (opus + 5 turns).

Crucially, the harness asserts the agents **did real work**, not just
that commands exited 0 — see the `verify_*` helpers in
`smoke-v04-e2e-common.sh`:

| helper | asserts |
|---|---|
| `verify_run_did_work` | latest experiment has ≥1 run + non-empty leaderboard |
| `verify_run_metrics_nonempty` | ≥1 run has a non-empty `metrics` dict |
| `verify_turns_ran` | session.json shows ≥1 completed loop turn |
| `verify_methods_consistent` | `methods.json` ↔ `progress.json` ↔ `leaderboard.json` mutually consistent |
| `verify_figures_produced` | ≥1 diagnostic figure under `experiments/*/artifacts/` |
| `verify_min_experiments` / `verify_each_experiment_did_work` | meta loop ran ≥N experiments, each recording ≥1 run |
| `verify_findings_nonempty` | `findings.json` has an `answer` + ≥1 final method |
| `verify_finalize_artifacts_real` | `requirements.txt` lists real packages; `reproduce.sh` has a shebang + references `requirements.txt` + runs a `methods/final_*.py`; ≥1 valid standalone `final_*.py`; (under `URIKA_SMOKE_REAL`) `requirements.txt` installs in a clean venv |
| `verify_no_early_exit_markers` | run.log has no "failed after 1 turn" / "paused after turn 1" / "Experiment failed:" / "no further experiments to suggest" / "but recorded 0 runs" |

**A green e2e is meant to mean: a real project was created with real
criteria; the loop ran multiple experiments each recording runs with
real metrics; bookkeeping is internally consistent; the finalizer
produced a usable findings.json + an installable requirements.txt + a
runnable-shaped reproduce.sh + standalone code that imports.** The
honest residual gap is *semantic* correctness of agent-written prose /
code — that's what `URIKA_SMOKE_REAL` + eyeballing the dashboard is
for.

### 6. Nightly CI — `.github/workflows/e2e-smoke.yml`

Runs the cheap-config open-mode e2e smoke on a schedule + on demand,
with `ANTHROPIC_API_KEY` from secrets. Skipped on the public mirror via
`if: github.repository == 'xkiwilabs/urika-dev'`. This is the canary
that catches prompt/parser drift and early-exit regressions between
releases — haiku-as-task-agent is *more* likely to produce the messy
output that triggers them, so it's a good stress test.

---

## Known coverage gaps (keep this list honest)

- **The agent-written content's *semantic* quality** — whether the
  finalizer's prose actually answers the question, whether the
  generated method code is *correct* (not just syntactically valid and
  importable). No automated check can close this; `URIKA_SMOKE_REAL=1`
  + eyeballing the dashboard is the process.
- **The dashboard "can't create with a real question" report** (a beta
  user: a substantial research question / description blocks the create
  button; "x" in every field works). The v0.4.4.1 TOML control-char
  fix (`workspace._toml_basic_string`) is the most likely cause and is
  covered by tests, but it's *unconfirmed* — needs the beta user's
  browser console + network response to be sure it isn't another layer.
- **ui-iterate** (Playwright MCP visual-polish loop) is available for
  manual layout/hover passes over the dashboard — not wired into CI.

_Recently closed:_ `reproduce.sh` execution → `tests/test_integration_reproduce.py`
runs the finalizer's `reproduce.sh` template (venv → install → run a
`final_*.py`) end to end. The `run_planning` "seed a baseline" mirror →
done (`cli/run_planning._determine_next_experiment` + tests). A golden
transcript corpus → `tests/fixtures/transcripts/` replayed by
`tests/test_orchestrator/test_loop_golden.py`.

## Convention reminders

- New agent role / new prompt JSON schema → update
  `test_prompt_parser_contract.py`.
- New artifact the orchestrator/finalizer writes → add an existence +
  *content* check to the e2e (`verify_*` helper) **and** a unit test of
  the writer.
- New way the run loop can terminate → a `test_loop*.py` test.
- New dashboard form / flow → a `test_dashboard/` HTTP test **and** a
  Playwright flow test in `test_smoke_dashboard.py`.
- Anything in the interactive `urika new` path → `test_builder_loop.py`.
