# Running Operations + Log Streaming Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Make agent operations (summarize / finalize / evaluate / report / present / build-tool / experiment run) safe to interact with from any page of the dashboard. The user should never lose track of what's running, never trigger an accidental duplicate, and always have a one-click path back to the live log stream.

**Architecture:** Lock-file-as-truth. Each spawn helper already drops a `.lock` file with the child PID; the file disappears when the drainer thread sees the subprocess exit. A new `list_active_operations(project_path)` helper walks all known lock-file shapes, filters to live PIDs, and returns a structured list. Every UI surface and every POST endpoint reads from that one source.

**Tech stack:** Existing FastAPI + HTMX + Alpine + Jinja. No new dependencies. Reuses `_is_active_run_lock` / `_pid_is_alive` from `urika.core.project_delete`.

**Out of scope:** Cancellation UX (we already have a Stop button on `run_log.html`; not extending to other op types in this phase). Notifications when a background op completes (separate feature).

---

## Phase B1 — Active operations helper

### Task B1.1: `list_active_operations()` core helper

**Files:**
- Create: `src/urika/dashboard/active_ops.py`
- Test: `tests/test_dashboard/test_active_ops.py`

**Step 1: Write failing tests**

Cover:
- No locks → returns empty list.
- Live `.summarize.lock` (PID = test process) → returns one `ActiveOp` with `type="summarize"`, correct `log_url`, `lock_path`, `experiment_id=None`.
- Live `experiments/exp-001/.lock` → returns `type="run"`, `experiment_id="exp-001"`, `log_url="/projects/<n>/experiments/exp-001/log"`.
- Live `experiments/exp-001/.evaluate.lock` → `type="evaluate"`, `experiment_id="exp-001"`, `log_url=".../log?type=evaluate"`.
- Same for `.report.lock` (`?type=report`) and `.present.lock` (`?type=present`).
- Live `tools/.build.lock` → `type="build_tool"`, `experiment_id=None`, `log_url="/projects/<n>/tools/build/log"`.
- Live `projectbook/.finalize.lock` → `type="finalize"`, `log_url="/projects/<n>/finalize/log"`.
- Stale lock (PID=99999999) → not returned.
- Empty `.lock` file → not returned (matches `_is_active_run_lock` semantics).
- `criteria.json.lock` (filelock mutex, no leading dot in basename) → not returned (verifies the dot-prefix rule still applies).

**Step 2: Implement**

```python
"""Detect and describe currently-running agent operations for a project.

Single source of truth for which ``.lock`` files indicate a live
operation. UI buttons, the project banner, and the spawn endpoints
all read from here so they agree on what's running.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from urika.core.project_delete import _is_active_run_lock


@dataclass(frozen=True)
class ActiveOp:
    """A running agent operation, located by its lock file."""

    type: str                     # "run" | "evaluate" | "report" | "present" |
                                  # "summarize" | "finalize" | "build_tool"
    project_name: str
    experiment_id: str | None     # None for project-level ops
    lock_path: Path
    log_url: str                  # absolute path under /projects/...


# Lock-file shapes we know about. Order matters only for the "more
# specific first" rule — match longer suffixes before bare ".lock".
_PROJECT_LEVEL_LOCKS: tuple[tuple[str, str, str], ...] = (
    # (lock relative path, op type, log url template — uses {project} placeholder)
    ("projectbook/.finalize.lock",  "finalize",   "/projects/{project}/finalize/log"),
    ("projectbook/.summarize.lock", "summarize",  "/projects/{project}/summarize/log"),
    ("tools/.build.lock",            "build_tool", "/projects/{project}/tools/build/log"),
)

_EXPERIMENT_LEVEL_LOCKS: tuple[tuple[str, str, str | None], ...] = (
    # (lock filename within experiments/<id>/, op type, log query type or None for run)
    (".evaluate.lock", "evaluate", "evaluate"),
    (".report.lock",   "report",   "report"),
    (".present.lock",  "present",  "present"),
    (".lock",          "run",      None),  # bare .lock is the experiment run
)


def list_active_operations(
    project_name: str, project_path: Path
) -> list[ActiveOp]:
    """Walk known lock shapes; return only those with a live PID."""
    if not project_path.exists():
        return []

    ops: list[ActiveOp] = []

    # Project-level locks at fixed paths.
    for rel, op_type, url_template in _PROJECT_LEVEL_LOCKS:
        lock = project_path / rel
        if lock.is_file() and _is_active_run_lock(lock):
            ops.append(
                ActiveOp(
                    type=op_type,
                    project_name=project_name,
                    experiment_id=None,
                    lock_path=lock,
                    log_url=url_template.format(project=project_name),
                )
            )

    # Per-experiment locks. Scan experiments/<id>/<lockname>.
    exp_root = project_path / "experiments"
    if exp_root.is_dir():
        for exp_dir in exp_root.iterdir():
            if not exp_dir.is_dir():
                continue
            for lock_name, op_type, log_type in _EXPERIMENT_LEVEL_LOCKS:
                lock = exp_dir / lock_name
                if lock.is_file() and _is_active_run_lock(lock):
                    base = (
                        f"/projects/{project_name}/experiments/"
                        f"{exp_dir.name}/log"
                    )
                    log_url = base if log_type is None else f"{base}?type={log_type}"
                    ops.append(
                        ActiveOp(
                            type=op_type,
                            project_name=project_name,
                            experiment_id=exp_dir.name,
                            lock_path=lock,
                            log_url=log_url,
                        )
                    )
                    break  # one op per experiment dir is enough — locks are exclusive

    return ops
```

