# Dashboard Coverage & In-Browser Flows Implementation Plan (Phase 11)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Take the Phase 10-polished dashboard from "browseable" to "primary interface" — modal-driven New Project + New Experiment flows replace interactive CLI prompts; Advisor chat lives in the browser; mid-run agent questions are answered inline; project-level Privacy + Notifications are fully editable (inheriting global defaults); and coverage gaps for the remaining CLI commands (criteria, tools, knowledge add/remove, finalize trigger) are closed. Plus targeted visual polish.

**Architecture:** Continues the Phase 1–10 stack — FastAPI + Jinja + HTMX + Alpine via CDN, hand-written CSS. Two new primitives this phase: a `modal()` Jinja macro (used by both New Project and New Experiment) and an SSE message-class extension that distinguishes `event: prompt` from `event: status` so the live-log page can render an inline answer form when the orchestrator pauses for input. Project creation triggers `urika new --json --non-interactive` as a subprocess; the dashboard supplies the form values that the interactive CLI would otherwise prompt for.

**Tech Stack:** Same as Phase 10. New optional dep: none (uses existing CDN scripts).

**Estimated total:** ~22 tasks across 7 phases. Phase 11A (~0.5 day) — visual polish. Phase 11B (~0.5 day) — modal primitive + New Experiment. Phase 11C (~1.5 days) — New Project modal + builder subprocess. Phase 11D (~0.5 day) — project-level Privacy + Notifications full editing. Phase 11E (~1 day) — advisor chat + knowledge add + finalize button + tools page. Phase 11F (~1 day) — mid-run interactive prompts (SSE event extension + answer form). Phase 11G (~0.5 day) — docs + smoke.

---

## Coverage audit (informs scope)

| CLI command | Current dashboard surface | Phase 11 plan |
|---|---|---|
| `list` | `/projects` | ✅ done |
| `new` | none | **11C** — modal + builder subprocess |
| `run` | `/projects/<n>/run` | **11B** — replace with button + modal |
| `experiment` | `/projects/<n>/experiments` | ✅ done |
| `methods` | `/projects/<n>/methods` | ✅ done |
| `knowledge` (read) | `/projects/<n>/knowledge` | ✅ done |
| `knowledge add` | none | **11E.3** — add via form |
| `results` | experiment-detail runs table | ✅ done |
| `report` (per-experiment) | `/projects/<n>/experiments/<id>/report` | ✅ done |
| `present` | per-experiment + projectbook viewers | ✅ done |
| `finalize` | `POST /api/.../finalize` exists | **11E.2** — button on project home |
| `advisor` | `POST /api/.../advisor` exists | **11E.1** — chat panel UI |
| `config` | `/settings` + `/projects/<n>/settings` | mostly done; **11D** for project Privacy/Notifications |
| `notifications` | global tab + project view-only | **11D** — project full edit |
| `update` | project settings PUT | ✅ done |
| `criteria` | none | **11E.4** — viewer page (read-only) |
| `evaluate` | none | **deferred** — advanced agent invocation, not blocking |
| `inspect` | none | **deferred** — local data introspection, CLI-appropriate |
| `logs` | `/projects/<n>/experiments/<id>/log` | ✅ done |
| `plan` | none | **deferred** — agent invocation, not user-facing |
| `setup` | none | **CLI-only** (installation flow) |
| `status` | project home | ✅ done |
| `summarize` | none | **deferred** — narrative summary, can call advisor instead |
| `tools` | none | **11E.4** — read-only listing |
| `usage` | none | **deferred** — small surface, low priority |
| `venv` | none | **CLI-only** (installation flow) |
| `build-tool` | none | **deferred** — agent invocation, complex |
| `dashboard` | self | n/a |
| `tui` | n/a | CLI-only |

Deferred items get a one-paragraph explanation in `docs/19-dashboard.md` Phase 11G so it's clear they're CLI-only on purpose.

---

## Phase 11A — Visual polish

### Task 11A.1: Move theme toggle out of page header

**Files:**
- Modify: `src/urika/dashboard/templates/_base.html`
- Modify: `src/urika/dashboard/templates/_sidebar.html`
- Modify: `src/urika/dashboard/static/app.css`

**Step 1: Audit current placement**

Open `_base.html`. The theme toggle button sits inside `<header class="page-header">` next to the page title — so on every page it appears centered-ish at the top of the main content area, looking misplaced.

**Step 2: Move it**

Decision: place the toggle at the **bottom of the sidebar** as an unobtrusive ghost button. The sidebar is always visible; this keeps the page header clean for breadcrumb + heading only.

In `_sidebar.html`, append after the `</nav>`:

```html
<div class="sidebar-footer">
  <button
    class="btn btn--ghost theme-toggle"
    @click="document.dispatchEvent(new CustomEvent('urika:toggle-theme'))"
    aria-label="Toggle theme"
  >
    <span x-data x-text="document.documentElement.dataset.theme === 'dark' ? '☀ Light' : '☾ Dark'"></span>
  </button>
</div>
```

In `_base.html`, remove the theme-toggle button from the page header. Keep the body-level Alpine `x-data` that owns `theme` state; add a listener for the custom event:

```html
<body
  x-data="{ theme: localStorage.getItem('urika-theme') || 'dark' }"
  x-init="
    document.documentElement.dataset.theme = theme;
    document.addEventListener('urika:toggle-theme', () => {
      theme = theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('urika-theme', theme);
      document.documentElement.dataset.theme = theme;
    });
  "
  :data-theme="theme"
>
```

