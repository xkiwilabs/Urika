# Dashboard Polish & Completeness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Take the Phase 1–9 dashboard from "wireframe with all routes" to "polished, complete UI" — apply the design system that exists, surface every artifact (reports, presentations, findings, raw artifacts), expand both settings pages to cover what the CLI exposes, bifurcate the sidebar into global vs project mode, and stop showing raw JSON to end users.

**Architecture:** No new infrastructure — every change is in the existing `src/urika/dashboard/` package. New routes added: artifact viewers (`/projects/<n>/experiments/<id>/report`, `/.../presentation`, `/projects/<n>/projectbook/<file>`) and a small markdown-render helper (uses `markdown` library if present, falls back to `<pre>` if not). Settings pages move to a tabbed layout via Alpine `x-show`. JSON-shaped data (findings, methods metrics, progress runs) gets formatted templates instead of raw dump.

**Tech Stack:** Same as Phase 1–9 — FastAPI, Jinja2, HTMX, Alpine via CDN, hand-written CSS. New optional dep: `markdown>=3.5` (fallback if absent).

**Replaces nothing.** This is incremental polish on top of Phase 1–9.

**Estimated total:** ~24 tasks across 7 phases. Phase 10A (~0.5 day) — sidebar + visual audit. Phase 10B (~1.5 days) — artifact viewers + experiment detail rework. Phase 10C (~1 day) — settings completeness. Phase 10D (~0.5 day) — JSON-as-formatted-views audit. Phase 10E (~0.5 day) — project home final-outputs surface. Phase 10F (~0.5 day) — docs + smoke.

---

## Design principle for this phase

Every browser-rendered page must:
1. Show the design system (accent color visible, dark mode swap works, hover states, real button styling).
2. Hide raw JSON. JSON-shaped data is rendered as tables, key-value lists, or pretty-printed-but-syntax-highlighted blocks with field labels.
3. Never link to `/api/*` from a page — those are for agents/scripts.
4. Have a finished feel: no inert placeholder buttons, no orphan "view X" links pointing at routes that 404.

---

## Phase 10A — Visual & navigation polish

### Task 10A.1: Sidebar bifurcation — global mode vs project mode

**Files:**
- Modify: `src/urika/dashboard/templates/_sidebar.html`
- Test: `tests/test_dashboard/test_sidebar.py` (new)

**Step 1: Failing tests**

```python
# tests/test_dashboard/test_sidebar.py
"""Sidebar shows global links OR project links — never both."""

def test_sidebar_on_projects_list_shows_global_links_only(client_with_projects):
    r = client_with_projects.get("/projects")
    body = r.text
    assert 'href="/projects"' in body
    assert 'href="/settings"' in body
    # No project nav since we're not inside a project
    assert "← Back to projects" not in body


def test_sidebar_on_project_home_shows_project_links_and_back_button(client_with_projects):
    r = client_with_projects.get("/projects/alpha")
    body = r.text
    assert "← Back to projects" in body
    assert 'href="/projects"' in body  # the back link
    # Project-scoped links present
    assert "/projects/alpha/experiments" in body
    assert "/projects/alpha/methods" in body
    # Global Settings link absent — project Settings link present instead
    # Count occurrences carefully: "/settings" appears exactly once for the
    # project-scoped settings link.
    assert body.count('href="/settings"') == 0
    assert "/projects/alpha/settings" in body


def test_sidebar_on_global_settings_shows_global_links_only(settings_client):
    r = settings_client.get("/settings")
    body = r.text
    assert 'href="/projects"' in body
    assert "← Back to projects" not in body
```

(`settings_client` fixture is already in `tests/test_dashboard/test_global_settings.py` — move it to `tests/test_dashboard/conftest.py` first if a second test file needs it.)

**Step 2: Run tests — confirm fail**

Run: `pytest tests/test_dashboard/test_sidebar.py -v`
Expected: 3 failures (current sidebar shows both global + project links inside a project; no back button).

**Step 3: Rewrite `_sidebar.html`**

Replace the entire file:

```html
<aside class="sidebar" x-data="{ open: true }" :aria-expanded="open">
  <a class="brand" href="/">
    <span class="wordmark">Urika</span>
  </a>
  <nav class="sidebar-nav">
    {% if project %}
      <a class="sidebar-link sidebar-link--back" href="/projects">← Back to projects</a>
      <div class="sidebar-section">
        <div class="sidebar-section-label">{{ project.name }}</div>
        <a class="sidebar-link" href="/projects/{{ project.name }}">Home</a>
        <a class="sidebar-link" href="/projects/{{ project.name }}/experiments">Experiments</a>
        <a class="sidebar-link" href="/projects/{{ project.name }}/methods">Methods</a>
        <a class="sidebar-link" href="/projects/{{ project.name }}/knowledge">Knowledge</a>
        <a class="sidebar-link" href="/projects/{{ project.name }}/run">Run</a>
        <a class="sidebar-link" href="/projects/{{ project.name }}/settings">Settings</a>
      </div>
    {% else %}
      <a class="sidebar-link" href="/projects">Projects</a>
      <a class="sidebar-link" href="/settings">Settings</a>
    {% endif %}
  </nav>
</aside>
```

**Step 4: Add the new modifier class to `static/app.css`**

Append to the `.sidebar-link` block area:

```css
.sidebar-link--back {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  margin-bottom: var(--space-3);
}
.sidebar-link--back:hover { color: var(--text); }
```

**Step 5: Run tests + verify all dashboard tests still pass**

Run: `pytest tests/test_dashboard/ -v 2>&1 | tail -10`
Expected: all green (3 new + everything prior).

**Step 6: Commit**

```bash
git commit -m "feat(dashboard): bifurcated sidebar (global vs project mode)

When inside a project the sidebar replaces the global Projects/
Settings links with a 'Back to projects' link plus project-scoped
nav. When outside a project (projects list, global settings) the
sidebar shows only the global links. No more dual-list confusion."
```

---

### Task 10A.2: Visual audit — accent color, button modifiers, dark mode

**Files:**
- Modify: any template that renders a button/link without the proper modifier class — most likely `projects_list.html`, `project_home.html`, `experiments.html`, `experiment_detail.html`, `run.html`, `run_log.html`.
- Modify: `src/urika/dashboard/static/app.css` if the design-system colors are not landing (check `:root` vs body inheritance).

