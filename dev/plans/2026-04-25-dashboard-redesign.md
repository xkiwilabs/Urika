# Dashboard Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current static read-only dashboard with a multi-page local web app that becomes a third primary interface alongside CLI and TUI — modern minimal aesthetic, projects-list landing, project home, experiment detail, live-streamed agent runs triggered from the browser, in-browser settings editing.

**Architecture:** FastAPI + Uvicorn server with Jinja2 templates and HTMX/Alpine.js for interactivity, served by a hand-written CSS design system. The dashboard owns subprocesses it spawns (writes PIDs to existing lockfiles); cross-surface awareness with TUI/CLI is filesystem-mediated through `<exp>/.lock` + `progress.json` + a new `<exp>/run.log`. SSE streams live run output to the browser. All-in packaging — `pip install urika` includes the web stack (~12MB extra).

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Jinja2, HTMX (CDN), Alpine.js (CDN), hand-written CSS, pytest + httpx for testing.

**Replaces:** Phase 5 of `dev/plans/2026-04-24-release-polish.md`. The 3 tasks under that Phase 5 (SSE live-reload, search/breadcrumb/responsive, optional auth) are subsumed here.

**Estimated total:** ~30 tasks across 9 phases. Phases 1–3 (~3 days) build the backend skeleton + design system; phases 4–6 (~4 days) implement the page surfaces; phase 7 (~1.5 days) adds run invocation + streaming; phases 8–9 (~1.5 days) settings/tests/docs.

---

## Design System — Visual Constants

These constants are referenced repeatedly throughout the plan. They live in `src/urika/dashboard/static/app.css` once Task 2.1 lands.

```
Colors (light):
  --bg              #ffffff   page background
  --bg-elevated     #f8fafc   cards
  --bg-hover        #f1f5f9   hovered list items
  --bg-code         #f1f5f9   code blocks / log lines
  --border          #e2e8f0   subtle dividers
  --border-strong   #cbd5e1   form fields
  --text            #0f172a   primary
  --text-muted      #64748b   secondary
  --text-subtle     #94a3b8   tertiary
  --accent          #2563eb   the one accent — links, primary buttons
  --accent-hover    #1d4ed8
  --success         #16a34a
  --warn            #ca8a04
  --error           #dc2626

Colors (dark):
  --bg              #0a0a0a
  --bg-elevated     #161616
  --bg-hover        #1f1f1f
  --bg-code         #161616
  --border          #262626
  --border-strong   #404040
  --text            #fafafa
  --text-muted      #a3a3a3
  --text-subtle     #737373
  --accent          #3b82f6
  --accent-hover    #60a5fa
  (success/warn/error: keep light values; they read fine on dark)

Typography:
  --font-ui     'Inter', -apple-system, system-ui, sans-serif
  --font-mono   'JetBrains Mono', 'SF Mono', Consolas, monospace
  --fs-xs   13px
  --fs-sm   14px         body
  --fs-md   16px         subheading
  --fs-lg   20px         section header
  --fs-xl   28px         page title
  --fw-regular   400
  --fw-medium    500
  --fw-semibold  600
  --lh-tight     1.3
  --lh-body      1.55

Spacing (4px unit):
  --space-1   4px
  --space-2   8px
  --space-3   12px
  --space-4   16px
  --space-5   24px
  --space-6   32px
  --space-7   48px
  --space-8   64px

Radii: 6px (small), 8px (cards), 12px (buttons)
Shadows: 0 1px 2px rgba(0,0,0,.04) (resting), 0 4px 12px rgba(0,0,0,.08) (hover)
Transitions: 150ms ease (everything)
Sidebar width: 240px
Content max-width: 1100px
```

---

## Phase 0 — Pre-flight (5 minutes)

### Task 0.1: Confirm baseline

Run: `pytest -q 2>&1 | tail -3`
Expected: `1456 passed`. If any fail, triage before starting.

Run: `git status --short`
Expected: clean working tree on `dev`.

---

## Phase 1 — Backend skeleton (FastAPI + routing)

### Task 1.1: Add web dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

**Step 1: Edit dependencies**

In the `dependencies = [...]` block, add after the existing entries:

```toml
    # Dashboard (FastAPI server + templating)
    "fastapi>=0.110,<1.0",
    "uvicorn[standard]>=0.27,<1.0",
    "jinja2>=3.1",
```

**Step 2: Reinstall**

Run: `pip install -e ".[dev]" 2>&1 | tail -5`
Expected: succeeds, fastapi/uvicorn/jinja2 installed.

**Step 3: Smoke check imports**

Run: `python -c "import fastapi, uvicorn, jinja2; print(fastapi.__version__, uvicorn.__version__, jinja2.__version__)"`
Expected: three versions printed, no errors.

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add fastapi/uvicorn/jinja2 to base dependencies