The custom-event approach decouples the toggle button from the body-level state.

In `app.css`, add:

```css
.sidebar-footer {
  margin-top: auto;
  padding: var(--space-3);
  border-top: 1px solid var(--border);
}
```

The sidebar already uses `display: flex; flex-direction: column` (verify in app.css; if not, add it). `margin-top: auto` pushes the footer to the bottom.

**Step 3: Test**

Add a test that the theme toggle is no longer in the page header but is in the sidebar:

```python
# tests/test_dashboard/test_visual_audit.py — append
def test_theme_toggle_lives_in_sidebar_not_header(client_with_projects):
    r = client_with_projects.get("/projects")
    body = r.text
    # The theme toggle button has the .theme-toggle class.
    # It must appear inside the <aside class="sidebar"> block, not
    # inside <header class="page-header">.
    import re
    sidebar_match = re.search(
        r'<aside class="sidebar"[^>]*>(.*?)</aside>', body, re.DOTALL
    )
    assert sidebar_match is not None
    assert 'theme-toggle' in sidebar_match.group(1)
    # And NOT in the page-header
    header_match = re.search(
        r'<header class="page-header"[^>]*>(.*?)</header>', body, re.DOTALL
    )
    if header_match:
        assert 'theme-toggle' not in header_match.group(1)
```

**Step 4: Commit**

```bash
git commit -m "feat(dashboard): theme toggle in sidebar footer

Page header is now clean (breadcrumb + title only); the theme
toggle moved to the sidebar bottom as an unobtrusive ghost
button. Decoupled via a custom 'urika:toggle-theme' event so the
toggle's exact placement is independent of the body-level theme
state."
```

---

### Task 11A.2: URIKA wordmark + sidebar link colors

**Files:**
- Modify: `src/urika/dashboard/templates/_sidebar.html`
- Modify: `src/urika/dashboard/static/app.css`

**Step 1: Audit current state**

The brand block at the top of the sidebar currently renders just `<span class="wordmark">Urika</span>` with whatever default size. The plan: bigger, centered, with a subtle blue underline matching the accent.

**Step 2: Update the brand**

In `_sidebar.html`:

```html
<a class="brand" href="/">
  <span class="wordmark">URIKA</span>
</a>
```

(Uppercase; keeps a tech-product feel and matches the CLI banner.)

In `app.css`:

```css
.brand {
  display: flex;
  justify-content: center;
  padding: var(--space-5) 0 var(--space-4);
  border-bottom: 1px solid var(--border);
  margin-bottom: var(--space-4);
}
.wordmark {
  font-size: var(--fs-xl);
  font-weight: var(--fw-semibold);
  letter-spacing: 0.04em;
  color: var(--accent);
}
.sidebar-link {
  color: var(--text-muted);
  text-decoration: none;
  padding: var(--space-2) var(--space-4);
  display: block;
  border-radius: 6px;
  transition: 150ms ease;
  font-size: var(--fs-sm);
}
.sidebar-link:hover {
  color: var(--text);
  background: var(--bg-hover);
}
.sidebar-link--active {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}
.sidebar-section-label {
  font-size: var(--fs-xs);
  font-weight: var(--fw-semibold);
  color: var(--text-subtle);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: var(--space-3) var(--space-4) var(--space-2);
}
```

(`color-mix` works in modern browsers; if the rest of the CSS uses it elsewhere — Phase 2.1 noted yes — keep using it.)

**Step 3: Mark the active sidebar link**

Add an Alpine-based active-state helper. In `_sidebar.html` wrap each link:

```html
<a class="sidebar-link"
   :class="{ 'sidebar-link--active': window.location.pathname === '/projects' }"
   href="/projects">Projects</a>
```

For project-mode links (Home, Experiments, etc.), use `startsWith`:

```html
<a class="sidebar-link"
   :class="{ 'sidebar-link--active': window.location.pathname.startsWith('/projects/{{ project.name }}/experiments') }"
   href="/projects/{{ project.name }}/experiments">Experiments</a>
```

The Home link should match exactly:

```html
:class="{ 'sidebar-link--active': window.location.pathname === '/projects/{{ project.name }}' }"
```

**Step 4: Test**

```python
# tests/test_dashboard/test_visual_audit.py — append
def test_sidebar_link_active_class_applied(client_with_projects):
    r = client_with_projects.get("/projects")
    body = r.text
    # The Projects link should have the active marker
    assert 'sidebar-link--active' in body or 'window.location.pathname === \'/projects\'' in body


def test_brand_uses_uppercase_urika(client_with_projects):
    r = client_with_projects.get("/projects")
    body = r.text
    assert "URIKA" in body
```

**Step 5: Commit**

```bash
git commit -m "feat(dashboard): URIKA wordmark + sidebar link styling

Brand: bigger, centered, accent-colored URIKA wordmark with a
border under it. Sidebar links: muted by default, accent on
hover and on active (matches the current URL). Section labels
get uppercase tracking. Subtle but the page now reads as
designed rather than as raw text."
```

---

### Task 11A.3: Secondary accent (success green)

**Files:**
- Modify: `src/urika/dashboard/static/app.css`

The primary accent stays blue (`--accent`). Currently `--success`, `--warn`, `--error` exist as standalone tokens. This task wires them into the `.tag--*` modifier set so status pills get color: completed → green, running → blue, paused → yellow, failed → red.

**Step 1: Audit `.tag--*` rules**