**Step 1: Manual audit pass**

Open each template and check:

- Every `<a>` rendered as a clickable link has a class. Default link styling should make `<a>` blue on white, light blue on dark; if not, fix `.list-item-link` and the bare-`a` rules in app.css.
- Every `<button>` has either `.btn .btn--primary`, `.btn .btn--secondary`, or `.btn .btn--ghost`. No button without a modifier.
- The breadcrumb uses `.breadcrumb` and `.breadcrumb-current`/`.breadcrumb-separator` (some templates use `.breadcrumb-sep` per the Task 6.5 implementer note).

**Step 2: Snapshot test for accent visibility**

Add `tests/test_dashboard/test_visual_audit.py`:

```python
"""Lightweight assertions that key pages render with design-system markers."""

def test_projects_list_uses_design_system(client_with_projects):
    r = client_with_projects.get("/projects")
    body = r.text
    # Page is using the base template (so CSS is loaded)
    assert '/static/app.css' in body
    # Any button on the page uses a modifier class
    import re
    bare_btns = re.findall(r'<button[^>]*\bclass="btn"[^>]*>', body)
    assert bare_btns == [], f"Found bare .btn buttons (no modifier): {bare_btns}"


def test_project_home_uses_design_system(client_with_projects):
    r = client_with_projects.get("/projects/alpha")
    body = r.text
    assert '/static/app.css' in body
    import re
    assert re.findall(r'<button[^>]*\bclass="btn"[^>]*>', body) == []
```

(Add similar one-liners for each main page if you want. Keep terse.)

**Step 3: Fix offenders**

For each offender the test catches, change `<button class="btn">` → `<button class="btn btn--ghost">` (theme toggle) or `<button class="btn btn--primary">` (primary action) etc. The theme-toggle button in `_base.html` already uses `.btn--ghost` — verify, fix if not.

**Step 4: Verify dark-mode swap works**

Quick programmatic check, not a test (browser-dependent):

```bash
python -c "
from urika.dashboard.app import create_app
from fastapi.testclient import TestClient
app = create_app(project_root=None)
client = TestClient(app)
r = client.get('/static/app.css')
assert '[data-theme=\"dark\"]' in r.text
assert 'data-theme' in r.text
print('OK')
"
```

**Step 5: Commit**

```bash
git commit -m "fix(dashboard): apply design system uniformly

Buttons without modifier classes were rendering as bare gray boxes
because .btn alone has no color rules. Added .btn--ghost / .btn--primary
modifiers to every button. Light test asserts no bare .btn slips back
in. Verified dark-mode swap continues to work via the data-theme
attribute on <html>."
```

---

## Phase 10B — Artifact viewers & experiment detail rework

### Task 10B.1: Add markdown rendering helper

**Files:**
- Modify: `pyproject.toml` (add `markdown>=3.5`)
- Create: `src/urika/dashboard/render.py`
- Test: `tests/test_dashboard/test_render.py`

**Step 1: Add the dep**

```toml
    "markdown>=3.5",
```

Run: `pip install -e ".[dev]" 2>&1 | tail -3`
Expected: succeeds.

**Step 2: Failing test**

```python
# tests/test_dashboard/test_render.py
"""Markdown → HTML rendering helper."""

from urika.dashboard.render import render_markdown


def test_render_markdown_basic():
    html = render_markdown("# Title\n\nbody")
    assert "<h1>Title</h1>" in html
    assert "<p>body</p>" in html


def test_render_markdown_handles_empty():
    assert render_markdown("") == ""
    assert render_markdown(None) == ""


def test_render_markdown_escapes_html_in_source():
    """Literal <script> tags from agent-written reports must not execute."""
    html = render_markdown("Plain text with <script>alert(1)</script>.")
    assert "<script>" not in html or "&lt;script&gt;" in html


def test_render_markdown_supports_fenced_code():
    html = render_markdown("```python\nx = 1\n```")
    assert "<code" in html
```

**Step 3: Implement**

```python
# src/urika/dashboard/render.py
"""Markdown → HTML helper used by the report viewer and the
formatted JSON pages.

Escapes raw HTML by default — agent-generated reports are
untrusted from the dashboard's perspective.
"""

from __future__ import annotations


def render_markdown(source: str | None) -> str:
    if not source:
        return ""
    try:
        import markdown
    except ImportError:
        # Graceful degradation: just escape and pre-wrap.
        from html import escape
        return f"<pre>{escape(source)}</pre>"

    md = markdown.Markdown(
        extensions=["fenced_code", "tables", "toc"],
        # safe_mode is deprecated; the modern approach is bleach or just
        # escape. Use Markdown's built-in escape via the extension list
        # plus html-escape any <script>/<iframe>/etc. on the input side.
    )
    # Pre-process: strip common dangerous tags
    import re
    cleaned = re.sub(
        r"<(script|iframe|object|embed)\b[^>]*>.*?</\1>",
        "",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(
        r"<(script|iframe|object|embed)\b[^>]*/?>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return md.convert(cleaned)
```

**Step 4: Run tests**

Run: `pytest tests/test_dashboard/test_render.py -v`
Expected: 4 passed.

**Step 5: Commit**

```bash
git commit -m "feat(dashboard): markdown render helper

render_markdown(source) wraps the python-markdown library with
fenced-code/tables/toc extensions and pre-strips <script>/<iframe>
tags. Agent-written reports go through this before being injected
into pages. Falls back to a <pre> dump if markdown isn't installed
(it's a hard dep but the fallback keeps us safe in odd envs)."
```

---

### Task 10B.2: Report viewer page

**Files:**
- Modify: `src/urika/dashboard/routers/pages.py`
- Create: `src/urika/dashboard/templates/report_view.html`
- Test: append to `tests/test_dashboard/test_pages_project.py`

**Step 1: Failing tests**