**Step 3: Verify tests pass.**

**Step 4: Commit** — `feat(dashboard): list_active_operations helper detects live agent locks`

---

## Phase B2 — Idempotent spawn endpoints

### Task B2.1: Refuse duplicate spawns; redirect to running log

**Files:**
- Modify: `src/urika/dashboard/routers/api.py` (every POST that spawns: summarize, finalize, evaluate, report, present, build-tool, experiment run)
- Test: extend `test_api_summarize.py`, `test_api_finalize.py`, `test_api_evaluate.py`, `test_api_report.py`, `test_api_present.py`, `test_api_build_tool.py`, `test_api_run.py`

**Step 1: Write failing tests**

For each of the 7 spawn endpoints, add:
- `test_<op>_post_when_already_running_redirects_to_log` — drop a live PID lock at the canonical path before posting. Assert:
  - Response is 200 with `HX-Redirect` to the running op's log URL when called from HTMX.
  - Response is 409 (or 200 with a `{"status": "already_running", "log_url": ...}` JSON body — pick one and stick with it; HX-Redirect wins for HTMX, JSON 409 for non-HTMX). The spawn helper is NOT called.
  - For experiment-level ops, the test uses `experiments/<id>/<the right .lock name>`.

**Step 2: Implement**

In each POST handler, BEFORE calling the spawn helper, check `list_active_operations(project_name, project_path)`. If an op of the same `type` (and matching `experiment_id` for experiment-level ops) is already running:
- HTMX request → return `Response(status_code=200, headers={"HX-Redirect": op.log_url})`
- non-HTMX → return `JSONResponse({"status": "already_running", "log_url": op.log_url, "type": op.type}, status_code=409)`

Do this with a tiny helper to avoid copy-paste:

```python
def _redirect_if_running(
    project_name: str,
    project_path: Path,
    op_type: str,
    request: Request,
    *,
    experiment_id: str | None = None,
) -> Response | JSONResponse | None:
    """If an op of this type is already running, return the redirect/409.
    Otherwise return None and let the caller spawn."""
    from urika.dashboard.active_ops import list_active_operations

    for op in list_active_operations(project_name, project_path):
        if op.type != op_type:
            continue
        if experiment_id is not None and op.experiment_id != experiment_id:
            continue
        if request.headers.get("hx-request") == "true":
            return Response(status_code=200, headers={"HX-Redirect": op.log_url})
        return JSONResponse(
            {"status": "already_running", "log_url": op.log_url, "type": op_type},
            status_code=409,
        )
    return None
```

Then each handler:

```python
existing = _redirect_if_running(name, summary.path, "summarize", request)
if existing is not None:
    return existing
# proceed to spawn ...
```

For experiment-level ops, pass `experiment_id=exp_id` so two different experiments running evaluators in parallel still each get to spawn (different lock paths).

Also: leave the `_validate_privacy_endpoint` pre-flight gate WHERE IT IS (before the spawn). The `_redirect_if_running` check goes BEFORE the privacy gate — if it's already running, we don't need to revalidate privacy.

**Step 3: Verify tests.**

**Step 4: Commit** — `feat(dashboard): spawn endpoints redirect to existing log when op already running`

---