Open `app.css` and find the existing `.tag` block. The Phase 2.1 implementer used `color-mix` for the modifiers; verify they actually pick up the right tokens.

**Step 2: Make sure all status modifiers use semantic colors**

```css
.tag--running {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
}
.tag--completed {
  color: var(--success);
  background: color-mix(in srgb, var(--success) 12%, transparent);
}
.tag--pending {
  color: var(--text-muted);
  background: var(--bg-elevated);
}
.tag--paused {
  color: var(--warn);
  background: color-mix(in srgb, var(--warn) 12%, transparent);
}
.tag--failed {
  color: var(--error);
  background: color-mix(in srgb, var(--error) 12%, transparent);
}
```

**Step 3: Apply the modifier in templates**

In `experiments.html` and `experiment_detail.html`, the status tag currently renders as `<span class="tag tag--{{ status }}">{{ status }}</span>` — that already works as long as the status string matches one of {running, completed, pending, paused, failed}. Verify by reading the template.

If not, change `<span class="tag">` → `<span class="tag tag--{{ status_normalized }}">` where `status_normalized` is `status.lower()` (since orchestrator may write "Running" vs "running"). Add a Jinja filter:

```python
# src/urika/dashboard/filters.py — append
def tag_status(status: str | None) -> str:
    """Lowercase + sanitize status for use in CSS modifier classes."""
    if not status:
        return "pending"
    s = status.lower().strip()
    return s if s in {"running", "completed", "pending", "paused", "failed"} else "pending"
```

Wire into `create_app()`:
```python
app.state.templates.env.filters["tag_status"] = tag_status
```

Then in templates: `<span class="tag tag--{{ status | tag_status }}">{{ status }}</span>`.

**Step 4: Test**

```python
# tests/test_dashboard/test_filters.py — append
def test_tag_status_normalizes():
    from urika.dashboard.filters import tag_status
    assert tag_status("Running") == "running"
    assert tag_status("COMPLETED") == "completed"
    assert tag_status(None) == "pending"
    assert tag_status("nonsense") == "pending"
```

Plus an integration test:

```python
def test_experiments_list_status_uses_tag_modifier(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments")
    body = r.text
    # The completed experiment should get the green modifier
    assert 'tag--completed' in body
```

**Step 5: Commit**

```bash
git commit -m "feat(dashboard): semantic status pill colors

Status tags pick the right color from the design system:
green for completed, blue for running, yellow for paused, red
for failed, muted gray for pending. New tag_status Jinja filter
normalizes the input so 'Running'/'running'/'RUNNING' all map
to the same modifier class."
```

---

## Phase 11B — Modal primitive + New Experiment

### Task 11B.1: Modal primitive

**Files:**
- Modify: `src/urika/dashboard/templates/_macros.html`
- Modify: `src/urika/dashboard/static/app.css`

**Step 1: Add the modal macro**

Append to `_macros.html`:

```html
{% macro modal(id, title) %}
{# Usage:
   {% call modal('new-experiment', 'New experiment') %}
     <form ...>...</form>
   {% endcall %}
   Trigger with: <button @click="$dispatch('open-modal', { id: 'new-experiment' })">Open</button>
#}
<div
  x-data="{ open: false }"
  x-init="
    window.addEventListener('open-modal', e => { if (e.detail && e.detail.id === '{{ id }}') open = true });
    window.addEventListener('close-modal', e => { if (!e.detail || e.detail.id === '{{ id }}') open = false });
  "
  x-show="open"
  x-cloak
  class="modal-backdrop"
  @click.self="open = false"
  @keydown.escape.window="open = false"
  role="dialog"
  aria-modal="true"
>
  <div class="modal-panel">
    <header class="modal-header">
      <h2 class="modal-title">{{ title }}</h2>
      <button class="btn btn--ghost modal-close" @click="open = false" aria-label="Close">×</button>
    </header>
    <div class="modal-body">
      {{ caller() }}
    </div>
  </div>
</div>
{% endmacro %}
```

**Step 2: CSS**

```css
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, .5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal-panel {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  width: min(560px, 90vw);
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0, 0, 0, .35);
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border);
}
.modal-title { font-size: var(--fs-lg); font-weight: var(--fw-semibold); }
.modal-close { font-size: 1.4em; }
.modal-body { padding: var(--space-5); }
```

**Step 3: Smoke test**

```python
# tests/test_dashboard/test_macros.py — append
def test_modal_macro_renders(tmp_path):
    from jinja2 import Environment, FileSystemLoader
    from pathlib import Path
    env = Environment(loader=FileSystemLoader("src/urika/dashboard/templates"))
    src = (
        '{% from "_macros.html" import modal %}'
        '{% call modal("test-modal", "Test") %}'
        '<p>body content</p>'
        '{% endcall %}'
    )
    out = env.from_string(src).render()
    assert "modal-backdrop" in out
    assert "modal-title" in out
    assert ">Test</h2>" in out
    assert "body content" in out
```

**Step 4: Commit**

```bash
git commit -m "feat(dashboard): modal primitive

_macros.modal(id, title) renders an Alpine-controlled overlay
opened by 'open-modal' / closed by 'close-modal' custom events
or click-outside / Escape. Used by the next two tasks (New
Experiment, New Project) and any future flow that needs a
focused form rather than a dedicated page."
```

---

### Task 11B.2: New Experiment button + modal

**Files:**
- Modify: `src/urika/dashboard/templates/experiments.html`
- Modify: `src/urika/dashboard/routers/api.py` — extend POST /api/projects/{name}/run to redirect via HTMX header on success