```python
def test_report_view_renders_markdown(client_with_runs):
    # Fabricate report.md
    proj = client_with_runs.app.state.project_root / "alpha"
    exp_dir = proj / "experiments" / "exp-001"
    (exp_dir / "report.md").write_text("# Findings\n\nLinear models fit best.")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/report")
    assert r.status_code == 200
    assert "<h1>Findings</h1>" in r.text
    assert "Linear models fit best." in r.text


def test_report_view_404_when_no_report(client_with_runs):
    """exp-001 has no report.md by default in this fixture."""
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/report")
    assert r.status_code == 404


def test_report_view_404_unknown_experiment(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-999/report")
    assert r.status_code == 404
```

**Step 2: Implement route**

```python
@router.get("/projects/{name}/experiments/{exp_id}/report", response_class=HTMLResponse)
def experiment_report(name: str, exp_id: str, request: Request) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    report_path = summary.path / "experiments" / exp_id / "report.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="No report for this experiment")

    from urika.dashboard.render import render_markdown
    body_html = render_markdown(report_path.read_text(encoding="utf-8"))
    return request.app.state.templates.TemplateResponse(
        "report_view.html",
        {
            "request": request,
            "project": summary,
            "experiment_id": exp_id,
            "body_html": body_html,
        },
    )
```

**Step 3: Implement template**

```html
{# src/urika/dashboard/templates/report_view.html #}
{% extends "_base.html" %}

{% block title %}Report · {{ experiment_id }} · Urika{% endblock %}
{% block heading %}Report: {{ experiment_id }}{% endblock %}

{% block breadcrumb %}
<nav class="breadcrumb">
  <a class="breadcrumb-item" href="/projects">Projects</a>
  <span class="breadcrumb-separator">/</span>
  <a class="breadcrumb-item" href="/projects/{{ project.name }}">{{ project.name }}</a>
  <span class="breadcrumb-separator">/</span>
  <a class="breadcrumb-item" href="/projects/{{ project.name }}/experiments">Experiments</a>
  <span class="breadcrumb-separator">/</span>
  <a class="breadcrumb-item" href="/projects/{{ project.name }}/experiments/{{ experiment_id }}">{{ experiment_id }}</a>
  <span class="breadcrumb-separator">/</span>
  <span class="breadcrumb-current">Report</span>
</nav>
{% endblock %}

{% block content %}
<article class="card markdown-body">
  {{ body_html | safe }}
</article>
{% endblock %}
```

**Step 4: Add `.markdown-body` styling to `static/app.css`**

```css
.markdown-body { line-height: var(--lh-body); }
.markdown-body h1, .markdown-body h2, .markdown-body h3 {
  margin-top: var(--space-5);
  margin-bottom: var(--space-3);
}
.markdown-body h1 { font-size: var(--fs-xl); }
.markdown-body h2 { font-size: var(--fs-lg); }
.markdown-body h3 { font-size: var(--fs-md); }
.markdown-body p { margin-bottom: var(--space-3); }
.markdown-body code {
  font-family: var(--font-mono);
  background: var(--bg-code);
  padding: 2px 4px;
  border-radius: 4px;
  font-size: 0.9em;
}
.markdown-body pre {
  background: var(--bg-code);
  padding: var(--space-3);
  border-radius: 6px;
  overflow-x: auto;
}
.markdown-body pre code { background: transparent; padding: 0; }
.markdown-body table {
  border-collapse: collapse;
  margin: var(--space-3) 0;
}
.markdown-body th, .markdown-body td {
  border: 1px solid var(--border);
  padding: var(--space-2) var(--space-3);
}
.markdown-body th { background: var(--bg-elevated); }
```

**Step 5: Run tests, commit**

```bash
git commit -m "feat(dashboard): per-experiment report viewer

GET /projects/<n>/experiments/<id>/report renders the experiment's
report.md as styled HTML inside a card. 404 when no report.md exists.
Uses the new render_markdown helper. .markdown-body CSS gives heading
hierarchy, code blocks, tables a real layout."
```

---

### Task 10B.3: Per-experiment presentation viewer

**Files:**
- Modify: `src/urika/dashboard/routers/pages.py`
- Test: append to `test_pages_project.py`

The presentation is an existing reveal.js HTML file at `<exp>/presentation.html` (or under `<exp>/presentation/index.html` for some pipelines — verify by reading the presentation_agent code). It's already a complete HTML document with its own `<head>` etc.; serve it as-is rather than embedding.

**Step 1: Failing tests**

```python
def test_presentation_view_serves_html_file(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    exp_dir = proj / "experiments" / "exp-001"
    (exp_dir / "presentation.html").write_text(
        "<!DOCTYPE html><html><body>fake reveal deck</body></html>"
    )
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/presentation")
    assert r.status_code == 200
    assert "fake reveal deck" in r.text
    # Served as text/html, not wrapped in our base template
    assert "<aside class=\"sidebar\"" not in r.text


def test_presentation_view_404_when_missing(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/presentation")
    assert r.status_code == 404
```

**Step 2: Implement**

```python
from fastapi.responses import FileResponse

@router.get("/projects/{name}/experiments/{exp_id}/presentation")
def experiment_presentation(name: str, exp_id: str):
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    exp_dir = summary.path / "experiments" / exp_id
    # presentation.html OR presentation/index.html — try both
    for candidate in (
        exp_dir / "presentation.html",
        exp_dir / "presentation" / "index.html",
    ):
        if candidate.exists():
            return FileResponse(candidate, media_type="text/html")
    raise HTTPException(status_code=404, detail="No presentation for this experiment")
```

**Step 3: Tests pass + commit**

```bash
git commit -m "feat(dashboard): per-experiment presentation viewer

Serves <exp>/presentation.html (or presentation/index.html) as raw
HTML so the reveal.js deck loads with its own <head>. The
experiment detail page (Task 10B.5) opens this in a new tab so
keyboard shortcuts (F, ESC, S) work as designed."
```

---

### Task 10B.4: Per-experiment artifacts list endpoint + viewer

**Files:**
- Modify: `src/urika/dashboard/routers/pages.py` (artifact viewer)
- Modify: `src/urika/dashboard/routers/api.py` (extend `experiment_artifacts` to also list files in `<exp>/artifacts/`)
- Test: append to `test_pages_project.py` and `test_api_artifacts.py`

**Step 1: Failing tests**