## Phase B3 — Buttons reflect running state

### Task B3.1: Pass running flags to relevant templates

**Files:**
- Modify: `src/urika/dashboard/routers/pages.py` (`project_home`, `experiment_detail`, the project-tools view if it has the build-tool button)
- Modify: `src/urika/dashboard/templates/project_home.html` — Summarize and Finalize buttons
- Modify: `src/urika/dashboard/templates/experiment_detail.html` — Evaluate, Report, Presentation buttons
- Modify: `src/urika/dashboard/templates/tools.html` — Build tool button (project scope)
- Test: extend `test_pages_project.py` and `test_pages_tools_criteria.py`

**Step 1: Tests**

For each affected page, add tests that:
- Without a running op, the button reads its normal label and posts to the form modal.
- With a live lock for that op type, the button reads `<verb> running… view log` (e.g. "Summarize running… view log") and links directly to the running op's `log_url` (an `<a href>`, NOT a button that opens a modal).
- The button's CSS class includes a `running` modifier so we can style it (subtle pulsing dot, accent border).

**Step 2: Implement**

In the page route handler:

```python
from urika.dashboard.active_ops import list_active_operations

active = list_active_operations(name, summary.path)
running_by_type = {op.type: op for op in active}
# For experiment_detail, also key by (type, experiment_id):
running_by_exp = {(op.type, op.experiment_id): op for op in active}
```

Pass these to the template. Each button uses the key-of-interest:

```jinja
{% set sm = running_by_type.get("summarize") %}
{% if sm %}
  <a class="btn btn--secondary btn--running" href="{{ sm.log_url }}">
    <span class="running-dot"></span>
    Summarize running… view log
  </a>
{% else %}
  <button type="button" class="btn btn--secondary"
          @click="$dispatch('open-modal', { id: 'summarize' })">
    {{ action_label("Summarize", "project", has_summary) }}
  </button>
{% endif %}
```

Use the same pattern for finalize, evaluate, report, present, build-tool. For experiment-level (evaluate / report / present / run), the lookup key is `(type, exp_id)` not just type.

**Step 3: Add CSS for the running indicator**

In `app.css`:

```css
.btn--running {
  border: 1px solid var(--accent);
  color: var(--accent);
}
.running-dot {
  display: inline-block;
  width: 0.5em;
  height: 0.5em;
  margin-right: 0.4em;
  border-radius: 50%;
  background: var(--accent);
  animation: urika-pulse 1.4s ease-in-out infinite;
  vertical-align: middle;
}
@keyframes urika-pulse {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50%      { opacity: 1.0; transform: scale(1.2); }
}
```

**Step 4: Verify tests.**

**Step 5: Commit** — `feat(dashboard): buttons show running state and link to live log when an op is in flight`

---

## Phase B4 — Persistent "running ops" banner

### Task B4.1: Project-scoped banner

**Files:**
- Modify: `src/urika/dashboard/templates/_base.html` — banner slot inside the project content area, above the breadcrumb. NOT in the global sidebar — only relevant on project pages.
- Modify: `src/urika/dashboard/routers/pages.py` — every project-scoped view passes `active_ops` to the template context (do this via a small middleware-style helper or a context-builder function rather than copy-pasting).
- Modify: `src/urika/dashboard/static/app.css` — banner styling.
- Test: `tests/test_dashboard/test_active_ops_banner.py` (new) — covers visibility on multiple page routes.

**Step 1: Tests**

- On any project page, no active ops → banner not rendered.
- One live `.summarize.lock` → banner visible on /projects/<n>, /projects/<n>/experiments, /projects/<n>/methods etc, with one entry "Summarize running" linking to the log.
- Two live ops (e.g. one summarize + one experiment run) → both entries in the banner.
- On the log page itself, suppress the banner entry that points to THIS page (would be a no-op self-link). Other entries stay.

**Step 2: Implement**

Build a small helper in `pages.py`:

```python
def _project_template_context(name: str, summary) -> dict:
    """Common context every project-scoped page needs."""
    from urika.dashboard.active_ops import list_active_operations
    return {
        "active_ops": list_active_operations(name, summary.path),
    }
```

Then every project page does:

```python
ctx = {"request": request, "project": summary, ...}
ctx.update(_project_template_context(name, summary))
return templates.TemplateResponse("...", ctx)
```

In `_base.html`, between the breadcrumb and the page heading:

```jinja
{% if active_ops %}
  <div class="active-ops-banner">
    <span class="active-ops-label">Running:</span>
    {% for op in active_ops %}
      {% if request.url.path != op.log_url.split('?')[0] %}
        <a class="active-op-chip" href="{{ op.log_url }}">
          <span class="running-dot"></span>
          {{ op.type | replace('_', ' ') }}
          {% if op.experiment_id %} · {{ op.experiment_id }}{% endif %}
        </a>
      {% endif %}
    {% endfor %}
  </div>
{% endif %}
```

CSS:

```css
.active-ops-banner {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: var(--space-2) var(--space-4);
  background: color-mix(in srgb, var(--accent) 10%, var(--bg));
  border-bottom: 1px solid color-mix(in srgb, var(--accent) 30%, var(--border));
  font-size: var(--fs-sm);
}
.active-ops-label { color: var(--text-muted); }
.active-op-chip {
  display: inline-flex; align-items: center; gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
  background: var(--bg);
  border: 1px solid var(--accent);
  border-radius: 999px;
  color: var(--accent);
  text-decoration: none;
}
.active-op-chip:hover { background: color-mix(in srgb, var(--accent) 10%, var(--bg)); }
```

**Step 3: Tests pass.**

**Step 4: Commit** — `feat(dashboard): project-wide running-ops banner with one-click return to live log`

---

## Phase B5 — Shared thinking partial + completion CTAs on log pages

### Task B5.1: Shared thinking partial

**Files:**
- Create: `src/urika/dashboard/static/urika-thinking.js`
- Create: `src/urika/dashboard/templates/_thinking.html` (Jinja partial: a single `<div>` with id, plus `<script>` that calls `urikaThinking.start(el)` after page load)
- Modify: `src/urika/dashboard/templates/advisor_chat.html` — replace the inline 50 lines of spinner JS with `{% include "_thinking.html" %}`.
- Modify: every log page template (`run_log.html`, `summarize_log.html`, `finalize_log.html`, `tool_build_log.html`) — show the partial above the `<pre id="log">`. Hide it on the first SSE message arrival.
- Test: `tests/test_dashboard/test_thinking_partial.py` — render templates, assert the `<div data-urika-thinking>` element appears.

**Step 1: Write the JS**

```js
// urika-thinking.js — animated "thinking…" placeholder for any element
// with [data-urika-thinking]. See start/stop API.

const SPINNER_FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"];
const ACTIVITY_VERBS = [
  "Thinking", "Reasoning", "Analyzing", "Processing",
  "Exploring", "Evaluating", "Considering", "Reviewing",
];

const SPINNER_INTERVAL_MS = 200;          // 5 frames/sec — visible but not frantic
const VERB_MIN_FRAMES = 4;                // wait at least 4 spinner ticks
const VERB_MAX_FRAMES = 8;                // and at most 8 before changing
const VERB_JITTER_MS = 800;               // ± random ms on top

function urikaThinkingStart(el) {
  if (!el || el.dataset.urikaThinkingActive === "1") return null;
  el.dataset.urikaThinkingActive = "1";
  el.classList.add("urika-thinking");

  let spinnerIdx = 0;
  let verbIdx = Math.floor(Math.random() * ACTIVITY_VERBS.length);

  const render = () => {
    el.textContent = `${SPINNER_FRAMES[spinnerIdx]} ${ACTIVITY_VERBS[verbIdx]}…`;
  };
  render();

  const spin = setInterval(() => {
    spinnerIdx = (spinnerIdx + 1) % SPINNER_FRAMES.length;
    render();
  }, SPINNER_INTERVAL_MS);

  let verbTimer = null;
  const scheduleNextVerb = () => {
    const frames = VERB_MIN_FRAMES + Math.floor(
      Math.random() * (VERB_MAX_FRAMES - VERB_MIN_FRAMES + 1)
    );
    const jitter = (Math.random() * 2 - 1) * VERB_JITTER_MS;
    const ms = Math.max(400, frames * SPINNER_INTERVAL_MS + jitter);
    verbTimer = setTimeout(() => {
      verbIdx = (verbIdx + 1) % ACTIVITY_VERBS.length;
      render();
      scheduleNextVerb();
    }, ms);
  };
  scheduleNextVerb();

  return {
    stop() {
      clearInterval(spin);
      if (verbTimer) clearTimeout(verbTimer);
      el.classList.remove("urika-thinking");
      el.textContent = "";
      delete el.dataset.urikaThinkingActive;
    },
  };
}

window.urikaThinking = { start: urikaThinkingStart };
```