**Step 1: Add the button + modal to experiments.html**

Replace the page-header area to include a top-right action button:

```html
{% block heading %}Experiments{% endblock %}

{% block content %}
<div class="page-actions">
  <button
    class="btn btn--primary"
    @click="$dispatch('open-modal', { id: 'new-experiment' })"
  >+ New experiment</button>
</div>

{# ... existing list/empty-state ... #}

{% from "_macros.html" import modal %}
{% call modal('new-experiment', 'New experiment') %}
  <form
    hx-post="/api/projects/{{ project.name }}/run"
    hx-headers='{"X-Modal-Id": "new-experiment"}'
    hx-target="#new-experiment-feedback"
    hx-swap="innerHTML"
  >
    {# Same fields as the old run.html form #}
    <div class="form-row">
      <label for="ne-name">Experiment name</label>
      <input id="ne-name" name="name" type="text" required>
    </div>
    <div class="form-row">
      <label for="ne-hypothesis">Hypothesis</label>
      <textarea id="ne-hypothesis" name="hypothesis" rows="3" required></textarea>
    </div>
    <div class="form-row form-row--inline">
      <label for="ne-mode">Mode</label>
      <select id="ne-mode" name="mode">
        {% for m in valid_modes %}
          <option value="{{ m }}" {% if m == project.mode %}selected{% endif %}>{{ m }}</option>
        {% endfor %}
      </select>
      <label for="ne-audience">Audience</label>
      <select id="ne-audience" name="audience">
        {% for a in valid_audiences %}
          <option value="{{ a }}" {% if a == project.audience %}selected{% endif %}>{{ a }}</option>
        {% endfor %}
      </select>
      <label for="ne-max-turns">Max turns</label>
      <input id="ne-max-turns" name="max_turns" type="number" min="1" value="10">
    </div>
    <div class="form-row">
      <label for="ne-instructions">Additional instructions (optional)</label>
      <textarea id="ne-instructions" name="instructions" rows="2"></textarea>
    </div>
    <div class="form-actions">
      <button type="button" class="btn btn--ghost" @click="$dispatch('close-modal')">Cancel</button>
      <button type="submit" class="btn btn--primary">Start experiment</button>
      <span id="new-experiment-feedback" class="text-muted"></span>
    </div>
  </form>
{% endcall %}
{% endblock %}
```

The route still needs `valid_modes` and `valid_audiences` — extend `project_experiments` route to load them.

**Step 2: HTMX redirect to live log on success**

The existing `POST /api/projects/{name}/run` returns either JSON or an HTML fragment. For the modal flow we want the browser to navigate to the live log on success.

HTMX supports the `HX-Redirect` response header: when present, HTMX navigates the whole page. Update the run endpoint:

```python
# in routers/api.py — api_project_run_post
# After successfully spawning:
hx_request = request.headers.get("hx-request") == "true"
if hx_request:
    log_url = f"/projects/{name}/experiments/{exp.experiment_id}/log"
    return Response(status_code=200, headers={"HX-Redirect": log_url})
# ... existing JSON / fragment branches ...
```

**Step 3: Decommission /projects/<n>/run**

The old standalone /run page is now unreachable from the UI. Two options:
- **Delete the route** (and its template + test).
- **Redirect** to /experiments (with the modal opened automatically via a query param like `?new=1` that the page reads with Alpine).

Pick **redirect**: keeps the URL working for anyone who bookmarked it. In `routers/pages.py`:

```python
@router.get("/projects/{name}/run")
def project_run_redirect(name: str) -> RedirectResponse:
    return RedirectResponse(url=f"/projects/{name}/experiments?new=1", status_code=307)
```