```python
# In test_api_artifacts.py
def test_artifacts_endpoint_lists_files_in_artifacts_dir(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    artifacts_dir = proj / "experiments" / "exp-001" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "fig1.png").write_bytes(b"fakepng")
    (artifacts_dir / "table.csv").write_text("a,b\n1,2\n")

    r = client_with_runs.get("/api/projects/alpha/experiments/exp-001/artifacts")
    assert r.status_code == 200
    data = r.json()
    files = {f["name"] for f in data["files"]}
    assert files == {"fig1.png", "table.csv"}
```

**Step 2: Extend the API endpoint**

In the existing `api_experiment_artifacts`, add:

```python
artifacts_dir = exp_dir / "artifacts"
files = []
if artifacts_dir.exists():
    for p in sorted(artifacts_dir.iterdir()):
        if p.is_file():
            files.append({
                "name": p.name,
                "size": p.stat().st_size,
                "url": f"/projects/{name}/experiments/{exp_id}/artifacts/{p.name}",
            })

return {
    "has_report": (exp_dir / "report.md").exists(),
    "has_presentation": (exp_dir / "presentation.html").exists() or (exp_dir / "presentation" / "index.html").exists(),
    "has_log": (exp_dir / "run.log").exists(),
    "files": files,
}
```

**Step 3: Add the artifact-file viewer page route**

```python
# In routers/pages.py
@router.get("/projects/{name}/experiments/{exp_id}/artifacts/{filename}")
def experiment_artifact_file(name: str, exp_id: str, filename: str):
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    # Resist path traversal
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    artifact_path = summary.path / "experiments" / exp_id / "artifacts" / filename
    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(artifact_path)
```

**Step 4: Add tests for the file viewer**

```python
def test_artifact_file_viewer_serves_png(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    artifacts_dir = proj / "experiments" / "exp-001" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "fig.png").write_bytes(b"\x89PNGfake")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/artifacts/fig.png")
    assert r.status_code == 200
    assert r.content.startswith(b"\x89PNG")


def test_artifact_file_viewer_rejects_traversal(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/artifacts/..%2F..%2Fetc%2Fpasswd")
    # FastAPI URL-decodes path params, so this becomes "../../etc/passwd"
    # but our slash/.. check rejects it.
    assert r.status_code in (400, 404)
```

**Step 5: Commit**

```bash
git commit -m "feat(dashboard): artifact list + file viewer

Extends the artifacts endpoint to list files under <exp>/artifacts/
with size + per-file URL. New page route /projects/<n>/experiments/<id>/artifacts/<file>
serves the actual file with FastAPI's FileResponse. Rejects path-
traversal attempts via slash/.. check on the filename. The
experiment detail page (next task) consumes the list to render
clickable thumbnails / links."
```

---

### Task 10B.5: Experiment detail page rework

**Files:**
- Modify: `src/urika/dashboard/routers/pages.py` (extend `experiment_detail` to fetch the artifacts list inline)
- Modify: `src/urika/dashboard/templates/experiment_detail.html`
- Test: extend `test_pages_project.py`

**Step 1: Failing tests**

```python
def test_experiment_detail_shows_report_button_when_present(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    exp_dir = proj / "experiments" / "exp-001"
    (exp_dir / "report.md").write_text("# Findings")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "View report" in body
    assert "/projects/alpha/experiments/exp-001/report" in body


def test_experiment_detail_shows_generate_buttons_when_artifacts_missing(client_with_runs):
    """When report.md / presentation.html aren't there, show 'Generate'
    buttons that POST to the relevant agent endpoint."""
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "Generate report" in body or "Run finalize" in body
    assert "Generate presentation" in body or "Run present" in body


def test_experiment_detail_lists_artifacts(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    artifacts_dir = proj / "experiments" / "exp-001" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "fig1.png").write_bytes(b"fake")
    (artifacts_dir / "table.csv").write_text("a,b")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "fig1.png" in body
    assert "table.csv" in body


def test_experiment_detail_presentation_link_opens_new_tab(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    (proj / "experiments" / "exp-001" / "presentation.html").write_text("<html></html>")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    # The presentation link must open in a new tab
    import re
    m = re.search(
        r'<a[^>]*href="/projects/alpha/experiments/exp-001/presentation"[^>]*>',
        body,
    )
    assert m is not None
    assert 'target="_blank"' in m.group(0)
```

**Step 2: Update the route to include artifacts**

```python
def experiment_detail(name: str, exp_id: str, request: Request) -> HTMLResponse:
    # ... existing 404 / load_experiment / progress code ...

    artifacts_dir = exp_dir / "artifacts"
    artifact_files = []
    if artifacts_dir.exists():
        for p in sorted(artifacts_dir.iterdir()):
            if p.is_file():
                artifact_files.append({
                    "name": p.name,
                    "url": f"/projects/{name}/experiments/{exp_id}/artifacts/{p.name}",
                    "size": p.stat().st_size,
                })

    return templates.TemplateResponse(
        "experiment_detail.html",
        {
            "request": request,
            "project": summary,
            "experiment": exp,
            "runs": runs,
            "has_report": has_report,
            "has_presentation": has_presentation,
            "has_log": has_log,
            "artifact_files": artifact_files,
        },
    )
```

**Step 3: Rework the template**

The template gets a clear "Artifacts" section with three sub-blocks:

```html
{# experiment_detail.html — artifacts block, replaces the resource-buttons row #}

<section class="artifacts">
  <h2 class="section-heading">Outputs</h2>

  <div class="artifact-row">
    <div class="artifact-row-label">Report</div>
    <div class="artifact-row-actions">
      {% if has_report %}
        <a class="btn btn--primary" href="/projects/{{ project.name }}/experiments/{{ experiment.experiment_id }}/report">View report</a>
      {% else %}
        <form
          hx-post="/api/projects/{{ project.name }}/finalize"
          hx-target="#finalize-feedback"
          hx-swap="innerHTML"
          style="display:inline"
        >
          <button class="btn btn--secondary" type="submit">Generate report (run finalize)</button>
          <span id="finalize-feedback" class="text-muted"></span>
        </form>
      {% endif %}
    </div>
  </div>

  <div class="artifact-row">
    <div class="artifact-row-label">Presentation</div>
    <div class="artifact-row-actions">
      {% if has_presentation %}
        <a class="btn btn--primary"
           href="/projects/{{ project.name }}/experiments/{{ experiment.experiment_id }}/presentation"
           target="_blank" rel="noopener">
          Open presentation ↗
        </a>
      {% else %}
        <form
          hx-post="/api/projects/{{ project.name }}/present"
          hx-target="#present-feedback"
          hx-swap="innerHTML"
          style="display:inline"
        >
          <input type="hidden" name="experiment_id" value="{{ experiment.experiment_id }}">
          <button class="btn btn--secondary" type="submit">Generate presentation</button>
          <span id="present-feedback" class="text-muted"></span>
        </form>
      {% endif %}
    </div>
  </div>

  <div class="artifact-row">
    <div class="artifact-row-label">Run log</div>
    <div class="artifact-row-actions">
      {% if has_log %}
        <a class="btn btn--secondary" href="/projects/{{ project.name }}/experiments/{{ experiment.experiment_id }}/log">View live log</a>
      {% else %}
        <span class="text-muted">No log yet — start a run</span>
      {% endif %}
    </div>
  </div>

  {% if artifact_files %}
    <div class="artifact-row">
      <div class="artifact-row-label">Files</div>
      <div class="artifact-row-actions">
        <ul class="artifact-files">
          {% for f in artifact_files %}
            <li>
              <a href="{{ f.url }}" target="_blank" rel="noopener">{{ f.name }}</a>
              <span class="text-muted">{{ f.size }} bytes</span>
            </li>
          {% endfor %}
        </ul>
      </div>
    </div>
  {% endif %}
</section>
```

Add minimal CSS:

```css
.artifacts { margin-top: var(--space-5); }
.section-heading {
  font-size: var(--fs-lg);
  font-weight: var(--fw-semibold);
  margin-bottom: var(--space-3);
}
.artifact-row {
  display: flex;
  gap: var(--space-4);
  align-items: center;
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--border);
}
.artifact-row-label {
  width: 140px;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.artifact-row-actions { flex: 1; display: flex; gap: var(--space-3); align-items: center; flex-wrap: wrap; }
.artifact-files { list-style: none; padding: 0; }
.artifact-files li { padding: var(--space-1) 0; }
```

**Step 4: Run tests + commit**

```bash
git commit -m "feat(dashboard): experiment detail rework — artifact-first

Outputs block now shows Report / Presentation / Log / Files rows.
Each row has a 'View' button when the artifact exists, or a
'Generate' button (HTMX-posted to the finalize/present endpoint)
when it doesn't. Presentation links open in a new tab so reveal.js
keyboard shortcuts work. Artifact files under <exp>/artifacts/
appear as a clickable list."
```

---

## Phase 10C — Settings page completeness

### Task 10C.1: Tabbed layout primitive

**Files:**
- Modify: `src/urika/dashboard/static/app.css` (add `.tabs`, `.tab-list`, `.tab-button`, `.tab-panel`)
- Modify: `src/urika/dashboard/templates/_macros.html` (new)

**Step 1: Author the tab macro**

```html
{# src/urika/dashboard/templates/_macros.html #}

{% macro tabs(name, panels) %}
{# panels = list of {id, label} dicts; the caller supplies the panel
   bodies as Jinja blocks named after the panel ids. #}
<div x-data="{ active: '{{ panels[0].id }}' }" class="tabs">
  <div class="tab-list" role="tablist">
    {% for p in panels %}
      <button
        class="tab-button"
        :class="{ 'tab-button--active': active === '{{ p.id }}' }"
        @click="active = '{{ p.id }}'"
        role="tab"
        type="button"
      >{{ p.label }}</button>
    {% endfor %}
  </div>
  {{ caller(active='') }}
</div>
{% endmacro %}
```

(The macro renders the tab bar and a placeholder slot; the caller provides the panel content with `x-show="active === '<id>'"`.)

**Step 2: CSS**

```css
.tabs { margin-top: var(--space-3); }
.tab-list {
  display: flex;
  gap: var(--space-1);
  border-bottom: 1px solid var(--border);
  margin-bottom: var(--space-4);
}
.tab-button {
  padding: var(--space-2) var(--space-4);
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  border-bottom: 2px solid transparent;
  transition: 150ms ease;
}
.tab-button:hover { color: var(--text); }
.tab-button--active {
  color: var(--text);
  border-bottom-color: var(--accent);
}
.tab-panel { padding: var(--space-3) 0; }
```

**Step 3: Commit**

```bash
git commit -m "feat(dashboard): tabs primitive

_macros.tabs(name, panels) renders an Alpine-controlled tab bar.
Used by the next two tasks (project settings, global settings) to
group related fields without scroll-walls."
```

---

### Task 10C.2: Project settings — full set

**Files:**
- Modify: `src/urika/dashboard/templates/project_settings.html` (rewrite into tabbed layout)
- Modify: `src/urika/dashboard/routers/pages.py` (load full urika.toml, not just the ProjectSummary fields)
- Modify: `src/urika/dashboard/routers/api.py` (the PUT endpoint accepts the new fields)
- Modify: `src/urika/core/revisions.py` if needed to support more fields
- Test: `tests/test_dashboard/test_pages_settings.py` and `test_api_settings.py`

**Tabs to deliver:**

1. **Basics** — name (read-only), question, description, mode, audience.
2. **Data** — `data_paths` (multi-line textarea, one path per line), success_criteria (key=value lines).
3. **Models** — `[runtime].model` (project override). `[runtime.models.<agent>]` per-agent overrides — render as a small grid: agent name | model | endpoint dropdown.
4. **Privacy** — view-only summary of inherited global privacy mode + the project's `[privacy]` overrides if any. Editing is global-only for now (link to /settings).
5. **Notifications** — `[notifications]` section (channels list, suppress level). Same shape as `urika notifications` interactive setup.

**Per-tab content / form fields**:

- Basics: same 4 fields as today.
- Data: `<textarea name="data_paths">` with one path per line. `<textarea name="success_criteria">` with `metric=threshold` per line.
- Models: emit one row per known agent (planning_agent, task_agent, evaluator, advisor_agent, tool_builder, literature_agent, presentation_agent, report_agent, project_builder, data_agent, finalizer). Each row: `<input name="model[<agent>]">`, `<select name="endpoint[<agent>]">` with options open/private/inherit. The PUT handler iterates these.
- Privacy: read-only block. A "Configure privacy globally" link to `/settings`.
- Notifications: `<input type="checkbox" name="channels" value="ntfy">` plus a list of channel-specific config fields. Mirror the interactive CLI setup.

**Implementation approach:**

The PUT handler grows to handle the new field families. Don't try to make `update_project_field` handle every nested key — for the more structured fields (data_paths, models, notifications) write them directly to urika.toml using the same load-mutate-save pattern, and append a single revision entry per top-level field updated (e.g. `field="data_paths"`, `new_value="<count> paths"`).

Add tests for:
- Saving data_paths writes an array to `[project].data_paths`.
- Saving model overrides writes to `[runtime.models.<agent>]`.
- Saving notifications writes to `[notifications]`.
- Each save records exactly one revision entry per top-level field changed.

**Commit:**

```bash
git commit -m "feat(dashboard): project settings — full coverage

Project settings page is now a 5-tab layout: Basics, Data, Models,
Privacy (read-only), Notifications. PUT /api/projects/<n>/settings
extends to write data_paths (as a list), per-agent model+endpoint
overrides under [runtime.models.<agent>], and the [notifications]
section. Privacy is global-only for now — the tab links to /settings.
revisions.json gets one entry per changed top-level field."
```

---

### Task 10C.3: Global settings — full set

**Files:**
- Modify: `src/urika/dashboard/templates/global_settings.html` (tabbed layout)
- Modify: `src/urika/dashboard/routers/pages.py` (load full settings dict)
- Modify: `src/urika/dashboard/routers/api.py` (PUT handler accepts more fields)

**Tabs to deliver:**

1. **Privacy** — mode picker (open / private / hybrid). Per-mode endpoint config:
   - **open** — default cloud model dropdown.
   - **private** — endpoint URL, API key env var, model name.
   - **hybrid** — cloud model (used by most agents) + private endpoint URL/key/model (used by data_agent, tool_builder).
   The form shows ALL THREE blocks but only the active one is required; submit-time validation enforces required fields per mode.
2. **Models** — default model (top-level `[runtime].model`) + per-agent overrides (same grid as project settings).
3. **Preferences** — default audience, default max_turns, web_search toggle, venv toggle.
4. **Notifications** — channels + per-channel config. Mirror the interactive CLI's setup.

The form's submit handler PUTs to `/api/settings` with all fields in one payload. The handler reads the full payload, builds the new settings dict, and calls `save_settings(...)`.

Tests for each tab's round-trip:
- Set mode=private with endpoint=http://localhost:11434, model=qwen3 → settings.toml has [privacy.endpoints.private] with the right values.
- Set per-agent override → settings.toml has [runtime.models.<agent>] table.
- Toggle notifications → settings.toml has [notifications] section.

**Commit:**

```bash
git commit -m "feat(dashboard): global settings — full coverage

Global settings page is now a 4-tab layout: Privacy, Models,
Preferences, Notifications. The Privacy tab renders the open /
private / hybrid configuration trees that match the 'urika config'
interactive setup. Save writes the full ~/.urika/settings.toml in
one shot. The five-field stub from Phase 5.3 is replaced by this."
```

---

## Phase 10D — JSON-as-formatted-views audit

### Task 10D.1: Methods page — drop the embedded JSON dump

**Files:**
- Modify: `src/urika/dashboard/templates/methods.html`

The current methods page embeds the full methods list as JSON via `{{ methods | tojson }}` for Alpine to sort client-side. That JSON is visible in `view-source`. Replacement: server-render the table fully; do client-side sort by adding `data-sort-*` attributes to rows and a small Alpine controller that re-orders the DOM.

**Step 1: Replace template**

```html
{% block content %}
{% if methods %}
<div x-data="{ sortBy: 'name', desc: true }">
  <div class="methods-controls">
    <label>Sort by:
      <select x-model="sortBy" @change="sortRows()" class="select">
        <option value="name">Name</option>
        {% for k in metric_keys %}
          <option value="{{ k }}">{{ k }}</option>
        {% endfor %}
      </select>
    </label>
    <button class="btn btn--ghost" @click="desc = !desc; sortRows()" x-text="desc ? '↓' : '↑'"></button>
  </div>

  <ul class="list" id="methods-list">
    {% for m in methods %}
      <li class="list-item"
          data-sort-name="{{ m.name }}"
          {% for k, v in m.metrics.items() %}data-sort-{{ k }}="{{ v }}"{% endfor %}>
        <div class="list-item-main">
          <div class="list-item-title">{{ m.name }}</div>
          <div class="list-item-subtitle">{{ m.description }}</div>
        </div>
        <div class="list-item-meta">
          {% for k, v in m.metrics.items() %}
            <span class="metric-pill">{{ k }}={% if v is number %}{{ "%.3f"|format(v) }}{% else %}{{ v }}{% endif %}</span>
          {% endfor %}
          <span class="tag">{{ m.status }}</span>
        </div>
      </li>
    {% endfor %}
  </ul>

  <script>
    function sortRows() {
      const list = document.getElementById('methods-list');
      const rows = Array.from(list.children);
      const ctx = Alpine.$data(list.parentElement);
      const key = `data-sort-${ctx.sortBy}`;
      rows.sort((a, b) => {
        const av = a.getAttribute(key);
        const bv = b.getAttribute(key);
        if (av === null && bv === null) return 0;
        if (av === null) return 1;
        if (bv === null) return -1;
        const an = parseFloat(av), bn = parseFloat(bv);
        if (!isNaN(an) && !isNaN(bn)) return ctx.desc ? bn - an : an - bn;
        return ctx.desc ? bv.localeCompare(av) : av.localeCompare(bv);
      });
      rows.forEach(r => list.appendChild(r));
    }
  </script>
</div>
{% else %}
<div class="empty-state">
  <p>No methods registered yet.</p>
</div>
{% endif %}
{% endblock %}
```

**Step 2: Test**