Dashboard is becoming a third primary interface — needs to be
available out of the box for pip install urika users. Adds ~12MB
to the install footprint, acceptable for a scientific platform that
already pulls scikit-learn, matplotlib, xgboost."
```

---

### Task 1.2: Decide naming — new dashboard module sits beside the old one

**Files:** none yet — this is a documentation/decision task.

The current `src/urika/dashboard/` (server.py, tree.py, renderer.py, templates/dashboard.html) will be **replaced wholesale** at the end of Phase 9. Until then, the new code lives at `src/urika/dashboard_v2/` so we don't break the running dashboard.

At the end of Phase 9, we delete the old files and rename `dashboard_v2/` → `dashboard/` in a single commit.

This task is just confirming the naming. No commit.

---

### Task 1.3: Scaffold dashboard_v2 package

**Files:**
- Create: `src/urika/dashboard_v2/__init__.py`
- Create: `src/urika/dashboard_v2/app.py`
- Create: `src/urika/dashboard_v2/templates/.gitkeep`
- Create: `src/urika/dashboard_v2/static/.gitkeep`
- Test: `tests/test_dashboard_v2/test_app_skeleton.py`

**Step 1: Write the failing test**

```python
# tests/test_dashboard_v2/test_app_skeleton.py
"""Tests for the FastAPI app skeleton."""

from __future__ import annotations

from fastapi.testclient import TestClient

from urika.dashboard_v2.app import create_app


def test_create_app_returns_fastapi_instance():
    from fastapi import FastAPI

    app = create_app(project_root=None)
    assert isinstance(app, FastAPI)


def test_health_endpoint_returns_ok():
    app = create_app(project_root=None)
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

**Step 2: Verify it fails**

Run: `pytest tests/test_dashboard_v2/test_app_skeleton.py -v 2>&1 | tail -15`
Expected: ImportError — `urika.dashboard_v2.app` doesn't exist.

**Step 3: Implement the skeleton**

Create `src/urika/dashboard_v2/__init__.py` (empty file).

Create `src/urika/dashboard_v2/app.py`:

```python
"""FastAPI app factory for the Urika dashboard v2.

The factory takes the projects root (where individual project
directories live, normally ``~/urika-projects/``) so tests can pass
a tmp dir. Routers attach to the app inside this function.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI


def create_app(project_root: Path | None) -> FastAPI:
    """Create a configured FastAPI app for the dashboard.

    ``project_root`` is the directory that contains all registered
    Urika projects (e.g. ``~/urika-projects``). The dashboard reads
    the project registry to enumerate them; it never writes outside a
    project's own directory.
    """
    app = FastAPI(title="Urika Dashboard", docs_url=None, redoc_url=None)
    app.state.project_root = project_root

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

Create `tests/test_dashboard_v2/__init__.py` (empty).

**Step 4: Verify it passes**

Run: `pytest tests/test_dashboard_v2/test_app_skeleton.py -v 2>&1 | tail -10`
Expected: 2 passed.

**Step 5: Commit**

```bash
git add src/urika/dashboard_v2/ tests/test_dashboard_v2/
git commit -m "feat(dashboard_v2): FastAPI app factory skeleton

create_app() returns a configured FastAPI instance. /healthz is
the only route initially; routers attach in subsequent tasks.
The project_root parameter (None in tests, real path in production)
is held on app.state and is what the project-registry endpoints will
read from."
```

---

### Task 1.4: Project-registry helper module

**Files:**
- Create: `src/urika/dashboard_v2/projects.py`
- Test: `tests/test_dashboard_v2/test_projects_helper.py`

**Step 1: Write the failing tests**

```python
# tests/test_dashboard_v2/test_projects_helper.py
"""Project-registry adapter for the dashboard v2.

Wraps the existing ProjectRegistry (~/.urika/projects.json) plus
on-disk project state so the dashboard pages have a single ergonomic
shape to consume.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.dashboard_v2.projects import (
    ProjectSummary,
    list_project_summaries,
    load_project_summary,
)


def _make_project(root: Path, name: str, *, with_experiment: bool = False) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'name = "{name}"\nquestion = "test q"\nmode = "exploratory"\n'
        f'description = ""\naudience = "standard"\n'
    )
    if with_experiment:
        exp_dir = proj / "experiments" / "exp-001"
        exp_dir.mkdir(parents=True)
        import json
        (exp_dir / "experiment.json").write_text(json.dumps({
            "experiment_id": "exp-001",
            "name": "baseline",
            "hypothesis": "test",
            "created": "2026-04-25T00:00:00Z",
        }))
        (exp_dir / "progress.json").write_text(json.dumps({
            "experiment_id": "exp-001",
            "status": "completed",
            "runs": [{"method": "ols", "metrics": {"r2": 0.5}}],
        }))
    return proj


def test_list_project_summaries_empty(tmp_path: Path):
    assert list_project_summaries({}) == []


def test_list_project_summaries_one_project(tmp_path: Path):
    proj = _make_project(tmp_path, "alpha")
    registry = {"alpha": proj}
    summaries = list_project_summaries(registry)
    assert len(summaries) == 1
    assert summaries[0].name == "alpha"
    assert summaries[0].path == proj
    assert summaries[0].experiment_count == 0


def test_list_project_summaries_with_experiment(tmp_path: Path):
    proj = _make_project(tmp_path, "alpha", with_experiment=True)
    registry = {"alpha": proj}
    summaries = list_project_summaries(registry)
    assert summaries[0].experiment_count == 1


def test_list_project_summaries_skips_missing_directory(tmp_path: Path):
    """Registry can point at a deleted project dir; surface it as
    'missing' rather than crashing."""
    registry = {"ghost": tmp_path / "does_not_exist"}
    summaries = list_project_summaries(registry)
    assert len(summaries) == 1
    assert summaries[0].missing is True


def test_load_project_summary_unknown_returns_none(tmp_path: Path):
    assert load_project_summary("nope", {}) is None


def test_load_project_summary_loads_full_metadata(tmp_path: Path):
    proj = _make_project(tmp_path, "alpha", with_experiment=True)
    registry = {"alpha": proj}
    summary = load_project_summary("alpha", registry)
    assert summary is not None
    assert summary.question == "test q"
    assert summary.mode == "exploratory"
```

**Step 2: Run — expect failure**

Run: `pytest tests/test_dashboard_v2/test_projects_helper.py -v 2>&1 | tail -15`
Expected: ImportError.

**Step 3: Implement**

Create `src/urika/dashboard_v2/projects.py`:

```python
"""Project enumeration helper for the dashboard.