CSS:

```css
.urika-thinking {
  color: var(--accent);
  font-family: var(--font-mono, monospace);
  font-size: var(--fs-md);
}
```

**Step 2: Partial template `_thinking.html`**

```jinja
{# Usage: {% include "_thinking.html" with context %}
   Renders a single placeholder div + auto-starts the spinner on load.
   Caller can stop() it by storing the return value of urikaThinking.start. #}
<div data-urika-thinking class="urika-thinking"></div>
<script src="/static/urika-thinking.js"></script>
<script>
  (function () {
    const els = document.querySelectorAll('[data-urika-thinking]:not([data-started])');
    els.forEach(el => {
      el.dataset.started = "1";
      window._urikaThinkingHandle = window.urikaThinking.start(el);
    });
  })();
</script>
```

(The single `_urikaThinkingHandle` is per-page — log pages have one placeholder; advisor has many but recreates fresh each turn so the helper just returns a fresh handle each time.)

**Step 3: Wire into advisor + each log template**

`advisor_chat.html` — replace inline spinner code with `window.urikaThinking.start(thinkingEl)`. Keep the existing message-bubble structure.

`run_log.html`, `summarize_log.html`, `finalize_log.html`, `tool_build_log.html` — add the partial above `<pre id="log">`. In each template's existing inline `<script>`, on first SSE message arrival, call `window._urikaThinkingHandle?.stop()` to swap the placeholder out.

**Step 4: Tests + commit**

Commit: `feat(dashboard): shared animated thinking placeholder across advisor + log pages`

### Task B5.2: Completion CTAs on log pages

**Files:**
- Modify: `summarize_log.html` — on completion, show "View summary" button if `summary.md` exists.
- Modify: `finalize_log.html` — on completion, show "View report" / "View presentation" / "View findings" buttons (whichever artifacts now exist).
- Modify: `tool_build_log.html` — on completion, "Back to tools" link.
- Modify: `run_log.html` — already has report/presentation probe; keep as-is.
- Add API endpoint: `GET /api/projects/<n>/artifacts/projectbook` returning `{has_summary, has_report, has_presentation, has_findings}`.
- Test: extend `test_api_*` and `test_pages_*` for the artifact probe + the new buttons.

**Step 1-3: Implement the artifact probe + each template's completion handler.**

After `event: status` arrives, fetch the artifact endpoint, then unhide the relevant buttons.

**Step 4: Tests + commit**

Commit: `feat(dashboard): completion CTAs on summarize / finalize / build-tool log pages`

---

## Phase B6 — Smoke checklist + docs

### Task B6.1: Smoke checklist

Create `dev/plans/2026-04-27-running-ops-smoke.md` mirroring the Phase 13 smoke template. Manual checks:
- Click Summarize. Navigate away. Banner shows "summarize". Click chip → back to live stream.
- Project home button now reads "Summarize running… view log".
- Click again from any page → no duplicate spawn.
- Stream completes → "View summary" button appears under the log.
- Repeat for finalize, build-tool, evaluate, report, present, experiment run.
- Hard-kill the urika subprocess externally; reload the dashboard. The lock is now stale (PID dead), so the banner clears and buttons go back to normal.

### Task B6.2: Update `docs/19-dashboard.md`

Add a section "Running operations" describing the lock-file-as-truth model, the banner, the running-state buttons, and idempotency.

Commit: `docs: running operations + log streaming`

---

## Execution order

Phases are sequenced by dependency:

1. **B1** unblocks everything else.
2. **B2** depends on B1 (idempotent endpoints read from `list_active_operations`).
3. **B3** depends on B1 (button state reads from `list_active_operations`).
4. **B4** depends on B1 (banner reads from `list_active_operations`).
5. **B5** is independent (visuals on log pages; no logic dependency).
6. **B6** closes out.

B3, B4, B5 can each go in their own subagent batch sequentially. Don't try to parallelize within a phase — they all touch overlapping templates / CSS.

**Test counts:** Baseline at start = 2025 passing. Expected total adds:
- B1: ~10 tests
- B2: ~7 tests (one per spawn endpoint)
- B3: ~8 tests
- B4: ~5 tests
- B5: ~8 tests

Final expected: ~2063 passing.

NO `Co-Authored-By:` lines on any commit.