Update `test_methods_page_returns_200_and_lists_methods` (or add) to assert that NO JSON-dump pattern appears in the page source (`assert '"name":' not in body and '"metrics":' not in body`).

**Step 3: Commit**

```bash
git commit -m "fix(dashboard): methods page no longer leaks raw JSON

The Alpine sort previously embedded {{ methods | tojson }} which
left a JSON dump in the page source. Replaced with server-rendered
rows + data-sort-* attributes; the sort happens by re-ordering DOM
nodes. Same UX, no JSON dump."
```

---

### Task 10D.2: Findings viewer (formatted, not raw)

**Files:**
- Modify: `src/urika/dashboard/routers/pages.py`
- Create: `src/urika/dashboard/templates/findings.html`
- Modify: `src/urika/dashboard/templates/project_home.html` (link to it)

`projectbook/findings.json` is finalize's output. Render it as a structured page: title (from findings), top-level summary, then a table of metrics, then a list of methods with their final ranks. NEVER show the raw JSON.

**Step 1: Inspect the schema**

Look at `src/urika/agents/finalizer.py` or `src/urika/core/labbook.py` for the findings.json schema if known. Otherwise read one from a real project (or build a minimal mock from the prompt for the finalizer). Likely keys: `summary`, `best_method`, `metrics_table`, `methods_ranking`, `recommendations`.

**Step 2: Implement route + template**

```python
@router.get("/projects/{name}/findings", response_class=HTMLResponse)
def project_findings(name: str, request: Request) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    findings_path = summary.path / "projectbook" / "findings.json"
    if not findings_path.exists():
        raise HTTPException(status_code=404, detail="No findings yet")
    import json
    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    return request.app.state.templates.TemplateResponse(
        "findings.html",
        {"request": request, "project": summary, "findings": findings},
    )
```

Template renders each well-known key as its own block (summary as paragraph, metrics_table as `<table>`, methods_ranking as `<ol>`). Unknown keys go into a "More" collapsible block where each value is rendered as either a plain string, a list, or a key-value dl — but never raw JSON.

**Step 3: Test**

```python
def test_findings_page_renders_well_known_fields(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    import json
    (book / "findings.json").write_text(json.dumps({
        "summary": "Linear models fit best.",
        "best_method": "ols",
        "metrics_table": [{"method": "ols", "r2": 0.9}, {"method": "rf", "r2": 0.8}],
    }))
    r = client_with_runs.get("/projects/alpha/findings")
    body = r.text
    assert "Linear models fit best." in body
    assert "ols" in body
    assert "0.9" in body
    # NO JSON dump
    assert '"summary":' not in body
    assert '"metrics_table":' not in body
```

**Step 4: Link from project home**

In `project_home.html`, add a "Final outputs" card (Phase 10E will expand this):

```html
{% if has_findings %}
<a class="card card--linked" href="/projects/{{ project.name }}/findings">
  <div class="card-title">Findings</div>
  <div class="card-body">View final findings →</div>
</a>
{% endif %}
```

**Step 5: Commit**

```bash
git commit -m "feat(dashboard): findings viewer (formatted, no JSON)

projectbook/findings.json renders as structured HTML — summary
paragraph, metrics table, methods ranking. Unknown keys land in a
'More' block where each value is rendered as a string/list/dl, never
as raw JSON. Page is reachable from the project home when findings
exist."
```

---

### Task 10D.3: Page audit — no /api/* in any rendered link

**Files:**
- Modify: any template that exposes `/api/...` as a clickable link.

**Step 1: Audit**

```bash
grep -rn "/api/" src/urika/dashboard/templates/
```

Every match should be either:
- A `hx-post=...`, `hx-put=...`, `hx-get=...` attribute (HTMX, programmatic).
- A `fetch("/api/...")` inline script (programmatic).
- An `EventSource("/api/...")` (programmatic).

NONE should be a regular `<a href="/api/...">` link.

**Step 2: Fix any offenders**

Convert any `<a href="/api/...">` to either a button posting via HTMX, or a link to the HTML viewer for the resource.

**Step 3: Add a regression test**

```python
# tests/test_dashboard/test_no_api_links.py
"""No browser-rendered page should expose /api/* as a clickable href."""

import re
import pytest


PAGES_TO_AUDIT = [
    "/projects",
    "/projects/alpha",
    "/projects/alpha/experiments",
    "/projects/alpha/experiments/exp-001",
    "/projects/alpha/experiments/exp-001/log",
    "/projects/alpha/methods",
    "/projects/alpha/knowledge",
    "/projects/alpha/run",
    "/projects/alpha/settings",
    "/settings",
]

@pytest.mark.parametrize("path", PAGES_TO_AUDIT)
def test_no_api_href_in_rendered_page(client_with_runs, path):
    # Some routes need different fixtures; skip 404s
    r = client_with_runs.get(path)
    if r.status_code == 404:
        pytest.skip(f"{path} 404 in this fixture")
    assert r.status_code == 200
    # Find all <a href="..."> values and assert none start with /api/
    for m in re.finditer(r'<a[^>]*\bhref="(/api/[^"]+)"', r.text):
        pytest.fail(f"Page {path} exposes /api/* link: {m.group(1)}")
```

**Step 4: Commit**

```bash
git commit -m "test(dashboard): regression — no /api/* in rendered page links

Programmatic /api/* endpoints are agent/script targets, not
user-facing. Added a parametrized test that loads each main page
and asserts no <a href="/api/..."> survives — only HTMX hx-* and
fetch() calls may reference /api/."
```

---

## Phase 10E — Project home: final outputs surface

### Task 10E.1: Final outputs card on project home

**Files:**
- Modify: `src/urika/dashboard/routers/pages.py` (extend `project_home` to detect projectbook artifacts)
- Modify: `src/urika/dashboard/templates/project_home.html`
- Test: append to `test_pages_project.py`

**Step 1: Failing test**

```python
def test_project_home_shows_final_outputs_when_present(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    (book / "findings.json").write_text("{}")
    (book / "report.md").write_text("# Final report")
    (book / "presentation.html").write_text("<html></html>")
    r = client_with_runs.get("/projects/alpha")
    body = r.text
    assert "Final outputs" in body
    assert "/projects/alpha/findings" in body
    assert "/projects/alpha/projectbook/report" in body or "Final report" in body
    assert "/projects/alpha/projectbook/presentation" in body or "presentation" in body
```