Wraps ProjectRegistry + per-project urika.toml + experiments/ scan
into a single ProjectSummary dataclass that templates can render
without touching multiple modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from urika.core.experiment import list_experiments
from urika.core.workspace import load_project_config


@dataclass
class ProjectSummary:
    """One row in the projects-list view."""

    name: str
    path: Path
    question: str = ""
    mode: str = ""
    description: str = ""
    audience: str = "standard"
    experiment_count: int = 0
    missing: bool = False


def list_project_summaries(
    registry: dict[str, Path],
) -> list[ProjectSummary]:
    """Build a summary for every entry in the registry, sorted by name.

    A registry entry whose directory has been deleted is included with
    ``missing=True`` so the UI can show it greyed-out rather than
    silently dropping it.
    """
    summaries: list[ProjectSummary] = []
    for name, path in sorted(registry.items()):
        if not path.exists():
            summaries.append(ProjectSummary(name=name, path=path, missing=True))
            continue
        try:
            cfg = load_project_config(path)
        except FileNotFoundError:
            summaries.append(ProjectSummary(name=name, path=path, missing=True))
            continue
        try:
            n_experiments = len(list_experiments(path))
        except Exception:
            n_experiments = 0
        summaries.append(
            ProjectSummary(
                name=name,
                path=path,
                question=cfg.question,
                mode=cfg.mode,
                description=cfg.description,
                audience=cfg.audience,
                experiment_count=n_experiments,
            )
        )
    return summaries


def load_project_summary(
    name: str,
    registry: dict[str, Path],
) -> ProjectSummary | None:
    path = registry.get(name)
    if path is None:
        return None
    if not path.exists():
        return ProjectSummary(name=name, path=path, missing=True)
    try:
        cfg = load_project_config(path)
    except FileNotFoundError:
        return ProjectSummary(name=name, path=path, missing=True)
    try:
        n_experiments = len(list_experiments(path))
    except Exception:
        n_experiments = 0
    return ProjectSummary(
        name=name,
        path=path,
        question=cfg.question,
        mode=cfg.mode,
        description=cfg.description,
        audience=cfg.audience,
        experiment_count=n_experiments,
    )
```

**Step 4: Run — expect green**

Run: `pytest tests/test_dashboard_v2/test_projects_helper.py -v 2>&1 | tail -10`
Expected: 6 passed.

**Step 5: Commit**

```bash
git add src/urika/dashboard_v2/projects.py tests/test_dashboard_v2/test_projects_helper.py
git commit -m "feat(dashboard_v2): ProjectSummary helper

list_project_summaries() and load_project_summary() wrap the
ProjectRegistry + per-project urika.toml + experiments scan into
one dataclass that templates can render without touching multiple
modules. Missing-directory case is surfaced as missing=True rather
than dropped silently."
```

---

## Phase 2 — Design system + base layout

### Task 2.1: Hand-written CSS design system

**Files:**
- Create: `src/urika/dashboard_v2/static/app.css`

**Step 1: Author the file**

Create `src/urika/dashboard_v2/static/app.css` containing all the constants from "Design System — Visual Constants" at the top of this plan, plus base resets and the 7 base components. Aim for ~400-500 lines.

Key components to include (each a single class block):

- `.btn` (with `.btn--primary`, `.btn--secondary`, `.btn--ghost`)
- `.card`
- `.list-item`
- `.breadcrumb`
- `.tag` (with `.tag--running`, `.tag--completed`, `.tag--paused`, `.tag--failed`)
- `.metric` (large stat number + label)
- `.log-line` (terminal output rendering with monospace + subtle row hover)

Plus layout primitives:
- `body`, `*` resets
- `.app-shell` (full-height flex with sidebar + main)
- `.sidebar` (240px, collapsible via `[aria-expanded]`)
- `.main` (centered content, max-width 1100px)
- `.page-header` (breadcrumb + page title)
- `.empty-state` (used when a list has no items)
- `.skeleton` (loading shimmer for fetches >200ms)

All colors use the CSS custom properties; no hard-coded hex outside `:root` and `[data-theme="dark"]`.

**Step 2: Manual visual smoke**

No tests for CSS — but verify it parses by serving a smoke template (deferred to Task 2.3).

**Step 3: Commit**

```bash
git add src/urika/dashboard_v2/static/app.css
git commit -m "feat(dashboard_v2): design-system CSS