Delete `templates/run.html`. The existing `project_run` route logic (active-experiment detection) is no longer needed because the experiments list already shows a "Live log" link for any experiment with a `.lock` file (or extend the experiments list to do so if it doesn't).

In `experiments.html`, read the `?new=1` query param via Alpine and auto-open the modal:

```html
<div x-init="if (new URLSearchParams(window.location.search).get('new') === '1') $dispatch('open-modal', { id: 'new-experiment' })"></div>
```

**Step 4: Tests**

Update the existing `/run` page tests to assert the redirect, and add tests that the experiments page renders the modal:

```python
def test_run_page_redirects_to_experiments_with_new_flag(client_with_projects):
    r = client_with_projects.get("/projects/alpha/run", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/projects/alpha/experiments?new=1"


def test_experiments_page_includes_new_experiment_modal(client_with_projects):
    r = client_with_projects.get("/projects/alpha/experiments")
    body = r.text
    assert "+ New experiment" in body
    assert "modal-backdrop" in body  # modal rendered (closed by default)
    assert 'name="hypothesis"' in body  # form field
```

For the HX-Redirect behavior, test the API:

```python
def test_run_post_returns_hx_redirect_when_htmx_request(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        headers={"hx-request": "true"},
        data={
            "name": "test", "hypothesis": "h",
            "mode": "exploratory", "audience": "expert",
            "max_turns": "5", "instructions": "",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect", "").startswith("/projects/alpha/experiments/")
    assert r.headers["hx-redirect"].endswith("/log")
```

**Step 5: Commit**

```bash
git commit -m "feat(dashboard): + New experiment button + modal

The /run page is replaced by a '+ New experiment' button on the
experiments list that opens a modal with the same fields. Submit
posts via HTMX; on success the API returns HX-Redirect so the
whole page navigates to the live log. The old /run URL redirects
to /experiments?new=1 (auto-opens the modal) for back-compat."
```

---

### Task 11B.3: Auto-redirect after start

(Folded into 11B.2. No separate task needed.)

---

## Phase 11C — New Project modal + builder subprocess

### Task 11C.1: + New project button + modal

**Files:**
- Modify: `src/urika/dashboard/templates/projects_list.html`

Top-right action button on `/projects`:

```html
<div class="page-actions">
  <button
    class="btn btn--primary"
    @click="$dispatch('open-modal', { id: 'new-project' })"
  >+ New project</button>
</div>

{% from "_macros.html" import modal %}
{% call modal('new-project', 'New project') %}
  <form
    hx-post="/api/projects"
    hx-target="#new-project-feedback"
    hx-swap="innerHTML"
  >
    <div class="form-row">
      <label for="np-name">Project name</label>
      <input id="np-name" name="name" type="text" pattern="[a-z0-9-]+" required
             placeholder="e.g. dht-target-selection">
    </div>
    <div class="form-row">
      <label for="np-question">Research question</label>
      <textarea id="np-question" name="question" rows="2" required></textarea>
    </div>
    <div class="form-row">
      <label for="np-description">Description (optional)</label>
      <textarea id="np-description" name="description" rows="2"></textarea>
    </div>
    <div class="form-row">
      <label for="np-data-paths">Data path(s) (one per line)</label>
      <textarea id="np-data-paths" name="data_paths" rows="3"
                placeholder="/path/to/data.csv"></textarea>
    </div>
    <div class="form-row form-row--inline">
      <label for="np-mode">Mode</label>
      <select id="np-mode" name="mode">
        {% for m in valid_modes %}
          <option value="{{ m }}">{{ m }}</option>
        {% endfor %}
      </select>
      <label for="np-audience">Audience</label>
      <select id="np-audience" name="audience">
        {% for a in valid_audiences %}
          <option value="{{ a }}">{{ a }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="form-actions">
      <button type="button" class="btn btn--ghost" @click="$dispatch('close-modal')">Cancel</button>
      <button type="submit" class="btn btn--primary">Create project</button>
      <span id="new-project-feedback" class="text-muted"></span>
    </div>
  </form>
{% endcall %}
```

The `pattern="[a-z0-9-]+"` enforces the slug-y names used by the registry. Provide context to the projects route so `valid_modes` / `valid_audiences` are available. Add tests for the page.

**Commit:**

```bash
git commit -m "feat(dashboard): + New project button + modal on /projects"
```

---

### Task 11C.2: POST /api/projects (creates project workspace)

**Files:**
- Modify: `src/urika/dashboard/routers/api.py`
- Modify: `src/urika/dashboard/runs.py` — add `spawn_project_builder` helper

**The hard problem:** `urika new` is interactive. It scans data, prompts for hypotheses, asks the user to pick experiment templates. The dashboard supplies the form values up-front; the builder agent then continues from "examined the data → suggesting next experiments" without re-asking the questions the user already answered.

**Approach for this phase:**

1. POST /api/projects creates a MINIMAL project workspace synchronously (`urika.core.workspace.create_project_workspace` + register in `ProjectRegistry`).
2. Then spawn `urika new --json --headless --name <n> --question <q> ...` as a subprocess. **A `--headless` flag is new.** It tells the CLI to skip all interactive prompts and just run the builder agent with the supplied values.
3. Return `HX-Redirect: /projects/<n>` (no live log yet for project creation — the workspace is set up synchronously and the builder agent runs in the background).

**Step 1: Add `--headless` to `urika new`**

In `src/urika/cli/project_new.py`, add a `--headless` Click option. When set:
- All `interactive_prompt` / `interactive_confirm` / `interactive_numbered` calls return their default value.
- All `click.echo` output still works (writes to stdout).
- The "What experiments would you like to run?" prompt is skipped — builder just records its suggestions and exits without invoking the orchestrator.

This is a non-trivial change to the `new` command. Read it first; if the interactive points are too entangled, the alternative is: build the workspace directly from the dashboard side (call `create_project_workspace` + `ProjectRegistry.register`) and skip the builder agent entirely for now.

**Pragmatic choice for this task: skip the builder agent.** The dashboard creates the workspace + registers; future Phase 12 can wire up the builder for hypothesis suggestions / data scanning.

**Step 2: Implementation**

```python
# routers/api.py
@router.post("/projects")
async def api_create_project(request: Request):
    body = await request.form()
    name = (body.get("name") or "").strip()
    question = (body.get("question") or "").strip()
    description = (body.get("description") or "").strip()
    mode = (body.get("mode") or "exploratory").strip()
    audience = (body.get("audience") or "expert").strip()
    data_paths_raw = (body.get("data_paths") or "").strip()

    if not name or not question:
        raise HTTPException(status_code=422, detail="name and question are required")
    if not re.match(r"^[a-z0-9-]+$", name):
        raise HTTPException(status_code=422, detail="name must be lowercase alphanumeric + hyphens")
    if mode not in VALID_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {sorted(VALID_MODES)}")
    if audience not in VALID_AUDIENCES:
        raise HTTPException(status_code=422, detail=f"audience must be one of {sorted(VALID_AUDIENCES)}")

    # Conflict check
    registry = ProjectRegistry()
    if name in registry.list_all():
        raise HTTPException(status_code=409, detail=f"Project '{name}' already exists")

    data_paths = [p.strip() for p in data_paths_raw.splitlines() if p.strip()]

    # Decide where the new project lives. Use the configured projects root,
    # or fall back to ~/urika-projects/.
    from urika.core.settings import load_settings
    settings = load_settings()
    projects_root = Path(
        settings.get("projects_root", str(Path.home() / "urika-projects"))
    ).expanduser()
    projects_root.mkdir(parents=True, exist_ok=True)
    project_dir = projects_root / name

    if project_dir.exists():
        raise HTTPException(status_code=409, detail="Directory already exists on disk")

    # Build the ProjectConfig
    from urika.core.models import ProjectConfig
    cfg = ProjectConfig(
        name=name,
        question=question,
        mode=mode,
        description=description,
        data_paths=data_paths,
        audience=audience,
    )

    from urika.core.workspace import create_project_workspace
    create_project_workspace(project_dir, cfg)
    registry.register(name, project_dir)

    if request.headers.get("hx-request") == "true":
        return Response(status_code=201, headers={"HX-Redirect": f"/projects/{name}"})
    return JSONResponse({"name": name, "path": str(project_dir)}, status_code=201)
```

Verify the `ProjectRegistry.register(name, path)` API exists; if it's `add(name, path)` or similar, adjust.

**Step 3: Tests**

```python
# tests/test_dashboard/test_api_create_project.py
import re
import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from urika.dashboard.app import create_app


@pytest.fixture
def create_client(tmp_path: Path, monkeypatch) -> TestClient:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    # Force projects_root via settings.toml
    (home / "settings.toml").write_text(
        f'projects_root = "{tmp_path / "projects"}"\n'
    )
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_create_project_writes_workspace_and_registers(create_client, tmp_path):
    r = create_client.post(
        "/api/projects",
        data={
            "name": "test-proj",
            "question": "Does X cause Y?",
            "description": "A test project",
            "mode": "exploratory",
            "audience": "expert",
            "data_paths": "",
        },
    )
    assert r.status_code == 201
    proj_dir = tmp_path / "projects" / "test-proj"
    assert proj_dir.exists()
    assert (proj_dir / "urika.toml").exists()
    # Registered
    import json
    registry = json.loads((tmp_path / "home" / "projects.json").read_text())
    assert registry["test-proj"] == str(proj_dir)


def test_create_project_returns_hx_redirect_when_htmx(create_client):
    r = create_client.post(
        "/api/projects",
        headers={"hx-request": "true"},
        data={
            "name": "p2", "question": "Q?", "description": "",
            "mode": "exploratory", "audience": "expert", "data_paths": "",
        },
    )
    assert r.status_code == 201
    assert r.headers["hx-redirect"] == "/projects/p2"


def test_create_project_rejects_duplicate_name(create_client, tmp_path):
    (tmp_path / "projects" / "dup").mkdir(parents=True)
    create_client.post(
        "/api/projects",
        data={
            "name": "dup", "question": "Q?", "description": "",
            "mode": "exploratory", "audience": "expert", "data_paths": "",
        },
    )
    # Second creation should 409
    r = create_client.post(
        "/api/projects",
        data={
            "name": "dup", "question": "Q?", "description": "",
            "mode": "exploratory", "audience": "expert", "data_paths": "",
        },
    )
    assert r.status_code == 409


def test_create_project_validates_name_format(create_client):
    r = create_client.post(
        "/api/projects",
        data={
            "name": "Has Spaces", "question": "Q?", "description": "",
            "mode": "exploratory", "audience": "expert", "data_paths": "",
        },
    )
    assert r.status_code == 422


def test_create_project_parses_data_paths(create_client, tmp_path):
    r = create_client.post(
        "/api/projects",
        data={
            "name": "with-data", "question": "Q?", "description": "",
            "mode": "exploratory", "audience": "expert",
            "data_paths": "/path/one\n/path/two\n",
        },
    )
    assert r.status_code == 201
    import tomllib
    cfg = tomllib.loads(
        (tmp_path / "projects" / "with-data" / "urika.toml").read_text()
    )
    assert cfg["project"]["data_paths"] == ["/path/one", "/path/two"]
```

**Step 4: Commit**

```bash
git commit -m "feat(dashboard): POST /api/projects — create new project

Materializes a project workspace synchronously: builds the
ProjectConfig from the form, calls create_project_workspace,
registers in the project registry. Validates name format / mode /
audience; 409 on duplicate. Builder agent invocation is deferred
to a future phase — for now the user goes straight to the
project home and runs experiments from there."
```

---

### Task 11C.3: Redirect after create

(Folded into 11C.2 — `HX-Redirect: /projects/<n>` already done.)

---

### Task 11C.4: (Deferred to Phase 12) Builder agent flow

Skip for now. Add a TODO doc in `dev/plans/` noting the builder integration is future work.

---

## Phase 11D — Project Privacy + Notifications full editing

### Task 11D.1: Project Privacy tab — fully editable with inheritance

**Files:**
- Modify: `src/urika/dashboard/routers/pages.py` (extend `project_settings` to load global privacy as inherit-from)
- Modify: `src/urika/dashboard/templates/project_settings.html` (Privacy tab)
- Modify: `src/urika/dashboard/routers/api.py` (PUT handler accepts privacy fields)

**Schema:** project's `[privacy]` section overrides global's. If absent, project inherits global. The UI shows a "Use global default" checkbox per field; unchecking reveals the override input.

Simpler initial pass: a single radio button group "Privacy mode for this project" with options:
- Inherit from global (current global mode shown, e.g. "Inherit from global (private)")
- Open
- Private
- Hybrid

When non-inherit selected, render the same per-mode fields as the global tab.

**Implementation:** ~mirror the global Privacy tab's fields under a project-scoped namespace (`project_privacy_*`) with an "inherit" sentinel. PUT handler writes to `[privacy]` in `urika.toml` only when non-inherit is selected; clears the section when "Inherit" is picked.

Tests: 6+ tests around the inheritance / override behavior.

Commit: `feat(dashboard): project Privacy tab — fully editable with inherit`

---

### Task 11D.2: Project Notifications tab — fully editable with inheritance

**Files:**
- Modify: `src/urika/dashboard/templates/project_settings.html` (Notifications tab)
- Modify: `src/urika/dashboard/routers/api.py`

Same pattern as 11D.1. Project `[notifications]` section overrides global. Per-channel: enable / inherit / disable; per-channel config (extra_to, override_chat_id) editable per project.

The existing project Notifications tab already has channels checkbox + extra_to + override_chat_id — extend with the inherit-vs-override semantics.

Commit: `feat(dashboard): project Notifications tab — full editing with inherit`

---

## Phase 11E — Coverage gaps + advisor chat

### Task 11E.1: Advisor chat panel

**Files:**
- Modify: `src/urika/dashboard/routers/pages.py` — add `/projects/<n>/advisor` page
- Create: `src/urika/dashboard/templates/advisor_chat.html`

The endpoint `POST /api/projects/<n>/advisor` already exists (Phase 7.2). Build the conversation surface:

- A scrollable transcript showing past Q→A (loaded from `projectbook/advisor-history.json`).
- An input at the bottom for the next question.
- Submit posts to the existing endpoint, appends the response to the transcript.

The conversation history is persisted in `projectbook/advisor-history.json` (Phase 7.2 implementer used this). Read it on page load for the transcript.

Inline JS uses `fetch()` to POST and rerender — simpler than HTMX for this case.

```python
@router.get("/projects/{name}/advisor", response_class=HTMLResponse)
def project_advisor(name: str, request: Request) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    history_path = summary.path / "projectbook" / "advisor-history.json"
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return request.app.state.templates.TemplateResponse(
        "advisor_chat.html",
        {"request": request, "project": summary, "history": history},
    )
```

Add a sidebar link to the chat page (under the project section).

Tests: page renders, history shows up, etc.

Commit: `feat(dashboard): advisor chat panel`

---

### Task 11E.2: Finalize button on project home

**Files:**
- Modify: `src/urika/dashboard/templates/project_home.html`

A "Finalize project" button on the project home that triggers `POST /api/projects/<n>/finalize`. On success, the page polls `projectbook/.finalize.lock` to know when finalize completes, then refreshes to show the new Final Outputs cards.

Or: redirect to the existing `/api/projects/<n>/finalize/stream` SSE log surface (live log for finalize).

Use the latter — there's already a finalize SSE endpoint. Add a `/projects/<n>/finalize/log` page mirroring `run_log.html` but pointing at the finalize stream.

Tests: button renders, log page renders, etc.

Commit: `feat(dashboard): project home — Finalize button + log page`

---

### Task 11E.3: Knowledge add via form

**Files:**
- Modify: `src/urika/dashboard/templates/knowledge.html` — add an "+ Add" form
- Modify: `src/urika/dashboard/routers/api.py` — POST /api/projects/<n>/knowledge

```python
@router.post("/projects/{name}/knowledge")
async def api_knowledge_add(name: str, request: Request):
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    body = await request.form()
    source = (body.get("source") or "").strip()
    if not source:
        raise HTTPException(status_code=422, detail="source is required")
    from urika.knowledge.store import KnowledgeStore
    store = KnowledgeStore(summary.path)
    try:
        entry = store.ingest(source)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}")
    if request.headers.get("hx-request") == "true":
        return Response(status_code=201, headers={"HX-Redirect": f"/projects/{name}/knowledge"})
    return JSONResponse({"id": entry.id, "title": entry.title}, status_code=201)
```

The knowledge.html form takes one input (URL or local file path).

Commit: `feat(dashboard): + Add knowledge form on knowledge page`

---

### Task 11E.4: Tools listing + criteria viewer pages

**Files:**
- Create: `src/urika/dashboard/templates/tools.html`
- Create: `src/urika/dashboard/templates/criteria.html`
- Modify: `src/urika/dashboard/routers/pages.py`

**Tools** — read-only listing of `urika.tools.registry` content (built-in + project-specific). One row per tool: name + description + category.

**Criteria** — show the project's success criteria from `[project].success_criteria` in urika.toml (already editable in project settings, but a dedicated viewer page is useful for visibility).

Both routes 404 if project unknown. Add sidebar links for both.

Commit: `feat(dashboard): tools + criteria read-only pages`

---

## Phase 11F — Mid-run interactive prompts

### Task 11F.1: SSE event extension for prompts

**Files:**
- Modify: `src/urika/orchestrator/run_log.py` (or a new helper)
- Modify: `src/urika/dashboard/routers/api.py` (SSE stream parses prompt events)
- Modify: `src/urika/dashboard/templates/run_log.html` (renders prompt form)

**The protocol:** the orchestrator writes a recognizable line to `run.log` whenever it pauses for input. Format:

```
URIKA-PROMPT: {"prompt_id": "p-001", "question": "Which baseline method should we start with?", "type": "text"}
```

The SSE stream consumer in routers/api.py recognizes this prefix, emits an `event: prompt` SSE event with the JSON payload as the data line. The browser's EventSource listens for the `prompt` event and renders an inline form. User submits the answer via POST `/api/projects/<n>/runs/<exp_id>/respond` (Task 11F.2). The orchestrator polls a corresponding answer file (`<exp>/.prompts/p-001.answer`) to read the response.

This task implements the SSE side: emit `event: prompt` when the orchestrator log line starts with `URIKA-PROMPT:`. The orchestrator-side `URIKA-PROMPT:` emission is a separate change in `src/urika/orchestrator/`.

**Deferring orchestrator-side changes:** the orchestrator integration is non-trivial (every interactive prompt site in the agent system would need to be updated to use a new "prompt-via-file" mechanism). For this task, build the SSE side + the answer endpoint + a smoke test that fabricates a `URIKA-PROMPT:` line in run.log and verifies the SSE stream emits the right event.

Tests: 3+ tests around the prompt detection.

Commit: `feat(dashboard): SSE prompt events + browser inline answer form`

---

### Task 11F.2: POST /api/projects/<n>/runs/<exp_id>/respond

**Files:**
- Modify: `src/urika/dashboard/routers/api.py`

```python
@router.post("/projects/{name}/runs/{exp_id}/respond")
async def api_run_respond(name: str, exp_id: str, request: Request):
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    body = await request.form()
    prompt_id = (body.get("prompt_id") or "").strip()
    answer = (body.get("answer") or "").strip()
    if not prompt_id:
        raise HTTPException(status_code=422, detail="prompt_id is required")
    # Path traversal protection
    if "/" in prompt_id or ".." in prompt_id:
        raise HTTPException(status_code=400, detail="Invalid prompt_id")
    answers_dir = summary.path / "experiments" / exp_id / ".prompts"
    answers_dir.mkdir(parents=True, exist_ok=True)
    (answers_dir / f"{prompt_id}.answer").write_text(answer, encoding="utf-8")
    return {"status": "answer_recorded", "prompt_id": prompt_id}
```

Tests + commit.

---

## Phase 11G — Docs + smoke

### Task 11G.1: Update docs/19-dashboard.md

Add sections covering:
- New Experiment / New Project modals (replaces /run page).
- Advisor chat surface.
- Finalize button + log page.
- Knowledge add form.
- Tools + criteria pages.
- Mid-run interactive prompts (when orchestrator support lands).
- Coverage map: which CLI commands have dashboard surfaces and which are CLI-only on purpose.

Commit: `docs(dashboard): coverage + flows additions`

---

### Task 11G.2: Final smoke checklist

Create `dev/plans/2026-04-26-dashboard-coverage-flows-smoke.md` with the manual checklist:

- [ ] `+ New project` button on /projects → modal opens → submit creates a project → redirect to project home.
- [ ] `+ New experiment` button on /experiments → modal opens → submit starts run → redirect to live log → log streams.
- [ ] Theme toggle: now in sidebar bottom (not page header). Click → swap. Reload → preserved.
- [ ] URIKA wordmark: bigger, centered in sidebar, accent-colored.
- [ ] Sidebar links: muted by default, accent on hover, accent + tinted bg when on the matching page.
- [ ] Status pills: completed=green, running=blue, paused=yellow, failed=red, pending=gray.
- [ ] Project settings → Privacy: pick "Override global", set mode=private, save → urika.toml has `[privacy]` block. Re-load page → values persist.
- [ ] Project settings → Notifications: same pattern.
- [ ] Advisor chat: type a question, hit Send → answer appears in transcript. History persists across reloads.
- [ ] Project home: "Finalize project" button → kicks off finalize, redirects to finalize log page.
- [ ] Knowledge page: "+ Add" form → enter a path/URL → ingested entry shows up.
- [ ] Tools + Criteria pages: render from existing data.
- [ ] (When orchestrator-side prompt support lands) live log: when run pauses for input, an inline form appears; submitting the answer continues the run.

Plus automated state.

Commit: `docs(plan): coverage + flows smoke results`

---

## Execution notes

- **Commit per task** — ~22 commits.
- **TDD throughout** — every code task has at least one failing test first.
- **Skills to invoke during execution:**
  - @superpowers:test-driven-development on every code task
  - @superpowers:verification-before-completion before marking complete
- **Stop conditions:**
  - If Task 11C.2 (POST /api/projects) hits unexpected complexity around `create_project_workspace` semantics — STOP, ship just the validation-and-form-submit path with a "TODO: workspace creation deferred" placeholder, and treat workspace creation as its own follow-up.
  - If Task 11F.1 (SSE prompt events) hits ambiguity about the orchestrator-side protocol — STOP, ship just the SSE consumer + answer endpoint with a fabricated-log-line smoke test, and document that orchestrator integration is Phase 12 work.
- **Deferred from this plan (intentional):**
  - Builder agent integration in /api/projects (Task 11C.4 placeholder; Phase 12).
  - Orchestrator-side `URIKA-PROMPT:` emission (Task 11F.1 placeholder; Phase 12).
  - Build-tool, evaluate, plan, summarize, inspect, usage CLI surfaces (deferred — agent-internal or CLI-appropriate).
  - WebSocket upgrade (still Phase 12 candidate; SSE handles current scope).
  - Cookie/query-param auth fallback (Phase 9.3 left bearer-only; user hasn't requested this).