**Step 2: Implement the projectbook viewers**

Add to `routers/pages.py`:

```python
@router.get("/projects/{name}/projectbook/report", response_class=HTMLResponse)
def projectbook_report(name: str, request: Request) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404)
    report_path = summary.path / "projectbook" / "report.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="No final report")
    from urika.dashboard.render import render_markdown
    return request.app.state.templates.TemplateResponse(
        "report_view.html",
        {
            "request": request,
            "project": summary,
            "experiment_id": "",  # template handles empty
            "body_html": render_markdown(report_path.read_text(encoding="utf-8")),
            "title_override": "Final report",
        },
    )


@router.get("/projects/{name}/projectbook/presentation")
def projectbook_presentation(name: str):
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404)
    book = summary.path / "projectbook"
    for candidate in (book / "presentation.html", book / "presentation" / "index.html"):
        if candidate.exists():
            return FileResponse(candidate, media_type="text/html")
    raise HTTPException(status_code=404, detail="No final presentation")
```

**Step 3: Extend `project_home` to detect them**

```python
book = summary.path / "projectbook"
final_outputs = {
    "has_findings": (book / "findings.json").exists(),
    "has_report": (book / "report.md").exists(),
    "has_presentation": (book / "presentation.html").exists() or (book / "presentation" / "index.html").exists(),
}
# Pass into template context
```

**Step 4: Render the card**

```html
{% if final_outputs.has_findings or final_outputs.has_report or final_outputs.has_presentation %}
<section class="final-outputs">
  <h2 class="section-heading">Final outputs</h2>
  <div class="final-outputs-grid">
    {% if final_outputs.has_findings %}
      <a class="card card--linked" href="/projects/{{ project.name }}/findings">
        <div class="card-title">Findings</div>
        <div class="card-body text-muted">Best method, key metrics, ranking.</div>
      </a>
    {% endif %}
    {% if final_outputs.has_report %}
      <a class="card card--linked" href="/projects/{{ project.name }}/projectbook/report">
        <div class="card-title">Report</div>
        <div class="card-body text-muted">Full narrative write-up.</div>
      </a>
    {% endif %}
    {% if final_outputs.has_presentation %}
      <a class="card card--linked" href="/projects/{{ project.name }}/projectbook/presentation" target="_blank" rel="noopener">
        <div class="card-title">Presentation ↗</div>
        <div class="card-body text-muted">Reveal.js slide deck.</div>
      </a>
    {% endif %}
  </div>
</section>
{% endif %}
```

CSS for the grid:

```css
.final-outputs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-3);
}
.card--linked {
  display: block;
  text-decoration: none;
  color: inherit;
  transition: 150ms ease;
}
.card--linked:hover {
  border-color: var(--accent);
  box-shadow: 0 4px 12px rgba(0,0,0,.08);
}
```

**Step 5: Commit**

```bash
git commit -m "feat(dashboard): project home — final outputs surface

When projectbook/{findings.json, report.md, presentation.html}
exist, the project home page shows a 'Final outputs' grid with
clickable cards. Findings open the formatted viewer; report opens
the markdown viewer; presentation opens in a new tab. The cards
only appear when the corresponding artifact exists."
```

---

## Phase 10F — Docs + smoke

### Task 10F.1: Update docs/19-dashboard.md

**Files:**
- Modify: `docs/19-dashboard.md`

Add sections covering:
- Sidebar bifurcation (global vs project mode + back button).
- Artifact viewers (per-experiment report + presentation + files; project-level findings + report + presentation).
- Settings tabs (basics / data / models / privacy / notifications for project; privacy / models / preferences / notifications for global).
- "JSON is for agents/scripts; pages render formatted views" principle.

**Commit:**

```bash
git commit -m "docs(dashboard): polish-phase additions"
```

---

### Task 10F.2: Final smoke checklist

**Files:**
- Create: `dev/plans/2026-04-26-dashboard-polish-smoke.md`

Checklist (manual, browser-based):

- [ ] Sidebar shows global links on /projects and /settings; back button + project nav inside a project.
- [ ] Theme toggle: light → dark → reload → preserved.
- [ ] Buttons: every visible button is colored (primary blue or ghost transparent), no bare-gray buttons.
- [ ] Project home: "Final outputs" cards appear when artifacts exist; click each one — no 404s.
- [ ] Experiment detail: "Generate report" button when no report.md; "View report" when present. Same for presentation. Files list shows uploaded artifacts.
- [ ] Click "Generate report" — runs finalize subprocess, log streams in, report appears after.
- [ ] Click "View presentation" — opens in new tab; reveal.js navigation works.
- [ ] Findings page renders structured (title, summary, metrics table) — no JSON dump.
- [ ] Methods page sorts client-side; no JSON in view-source.
- [ ] Settings (project): all 5 tabs render; saving Data → adds to revisions.json. Saving Models → updates urika.toml. Saving Notifications → updates urika.toml.
- [ ] Settings (global): all 4 tabs render; Privacy mode picker works; Notifications config persists.
- [ ] No /api/* link is reachable by clicking through the UI (only via HTMX/fetch internally).

---

## Execution notes

- **TDD throughout** — every task has at least one failing test first.
- **Commit per task** — 24 commits for this phase.
- **No new dependencies** beyond `markdown>=3.5` (Task 10B.1).
- **Skills to invoke during execution:**
  - @superpowers:test-driven-development on every code task
  - @superpowers:verification-before-completion before marking complete
  - @pr-review-toolkit:code-reviewer after each phase
- **Stop conditions:** if Phase 10C (settings completeness) hits unexpected complexity (deeply nested TOML edits, validation interactions with core/models VALID_AUDIENCES) — stop, write up the issue, and consider shipping just the Basics tab + Privacy tab for global settings, deferring the rest.
- **Deferred from this plan:**
  - Audience expansion to `{"expert", "standard", "novice"}` in core/models.py (a real cross-cutting change; needs its own plan).
  - Cookie/query-param auth fallback (Phase 9.3 left bearer-only).
  - WebSocket upgrade for interactive prompts inside browser-launched runs.