Hand-written CSS defining the 7-component vocabulary (btn, card,
list-item, breadcrumb, tag, metric, log-line) and the layout
primitives (app-shell, sidebar, main, page-header, empty-state,
skeleton). Color/typography/spacing scales as CSS custom properties
so the dark-mode toggle is a single attribute swap. Linear/Vercel-
inspired aesthetic — generous whitespace, no uppercase tracking,
restrained accent palette."
```

---

### Task 2.2: Base Jinja template + theme toggle

**Files:**
- Create: `src/urika/dashboard_v2/templates/_base.html`
- Create: `src/urika/dashboard_v2/templates/_sidebar.html`

**Step 1: Author `_base.html`**

```html
<!DOCTYPE html>
<html lang="en" data-theme="{{ theme | default('light') }}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Urika{% endblock %}</title>
  <link rel="stylesheet" href="/static/app.css">
  <script src="https://unpkg.com/htmx.org@1.9.10" defer></script>
  <script src="https://unpkg.com/alpinejs@3.13.5/dist/cdn.min.js" defer></script>
</head>
<body
  x-data="{ theme: localStorage.getItem('urika-theme') || 'light' }"
  x-init="document.documentElement.dataset.theme = theme"
  :data-theme="theme"
>
  <div class="app-shell">
    {% include '_sidebar.html' %}
    <main class="main">
      <header class="page-header">
        {% block breadcrumb %}{% endblock %}
        <h1 class="page-title">{% block heading %}{% endblock %}</h1>
        <button
          class="btn btn--ghost theme-toggle"
          @click="theme = theme === 'light' ? 'dark' : 'light'; localStorage.setItem('urika-theme', theme)"
          x-text="theme === 'light' ? 'Dark' : 'Light'"
          aria-label="Toggle theme"
        ></button>
      </header>
      {% block content %}{% endblock %}
    </main>
  </div>
</body>
</html>
```

**Step 2: Author `_sidebar.html`**

```html
<aside class="sidebar" x-data="{ open: true }" :aria-expanded="open">
  <a class="brand" href="/">
    <span class="wordmark">Urika</span>
  </a>
  <nav class="sidebar-nav">
    <a class="sidebar-link" href="/projects">Projects</a>
    <a class="sidebar-link" href="/settings">Settings</a>
    {% if project %}
      <div class="sidebar-section">
        <div class="sidebar-section-label">{{ project.name }}</div>
        <a class="sidebar-link" href="/projects/{{ project.name }}">Home</a>
        <a class="sidebar-link" href="/projects/{{ project.name }}/experiments">Experiments</a>
        <a class="sidebar-link" href="/projects/{{ project.name }}/methods">Methods</a>
        <a class="sidebar-link" href="/projects/{{ project.name }}/knowledge">Knowledge</a>
        <a class="sidebar-link" href="/projects/{{ project.name }}/run">Run</a>
        <a class="sidebar-link" href="/projects/{{ project.name }}/settings">Settings</a>
      </div>
    {% endif %}
  </nav>
</aside>
```

**Step 3: Commit**

```bash
git add src/urika/dashboard_v2/templates/_base.html src/urika/dashboard_v2/templates/_sidebar.html
git commit -m "feat(dashboard_v2): base template + sidebar with theme toggle

_base.html defines the page shell and pulls in HTMX + Alpine via
CDN. Theme toggle is pure Alpine + localStorage. _sidebar.html
shows global links always; project links only when a project is
loaded into the request context. No JavaScript build, no bundled
JS — just two CDN scripts."
```

---

### Task 2.3: Wire static + template loading into the FastAPI app

**Files:**
- Modify: `src/urika/dashboard_v2/app.py`
- Test: `tests/test_dashboard_v2/test_static_and_template.py`

**Step 1: Failing tests**

```python
# tests/test_dashboard_v2/test_static_and_template.py
from fastapi.testclient import TestClient

from urika.dashboard_v2.app import create_app


def test_app_serves_static_css():
    app = create_app(project_root=None)
    client = TestClient(app)
    r = client.get("/static/app.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    assert "--accent" in r.text  # design-system var present


def test_app_has_jinja_environment_attached():
    app = create_app(project_root=None)
    assert hasattr(app.state, "templates")
    # Template directory should resolve _base.html
    tpl = app.state.templates.get_template("_base.html")
    assert tpl is not None
```

**Step 2: Implement**

Update `src/urika/dashboard_v2/app.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_PKG_DIR = Path(__file__).parent
_TEMPLATES_DIR = _PKG_DIR / "templates"
_STATIC_DIR = _PKG_DIR / "static"


def create_app(project_root: Path | None) -> FastAPI:
    app = FastAPI(title="Urika Dashboard", docs_url=None, redoc_url=None)
    app.state.project_root = project_root
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

**Step 3: Run tests**

Run: `pytest tests/test_dashboard_v2/ -v 2>&1 | tail -10`
Expected: 4 passed (the 2 new + 2 prior).

**Step 4: Commit**

```bash
git add src/urika/dashboard_v2/app.py tests/test_dashboard_v2/test_static_and_template.py
git commit -m "feat(dashboard_v2): mount /static and Jinja templates"
```

---

## Phase 3 — Routing skeleton + projects-list page

### Task 3.1: Routers package with empty router stubs

**Files:**
- Create: `src/urika/dashboard_v2/routers/__init__.py`
- Create: `src/urika/dashboard_v2/routers/pages.py`
- Create: `src/urika/dashboard_v2/routers/api.py`
- Modify: `src/urika/dashboard_v2/app.py` to include the routers

**Step 1: Create router stubs**

`src/urika/dashboard_v2/routers/__init__.py`: empty file.

`src/urika/dashboard_v2/routers/pages.py`:
```python
"""HTML page routes — server-rendered Jinja templates."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["pages"])
```

`src/urika/dashboard_v2/routers/api.py`:
```python
"""JSON API routes — used by HTMX fragments and external callers."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["api"])
```

**Step 2: Wire into app.py**

In `create_app()`, after templates/static setup:

```python
    from urika.dashboard_v2.routers import pages, api
    app.include_router(pages.router)
    app.include_router(api.router)
```

**Step 3: Commit**

```bash
git add src/urika/dashboard_v2/routers/ src/urika/dashboard_v2/app.py
git commit -m "feat(dashboard_v2): routers package skeleton

pages.router holds HTML routes; api.router holds /api/* JSON
routes. Both are empty initially; subsequent tasks attach
endpoints to each."
```

---

### Task 3.2: GET / and /projects → projects list page

**Files:**
- Modify: `src/urika/dashboard_v2/routers/pages.py`
- Create: `src/urika/dashboard_v2/templates/projects_list.html`
- Test: `tests/test_dashboard_v2/test_pages_projects.py`

**Step 1: Failing tests**

```python
# tests/test_dashboard_v2/test_pages_projects.py
from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from urika.dashboard_v2.app import create_app


@pytest.fixture
def client_with_projects(tmp_path: Path, monkeypatch) -> TestClient:
    """A dashboard whose registry is forced to point at tmp projects."""
    # Fabricate two projects on disk
    for name in ("alpha", "beta"):
        proj = tmp_path / name
        proj.mkdir()
        (proj / "urika.toml").write_text(
            f'name = "{name}"\nquestion = "q for {name}"\nmode = "exploratory"\n'
            f'description = ""\naudience = "standard"\n'
        )

    # Force the ProjectRegistry to read from a tmp file
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({
        "alpha": str(tmp_path / "alpha"),
        "beta": str(tmp_path / "beta"),
    }))

    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_root_redirects_to_projects(client_with_projects: TestClient):
    r = client_with_projects.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/projects"


def test_projects_list_shows_all_projects(client_with_projects: TestClient):
    r = client_with_projects.get("/projects")
    assert r.status_code == 200
    body = r.text
    assert "alpha" in body
    assert "beta" in body
    assert "q for alpha" in body


def test_projects_list_empty_state(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    r = client.get("/projects")
    assert r.status_code == 200
    assert "No projects" in r.text or "No projects yet" in r.text
```

**Step 2: Implement page route**

In `src/urika/dashboard_v2/routers/pages.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from urika.core.registry import ProjectRegistry
from urika.dashboard_v2.projects import list_project_summaries

router = APIRouter(tags=["pages"])


@router.get("/", response_class=RedirectResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/projects", status_code=307)


@router.get("/projects", response_class=HTMLResponse)
def projects_list(request: Request) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summaries = list_project_summaries(registry)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "projects_list.html",
        {"request": request, "projects": summaries},
    )
```

**Step 3: Implement template**

`src/urika/dashboard_v2/templates/projects_list.html`:

```html
{% extends "_base.html" %}

{% block title %}Projects · Urika{% endblock %}
{% block heading %}Projects{% endblock %}

{% block content %}
  {% if projects %}
    <ul class="list">
      {% for p in projects %}
        <li class="list-item {{ 'list-item--missing' if p.missing else '' }}">
          <a href="/projects/{{ p.name }}" class="list-item-link">
            <div class="list-item-main">
              <div class="list-item-title">{{ p.name }}</div>
              {% if p.question %}
                <div class="list-item-subtitle">{{ p.question }}</div>
              {% endif %}
            </div>
            <div class="list-item-meta">
              {% if p.missing %}
                <span class="tag tag--failed">missing</span>
              {% else %}
                <span class="text-muted">{{ p.experiment_count }} experiments</span>
                <span class="tag">{{ p.mode }}</span>
              {% endif %}
            </div>
          </a>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <div class="empty-state">
      <p>No projects yet.</p>
      <p class="text-muted">Create one with: <code>urika new &lt;name&gt;</code></p>
    </div>
  {% endif %}
{% endblock %}
```

**Step 4: Run tests**

Run: `pytest tests/test_dashboard_v2/ -v 2>&1 | tail -15`
Expected: 7 passed.

**Step 5: Commit**

```bash
git add -A
git commit -m "feat(dashboard_v2): projects list page

GET / redirects to /projects. /projects renders all registered
projects via the ProjectSummary helper. Missing-directory entries
are shown with a 'missing' tag. Empty state hints at the right
CLI command."
```

---

### Task 3.3: API endpoint /api/projects (JSON)

**Files:**
- Modify: `src/urika/dashboard_v2/routers/api.py`
- Test: `tests/test_dashboard_v2/test_api_projects.py`

**Step 1: Failing tests**

```python
# tests/test_dashboard_v2/test_api_projects.py
def test_api_projects_returns_json_list(client_with_projects):
    r = client_with_projects.get("/api/projects")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    names = {p["name"] for p in data}
    assert names == {"alpha", "beta"}
    for p in data:
        assert "question" in p
        assert "mode" in p
        assert "experiment_count" in p


def test_api_projects_empty_when_no_registry(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from urika.dashboard_v2.app import create_app
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json() == []
```

The `client_with_projects` fixture from `test_pages_projects.py` should be moved to `tests/test_dashboard_v2/conftest.py` so both files can use it. Do that as a small refactor first.

**Step 2: Implement**

In `src/urika/dashboard_v2/routers/api.py`:

```python
from __future__ import annotations

from fastapi import APIRouter

from urika.core.registry import ProjectRegistry
from urika.dashboard_v2.projects import list_project_summaries

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/projects")
def api_projects() -> list[dict]:
    registry = ProjectRegistry().list_all()
    summaries = list_project_summaries(registry)
    return [
        {
            "name": s.name,
            "path": str(s.path),
            "question": s.question,
            "mode": s.mode,
            "description": s.description,
            "audience": s.audience,
            "experiment_count": s.experiment_count,
            "missing": s.missing,
        }
        for s in summaries
    ]
```

**Step 3: Run tests + commit**

```bash
git commit -m "feat(dashboard_v2): GET /api/projects JSON endpoint"
```

---

## Phase 4 — Project home + experiment list pages

### Task 4.1: GET /projects/<name> → project home

**Files:**
- Modify: `src/urika/dashboard_v2/routers/pages.py`
- Create: `src/urika/dashboard_v2/templates/project_home.html`
- Test: `tests/test_dashboard_v2/test_pages_project.py`

**Step 1: Failing tests**

Test cases:
- `GET /projects/alpha` returns 200, contains the project name + question
- `GET /projects/unknown` returns 404
- The page lists recent experiments (top 5)
- Sidebar context includes `project=alpha`

**Step 2: Implement** — route reads `load_project_summary(name, registry)`, returns 404 if None or `missing=True`, else renders `project_home.html` with `project=summary` plus recent experiments via `list_experiments(summary.path)[-5:]`.

**Step 3: Commit**

---

### Task 4.2: GET /projects/<name>/experiments → experiment list

**Files:**
- Modify: `src/urika/dashboard_v2/routers/pages.py`
- Create: `src/urika/dashboard_v2/templates/experiments.html`
- Test: append to `tests/test_dashboard_v2/test_pages_project.py`

Pattern same as 4.1. Page shows table of experiments with name / id / status / runs / last-touched. Empty state for projects with no experiments.

**Step 3: Commit**

---

### Task 4.3: GET /projects/<name>/experiments/<exp_id> → experiment detail

**Files:**
- Modify: `src/urika/dashboard_v2/routers/pages.py`
- Create: `src/urika/dashboard_v2/templates/experiment_detail.html`
- Test: append

Page shows: experiment hypothesis, status tag, runs table (method / metrics / observation snippet), links to report / presentation / log / artifacts.

**Step 3: Commit**

---

### Task 4.4: GET /projects/<name>/methods → method registry

**Files:**
- Modify: `src/urika/dashboard_v2/routers/pages.py`
- Create: `src/urika/dashboard_v2/templates/methods.html`
- Test: append

Reads `<project>/methods.json`. Shows each method with metrics. Sortable by primary metric — sort happens client-side via Alpine `x-data="{ sortBy: 'name' }"`.

**Step 3: Commit**

---

### Task 4.5: GET /projects/<name>/knowledge → knowledge browser

**Files:**
- Modify: `src/urika/dashboard_v2/routers/pages.py`
- Create: `src/urika/dashboard_v2/templates/knowledge.html`

Reads project knowledge store via existing `urika.knowledge.KnowledgeStore`. Shows ingested entries with title / source-type / id. Click to view raw markdown.

**Step 3: Commit**

---

## Phase 5 — Settings pages (write surface)

### Task 5.1: GET /projects/<name>/settings → project settings page

**Files:**
- Modify: `src/urika/dashboard_v2/routers/pages.py`
- Create: `src/urika/dashboard_v2/templates/project_settings.html`
- Test: `tests/test_dashboard_v2/test_pages_settings.py`

Form for description / question / mode / audience. Each field has a `name` attribute matching the `urika.toml` key. Submit goes to `PUT /api/projects/<name>/settings` via HTMX.

**Step 3: Commit**

---

### Task 5.2: PUT /api/projects/<name>/settings — atomic write

**Files:**
- Modify: `src/urika/dashboard_v2/routers/api.py`
- Test: `tests/test_dashboard_v2/test_api_settings.py`

Calls `urika.core.revisions.update_project_field` for each changed field (so revisions.json gets entries). Validation: mode in `{"exploratory", "confirmatory", "pipeline"}`; audience in `{"expert", "standard", "novice"}`; description/question stripped. Returns the updated project_home fragment for HTMX swap (or JSON if `Accept: application/json`).

**Step 3: Commit**

---

### Task 5.3: GET /settings → global settings page + PUT /api/settings

**Files:**
- Modify: `src/urika/dashboard_v2/routers/pages.py`
- Modify: `src/urika/dashboard_v2/routers/api.py`
- Create: `src/urika/dashboard_v2/templates/global_settings.html`
- Test: `tests/test_dashboard_v2/test_global_settings.py`

Backed by `~/.urika/settings.toml`. Fields: default_privacy_mode, default_endpoint_url, default_endpoint_key_env, default_audience, default_max_turns. Same atomic-write pattern.

**Step 3: Commit**

---

## Phase 6 — Run launcher + SSE log streaming

### Task 6.1: `<exp>/run.log` writer in the orchestrator

**Files:**
- Modify: `src/urika/orchestrator/loop.py` — when a run starts, open `<project>/experiments/<exp>/run.log` in append mode; tee `print()` calls there too.

Actually do it cleaner: add an `OrchestratorLogger` context manager in a new `src/urika/orchestrator/run_log.py` that wraps `sys.stdout` to also write to `run.log`. Run-mode commands (`urika run`, the dashboard, the TUI) install it for the duration of the run.

**Files:**
- Create: `src/urika/orchestrator/run_log.py`
- Modify: `src/urika/cli/run.py` to wrap the orchestrator call in `OrchestratorLogger`
- Test: `tests/test_orchestrator/test_run_log.py`

**Step 1: Failing test**

```python
def test_run_log_writes_to_file(tmp_path: Path, capsys):
    from urika.orchestrator.run_log import OrchestratorLogger

    log_path = tmp_path / "run.log"
    with OrchestratorLogger(log_path):
        print("hello")
        print("world")
    content = log_path.read_text()
    assert "hello" in content
    assert "world" in content
    # Captured stdout still has the lines too
    out = capsys.readouterr().out
    assert "hello" in out
```

**Step 2: Implement** — `OrchestratorLogger` is a context manager that swaps `sys.stdout` for a tee writer that appends each line to the log file AND forwards to the original stdout. On exit, restores the original stdout.

**Step 3: Wire into `cli/run.py`** — wrap the run-experiment call in `OrchestratorLogger(project_path / "experiments" / experiment_id / "run.log")`.

**Step 4: Commit**

---

### Task 6.2: GET /projects/<name>/run → run launcher form

**Files:**
- Modify: `src/urika/dashboard_v2/routers/pages.py`
- Create: `src/urika/dashboard_v2/templates/run.html`
- Test: append

Form with the fields described in the design doc (experiment name, hypothesis, max turns, audience, mode, instructions). If a run is currently active, show the "view live →" link instead of the form.

**Step 3: Commit**

---

### Task 6.3: POST /api/projects/<name>/run — spawn subprocess

**Files:**
- Modify: `src/urika/dashboard_v2/routers/api.py`
- Create: `src/urika/dashboard_v2/runs.py` — subprocess spawn helper
- Test: `tests/test_dashboard_v2/test_api_run.py`

The endpoint:
1. Validates form fields.
2. Calls `urika.core.experiment.create_experiment` to materialize the experiment.
3. Spawns `subprocess.Popen([sys.executable, "-m", "urika", "run", project_name, "--experiment", exp_id, "--json", ...])` with `stdout=PIPE, stderr=STDOUT, bufsize=1, text=True`.
4. Spawns a daemon thread that reads stdout line-by-line and writes to `<exp>/run.log` (also writes the PID to `<exp>/.lock` if not already).
5. Returns `{"experiment_id": "<id>", "status": "started"}`.

The daemon-thread design means the dashboard process (uvicorn) keeps running after the function returns; the subprocess outlives the HTTP request.

Test the endpoint with a tiny shell script as the subprocess (use `monkeypatch` to replace `sys.executable` with `bash -c "echo started; sleep 0.1; echo done"`-equivalent so tests are fast).

**Step 3: Commit**

---

### Task 6.4: GET /api/runs/<exp_id>/stream — SSE log tailer

**Files:**
- Modify: `src/urika/dashboard_v2/routers/api.py`
- Test: `tests/test_dashboard_v2/test_api_stream.py`

Returns `StreamingResponse` with media type `text/event-stream`. Implementation: opens `<exp>/run.log` and emits `data: <line>\n\n` for each existing line, then polls for new lines every 0.5s. When the lockfile is removed, emits `event: status\ndata: {"status":"completed"}\n\n` and closes.

The test uses httpx-async to consume a few SSE events from a fixture log file.

**Step 3: Commit**

---

### Task 6.5: GET /projects/<name>/experiments/<exp_id>/log → live log page

**Files:**
- Modify: `src/urika/dashboard_v2/routers/pages.py`
- Create: `src/urika/dashboard_v2/templates/run_log.html`

Page contains a `<pre id="log"></pre>` and an inline `<script>` that opens an `EventSource('/api/runs/<id>/stream')` and appends each `data:` line to the `<pre>`. Status event reveals "view report" / "view presentation" links.

**Step 3: Commit**

---

### Task 6.6: POST /api/runs/<exp_id>/stop — request pause

**Files:**
- Modify: `src/urika/dashboard_v2/routers/api.py`
- Test: append to `test_api_run.py`

Writes a `pause_requested` flag (existing `pause_controller` mechanism) so the orchestrator stops at the next safe checkpoint. Returns `{"status": "stop_requested"}`.

**Step 3: Commit**

---

## Phase 7 — Other agent invocations from the browser

### Task 7.1: POST /api/projects/<name>/finalize

Mirrors 6.3. Spawns `urika finalize <project> --json`. Response includes the experiment ID (none — finalize is project-level) and tails the same `<project>/projectbook/finalize.log`.

### Task 7.2: POST /api/projects/<name>/advisor

Async-style: the advisor is short. POST receives `{question}`, calls advisor agent inline (not subprocess), returns the response markdown. Browser shows it in a modal or scrolls into a conversation panel.

### Task 7.3: POST /api/projects/<name>/present (per-experiment)

Mirrors 6.3. Spawns `urika present <project> --experiment <id>`.

Each of 7.1–7.3 is a small task, ~30 mins each.

---

## Phase 8 — TUI integration + auto-launch

### Task 8.1: TUI `/dashboard` slash command

**Files:**
- Modify: `src/urika/tui/app.py` (or wherever slash commands route in the TUI)
- Create: `src/urika/tui/dashboard_launcher.py`

`/dashboard` in the TUI:
1. Starts a uvicorn server in a background `threading.Thread` on a random free port.
2. Opens `http://127.0.0.1:<port>/projects/<current_project>` in the user's browser via `webbrowser.open`.
3. Stores the server reference on the TUI app so it can be shut down on `app.exit()`.

Test: a unit test that calls the launcher with a mock `webbrowser.open` and verifies the server starts + URL is correct.

### Task 8.2: `urika new` offers to open the dashboard

Modify `cli/project_new.py`: at the end of `new()` if `--json` is False and a project was created successfully, ask `interactive_confirm("Open the dashboard now?", default=True)`. If yes, spawn `urika dashboard <name>` as a subprocess and open the browser.

### Task 8.3: `urika dashboard` (no args) opens to projects list

Modify `cli/config.py` `dashboard` command (or wherever it lives — could be `cli/config_dashboard.py` after Phase 8 split): make `project` argument optional. If omitted, start the server and open `/projects`. If present, start the server and open `/projects/<name>`.

---

## Phase 9 — Cutover, cleanup, polish

### Task 9.1: Replace old dashboard with v2

**Files:**
- Delete: `src/urika/dashboard/server.py`, `src/urika/dashboard/tree.py`, `src/urika/dashboard/renderer.py`, `src/urika/dashboard/templates/dashboard.html`, `src/urika/dashboard/__init__.py`
- Move: `src/urika/dashboard_v2/*` → `src/urika/dashboard/*`
- Update imports across the codebase: `urika.dashboard_v2` → `urika.dashboard`
- Update tests: `tests/test_dashboard_v2/` → `tests/test_dashboard/`

```bash
git mv src/urika/dashboard_v2 src/urika/dashboard_new
git rm -r src/urika/dashboard
git mv src/urika/dashboard_new src/urika/dashboard
git mv tests/test_dashboard_v2 tests/test_dashboard
# fix imports with sed
git commit -m "chore(dashboard): cut over from dashboard_v2 to dashboard

Old BaseHTTPRequestHandler implementation removed. v2 (FastAPI)
takes its place. Imports updated; all tests still pass."
```

### Task 9.2: Update docs/13-configuration.md, docs/16-interactive-tui.md, docs/README.md

Add a new doc `docs/19-dashboard.md` describing the multi-page dashboard, run launcher, settings UI, theme toggle, and the cross-surface coordination model.

### Task 9.3: Add `--auth-token` option to `urika dashboard` and the corresponding header check

Inserts a single dependency in FastAPI that compares `Authorization: Bearer <token>` (constant-time) when auth_token is configured.

### Task 9.4: Final smoke + full pytest sweep

Run: `pytest -q` → all green.

Run: `urika dashboard <smoke-project>` → opens browser, navigate manually:
- Projects list → click into project
- Click Settings → edit description → save → page reloads with new value
- Click Run → fill form → click Start → watch SSE-streamed log → see completion
- Click Theme toggle → dark mode works → reload page → preserved
- Click sidebar Knowledge / Methods / Experiments → all render

Smoke checklist captured in `dev/plans/2026-04-25-dashboard-redesign-smoke.md`.

---

## Future work (post-0.2 release)

- WebSocket upgrade for interactive prompts inside browser-launched runs (currently SSE-only; if a run hits `click.prompt` it falls back to default values)
- Dashboard-driven advisor chat (conversation surface, like the TUI's free-text path)
- Edit-in-browser markdown for reports / projectbook content
- Multi-user auth model beyond a single bearer token
- OS-level "Open Urika" desktop shortcut that launches `urika dashboard`

---

## Execution notes

- **Commit per task.** Phase 4 / 5 / 6 sub-tasks each get their own commit.
- **TDD throughout** — every page route has at least a 200-status test and a content-presence test; every API endpoint has happy-path + invalid-input + auth tests.
- **No JS bundler.** HTMX and Alpine via CDN. If we ever want to add a dependency-managed JS, that's its own decision later.
- **Skills to invoke during execution:**
  - @superpowers:test-driven-development on every code task
  - @superpowers:verification-before-completion before marking complete
  - @pr-review-toolkit:code-reviewer after each phase
- **Worktree:** recommended for the cutover (Phase 9.1) since it touches many files at once. Use @superpowers:using-git-worktrees.
- **Stop conditions:** if Phase 6 (run streaming) hits unexpected complexity (subprocess buffering, lockfile races) — stop, write up the issue, and consider reducing scope to "view-only dashboard with run summaries but no live streaming" for the 0.2.0 release. Streaming can come in 0.2.1.
