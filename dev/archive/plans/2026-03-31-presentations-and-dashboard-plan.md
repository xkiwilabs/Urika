# Presentations, Reports & Project Dashboard — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add audience modes (novice/expert) to presentations and reports, fix presentation layout for viewport-locked scaling, add zoomable figures, and build a browser-based read-only project dashboard.

**Architecture:** Two independent features. Feature 1 modifies agent prompts + presentation template CSS/JS + CLI/REPL flags. Feature 2 adds a new `dashboard` module with a stdlib HTTP server, curated project tree, and a single-page HTML app. No new heavy dependencies.

**Tech Stack:** Python stdlib `http.server`, reveal.js (existing), CSS flexbox/clamp(), vanilla JS, `markdown` library (new lightweight dep for dashboard MD rendering).

---

## Feature 1: Audience Modes + Presentation Layout

### Task 1: Add `audience` field to ProjectConfig

**Files:**
- Modify: `src/urika/core/models.py:14-56`
- Test: `tests/test_core/test_models.py`

**Step 1: Write the failing test**

In `tests/test_core/test_models.py`, add:

```python
def test_audience_default_expert():
    """ProjectConfig defaults to expert audience."""
    config = ProjectConfig(name="test", question="q", mode="exploratory")
    assert config.audience == "expert"

def test_audience_from_toml():
    """ProjectConfig reads audience from preferences."""
    d = {
        "project": {"name": "test", "question": "q", "mode": "exploratory"},
        "preferences": {"audience": "novice"},
    }
    config = ProjectConfig.from_toml_dict(d)
    assert config.audience == "novice"

def test_audience_invalid_raises():
    """Invalid audience value raises ValueError."""
    import pytest
    with pytest.raises(ValueError, match="audience"):
        ProjectConfig(name="test", question="q", mode="exploratory", audience="beginner")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_models.py -v -k audience`
Expected: FAIL — `audience` field does not exist

**Step 3: Implement**

In `src/urika/core/models.py`, add to `ProjectConfig`:
- Field: `audience: str = "expert"` with validation against `VALID_AUDIENCES = {"expert", "novice"}`
- In `__post_init__`: validate `self.audience in VALID_AUDIENCES`
- In `from_toml_dict()`: read `d.get("preferences", {}).get("audience", "expert")`
- In `to_toml_dict()`: write under `preferences.audience`

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_models.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/core/models.py tests/test_core/test_models.py
git commit -m "feat: add audience field to ProjectConfig (expert/novice)"
```

---

### Task 2: Add `{audience_instructions}` to agent prompts

**Files:**
- Modify: `src/urika/agents/roles/prompts/presentation_agent_system.md`
- Modify: `src/urika/agents/roles/prompts/report_agent_system.md`
- Modify: `src/urika/agents/roles/prompts/finalizer_system.md`

**Step 1: Add audience block to presentation prompt**

At the end of `presentation_agent_system.md`, before `## Rules`, add:

```markdown
## Audience

{audience_instructions}
```

**Step 2: Add audience block to report prompt**

Same location in `report_agent_system.md`.

**Step 3: Add audience block to finalizer prompt**

Same location in `finalizer_system.md`. The finalizer writes `findings.json` which contains the `answer` field — this should adapt to audience.

**Step 4: Commit**

```bash
git add src/urika/agents/roles/prompts/
git commit -m "feat: add audience_instructions placeholder to agent prompts"
```

---

### Task 3: Pass `audience` variable through agent roles

**Files:**
- Modify: `src/urika/agents/roles/presentation_agent.py:28-57`
- Modify: `src/urika/agents/roles/report_agent.py:28-55`
- Modify: `src/urika/agents/roles/finalizer.py:28-56`
- Test: `tests/test_agents/test_presentation_agent_role.py`
- Test: `tests/test_agents/test_report_agent_role.py`

**Step 1: Write failing tests**

In `tests/test_agents/test_presentation_agent_role.py`, add:

```python
def test_audience_novice_in_prompt():
    """Novice audience instructions appear in system prompt."""
    role = AgentRegistry().discover().get("presentation_agent")
    config = role.build_config(
        project_dir=Path("/tmp/test"), experiment_id="exp-001", audience="novice"
    )
    assert "plain language" in config.system_prompt.lower()

def test_audience_expert_in_prompt():
    """Expert audience instructions appear in system prompt."""
    role = AgentRegistry().discover().get("presentation_agent")
    config = role.build_config(
        project_dir=Path("/tmp/test"), experiment_id="exp-001", audience="expert"
    )
    assert "domain expertise" in config.system_prompt.lower()
```

Similar tests for report_agent.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents/test_presentation_agent_role.py -v -k audience`
Expected: FAIL — `audience` keyword not accepted

**Step 3: Implement**

In each role's `build_config()`, add `audience: str = "expert"` parameter. Define two instruction strings:

```python
_AUDIENCE_INSTRUCTIONS = {
    "expert": (
        "Assume domain expertise. Use technical terminology freely. "
        "Focus on results and methodology. Keep explanations concise."
    ),
    "novice": (
        "Explain every method in plain language as if the reader has no "
        "statistics or ML background. For each method or model, add a "
        "'What this means' explanation. Define all technical terms on first use. "
        "Explain why each approach was chosen and what the results mean practically. "
        "Walk through results step by step. For presentations, include 1-2 extra "
        "slides per method explaining the approach conceptually before showing results."
    ),
}
```

Add to the prompt variables dict: `"audience_instructions": _AUDIENCE_INSTRUCTIONS.get(audience, _AUDIENCE_INSTRUCTIONS["expert"])`.

Put `_AUDIENCE_INSTRUCTIONS` in a shared location — either `src/urika/agents/roles/__init__.py` or a new `src/urika/agents/audience.py` — so all three roles import the same dict.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agents/ -v -k audience`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/urika/agents/
git commit -m "feat: pass audience instructions to presentation, report, and finalizer agents"
```

---

### Task 4: Thread `audience` through orchestrator

**Files:**
- Modify: `src/urika/orchestrator/loop.py:74-318` — `_generate_reports()` and `_generate_presentation()`
- Modify: `src/urika/orchestrator/finalize.py:15-167`
- Modify: `src/urika/orchestrator/loop.py:465+` — `run_experiment()` signature

**Step 1: Add `audience` parameter to `run_experiment()`**

In `loop.py`, add `audience: str = "expert"` to `run_experiment()` signature. Pass it through to `_generate_reports()` and `_generate_presentation()`. Those functions pass it to `role.build_config(..., audience=audience)`.

**Step 2: Add `audience` parameter to `finalize_project()`**

In `finalize.py`, add `audience: str = "expert"` to `finalize_project()` signature. Pass to all three agent `build_config()` calls.

**Step 3: Add `audience` parameter to `run_project()`**

In `meta.py`, add `audience: str = "expert"` to `run_project()` signature. Pass through to `run_experiment()` and `finalize_project()`.

**Step 4: Run orchestrator tests**

Run: `pytest tests/test_orchestrator/ -v`
Expected: ALL PASS (existing tests use defaults)

**Step 5: Commit**

```bash
git add src/urika/orchestrator/
git commit -m "feat: thread audience parameter through orchestrator"
```

---

### Task 5: Add `--audience` flag to CLI commands

**Files:**
- Modify: `src/urika/cli.py` — `run`, `report`, `present`, `finalize` commands
- Modify: `src/urika/repl_commands.py` — `cmd_run`, `cmd_report`, `cmd_present`, `cmd_finalize`

**Step 1: Add `--audience` option to CLI commands**

For each command (`run`, `report`, `present`, `finalize`), add:
```python
@click.option("--audience", type=click.Choice(["novice", "expert"]), default=None,
              help="Output audience level (default: from project config or expert)")
```

If `--audience` is None, read from `urika.toml` preferences. Pass to orchestrator calls.

**Step 2: Add `--audience` parsing to REPL commands**

In `cmd_run`, `cmd_report`, `cmd_present`, `cmd_finalize`, parse `--audience` from args string. Pass to the CLI invocation or direct agent call.

**Step 3: Run CLI and REPL tests**

Run: `pytest tests/test_cli.py tests/test_repl/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/urika/cli.py src/urika/repl_commands.py
git commit -m "feat: add --audience flag to run, report, present, finalize commands"
```

---

### Task 6: Rewrite presentation template CSS for viewport-locked scaling

**Files:**
- Modify: `src/urika/templates/presentation/template.html`
- Modify: `src/urika/templates/presentation/theme-light.css`
- Modify: `src/urika/templates/presentation/theme-dark.css`

**Step 1: Rewrite CSS in template.html**

Replace the entire `<style>` block in `template.html` with viewport-locked CSS:

Key changes:
- All slide content: `display: flex; flex-direction: column; max-height: 100%; overflow: hidden`
- Typography with `clamp()`: h1 `clamp(22px, 3.5vw, 28px)`, h2 `clamp(18px, 2.8vw, 22px)`, body `clamp(12px, 2vw, 15px)`, caption `clamp(10px, 1.5vw, 12px)`, stat `clamp(48px, 9vw, 72px)`
- Figures: `max-height: 55%` of slide (not fixed px), `object-fit: contain`
- Content area: 70% of slide for breathing room
- Font stack: `Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif`
- Subtle transitions: `transition: opacity 0.3s ease`
- No decorative gradients on body slides
- Accent color sparingly: dividers, stat numbers, figure borders
- Slide footer: 10px muted, Urika branding + slide number

**Step 2: Update theme CSS files**

Update `theme-light.css` and `theme-dark.css` to use the same CSS variable names. Ensure dark mode properly inverts all colors.

**Step 3: Manual test**

Open an existing presentation from `~/urika-projects/` in a browser. Resize the window — content should scale, nothing should overflow.

**Step 4: Commit**

```bash
git add src/urika/templates/presentation/
git commit -m "feat: viewport-locked presentation CSS with clamp() typography"
```

---

### Task 7: Add lightbox zoom for presentation figures

**Files:**
- Modify: `src/urika/templates/presentation/template.html`

**Step 1: Add lightbox HTML + JS**

At the end of `template.html` body (before `</body>`), add:

```html
<!-- Lightbox overlay -->
<div id="urika-lightbox" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); z-index:9999; cursor:pointer; align-items:center; justify-content:center;">
  <img id="urika-lightbox-img" style="max-width:90vw; max-height:90vh; object-fit:contain; border-radius:8px;">
  <button style="position:absolute; top:20px; right:20px; background:none; border:none; color:white; font-size:32px; cursor:pointer;">&times;</button>
</div>
```

Add JS (before `</body>`):

```javascript
document.querySelectorAll('.slide-figure img').forEach(img => {
  img.style.cursor = 'pointer';
  img.addEventListener('click', e => {
    e.stopPropagation();
    const lb = document.getElementById('urika-lightbox');
    document.getElementById('urika-lightbox-img').src = img.src;
    lb.style.display = 'flex';
  });
});
document.getElementById('urika-lightbox').addEventListener('click', () => {
  document.getElementById('urika-lightbox').style.display = 'none';
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.getElementById('urika-lightbox').style.display = 'none';
});
```

**Step 2: Add `slide-figure` class to figure rendering**

In `src/urika/core/presentation.py`, ensure `_render_figure_slide()` and `_render_two_col_slide()` wrap images in a `<div class="slide-figure">`.

**Step 3: Manual test**

Open a presentation with figures. Click a figure — lightbox should appear. Click outside or press Escape — lightbox closes.

**Step 4: Commit**

```bash
git add src/urika/templates/presentation/template.html src/urika/core/presentation.py
git commit -m "feat: add lightbox zoom for presentation figures"
```

---

### Task 8: Update presentation agent prompt for layout guidelines

**Files:**
- Modify: `src/urika/agents/roles/prompts/presentation_agent_system.md`

**Step 1: Update layout guidance**

Add/update in the prompt:

```markdown
## Slide Layout Rules

- **Full-width figures by default.** Use the `figure` slide type for ALL figures with multiple panels, small text, legends, or axis labels. The figure gets the full slide width for maximum readability.
- **Two-column (`figure-text`) is opt-in.** Only use for simple single-panel visualizations (bar charts, pie charts) where 2-3 bullets alongside are sufficient to explain the result.
- **Hard content limits per slide:**
  - Maximum 4 bullets per slide
  - Maximum 8 words per bullet
  - Maximum 1 figure per slide
  - If you have more content, split across multiple slides
- **Never crowd a slide.** White space is a feature, not wasted space. When in doubt, add another slide.
```

**Step 2: Commit**

```bash
git add src/urika/agents/roles/prompts/presentation_agent_system.md
git commit -m "feat: update presentation prompt with layout rules and figure guidelines"
```

---

### Task 9: Run full test suite and integration check

**Step 1: Run all tests**

Run: `pytest -v 2>&1 | tail -30`
Expected: ALL PASS

**Step 2: Generate a test presentation**

If possible, run `urika present --audience novice` on an existing project to verify the full pipeline works end-to-end.

**Step 3: Commit any fixes**

---

## Feature 2: Project Dashboard

### Task 10: Add `markdown` dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add markdown to core dependencies**

In `pyproject.toml`, add `"markdown>=3.5"` to the `dependencies` list. This is a lightweight pure-Python package (~100KB).

**Step 2: Verify install**

Run: `pip install -e ".[dev]" && python -c "import markdown; print(markdown.version)"`
Expected: Version prints

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add markdown dependency for dashboard rendering"
```

---

### Task 11: Create dashboard module structure

**Files:**
- Create: `src/urika/dashboard/__init__.py`
- Create: `src/urika/dashboard/server.py`
- Create: `src/urika/dashboard/tree.py`
- Create: `src/urika/dashboard/renderer.py`
- Create: `src/urika/dashboard/templates/__init__.py`
- Create: `src/urika/dashboard/templates/dashboard.html`

**Step 1: Create directory and __init__.py**

```python
# src/urika/dashboard/__init__.py
"""Urika project dashboard — browser-based read-only project viewer."""

from urika.dashboard.server import start_dashboard

__all__ = ["start_dashboard"]
```

**Step 2: Create placeholder files**

Create empty placeholder files for `server.py`, `tree.py`, `renderer.py`, `templates/__init__.py`.

**Step 3: Commit**

```bash
git add src/urika/dashboard/
git commit -m "feat: create dashboard module structure"
```

---

### Task 12: Build curated project tree

**Files:**
- Implement: `src/urika/dashboard/tree.py`
- Test: `tests/test_dashboard/test_tree.py`

**Step 1: Write failing tests**

```python
def test_build_tree_has_experiments(tmp_project_dir):
    """Tree includes experiments section."""
    tree = build_project_tree(tmp_project_dir)
    sections = [s["label"] for s in tree]
    assert "Experiments" in sections

def test_build_tree_experiment_children(tmp_project_dir):
    """Each experiment has labbook, artifacts, presentation children."""
    tree = build_project_tree(tmp_project_dir)
    exp_section = next(s for s in tree if s["label"] == "Experiments")
    if exp_section["children"]:
        exp = exp_section["children"][0]
        child_labels = [c["label"] for c in exp["children"]]
        assert "Labbook" in child_labels
        assert "Artifacts" in child_labels

def test_build_tree_has_projectbook(tmp_project_dir):
    tree = build_project_tree(tmp_project_dir)
    sections = [s["label"] for s in tree]
    assert "Projectbook" in sections

def test_build_tree_has_methods(tmp_project_dir):
    tree = build_project_tree(tmp_project_dir)
    sections = [s["label"] for s in tree]
    assert "Methods" in sections

def test_build_tree_has_criteria(tmp_project_dir):
    tree = build_project_tree(tmp_project_dir)
    sections = [s["label"] for s in tree]
    assert "Criteria" in sections
```

**Step 2: Run tests — verify they fail**

**Step 3: Implement `build_project_tree()`**

Function returns a list of dicts, each representing a tree node:

```python
{"label": "Experiments", "type": "section", "children": [
    {"label": "exp-001-baseline", "type": "experiment", "children": [
        {"label": "Labbook", "type": "folder", "children": [
            {"label": "notes.md", "type": "file", "path": "experiments/exp-001/labbook/notes.md"},
            ...
        ]},
        {"label": "Artifacts", "type": "folder", "children": [
            {"label": "results.png", "type": "image", "path": "experiments/exp-001/artifacts/results.png"},
            ...
        ]},
        {"label": "Presentation", "type": "link", "path": "experiments/exp-001/presentation/index.html"},
    ]},
]}
```

Scans the project directory, builds the curated structure. Only includes files that exist.

**Step 4: Run tests — verify they pass**

**Step 5: Commit**

```bash
git add src/urika/dashboard/tree.py tests/test_dashboard/
git commit -m "feat: build curated project tree for dashboard sidebar"
```

---

### Task 13: Build file renderer

**Files:**
- Implement: `src/urika/dashboard/renderer.py`
- Test: `tests/test_dashboard/test_renderer.py`

**Step 1: Write failing tests**

```python
def test_render_markdown():
    """Markdown renders to HTML."""
    html = render_file_content("# Hello\n\nWorld", "test.md")
    assert "<h1>" in html
    assert "Hello" in html

def test_render_json():
    """JSON renders with syntax highlighting wrapper."""
    html = render_file_content('{"key": "value"}', "test.json")
    assert "key" in html
    assert "<pre" in html

def test_render_python():
    """Python renders with code block."""
    html = render_file_content("def foo():\n    pass", "test.py")
    assert "<pre" in html
    assert "def foo" in html

def test_render_unknown_returns_pre():
    """Unknown file type renders as preformatted text."""
    html = render_file_content("plain text", "test.txt")
    assert "<pre" in html
```

**Step 2: Implement `render_file_content()`**

```python
def render_file_content(content: str, filename: str) -> str:
    """Render file content to HTML based on file extension."""
```

- `.md` → `markdown.markdown(content, extensions=["tables", "fenced_code"])`
- `.json` → parse, pretty-print, wrap in `<pre><code class="language-json">`
- `.py` → wrap in `<pre><code class="language-python">`
- Images → return `<img>` tag (handled differently — by path, not content)
- Other → `<pre>` escaped text

**Step 3: Run tests — verify they pass**

**Step 4: Commit**

```bash
git add src/urika/dashboard/renderer.py tests/test_dashboard/test_renderer.py
git commit -m "feat: file content renderer for dashboard (markdown, JSON, Python)"
```

---

### Task 14: Build dashboard HTML template

**Files:**
- Create: `src/urika/dashboard/templates/dashboard.html`

**Step 1: Write the single-page app HTML**

This is a large file (~400-600 lines) containing all HTML, CSS, and JS inline. Key sections:

**CSS:**
- Three-panel layout: header, sidebar+content, footer
- Urika brand colors (same CSS variables as presentations)
- Dark mode toggle via CSS class on `<body>`
- Sidebar: 250px, resizable, tree with expand/collapse
- Content: flex-grow, max-width 720px centered, comfortable typography
- Footer: stats bar
- Responsive: sidebar collapses to hamburger below 768px
- Modern aesthetic: Inter font, subtle hover animations, smooth transitions

**JS:**
- `fetchTree()` → GET `/api/tree`, render sidebar
- `fetchFile(path)` → GET `/api/file?path=...`, display in content area
- `fetchStats()` → GET `/api/stats`, populate footer
- Tree expand/collapse with localStorage persistence
- Light/dark toggle with localStorage persistence
- Image click → lightbox zoom (same pattern as presentations)
- Presentation links → `window.open()` in new tab

**HTML structure:**
```html
<header>Urika wordmark | project name | dark mode toggle</header>
<main>
  <nav id="sidebar">tree goes here</nav>
  <article id="content">welcome view</article>
</main>
<footer>stats bar</footer>
```

**Step 2: Commit**

```bash
git add src/urika/dashboard/templates/
git commit -m "feat: dashboard single-page HTML template"
```

---

### Task 15: Build HTTP server

**Files:**
- Implement: `src/urika/dashboard/server.py`
- Test: `tests/test_dashboard/test_server.py`

**Step 1: Write failing tests**

```python
import threading
import urllib.request

def test_server_starts_and_serves_root(tmp_project_dir):
    """Server starts and serves the dashboard HTML."""
    from urika.dashboard.server import DashboardServer
    server = DashboardServer(tmp_project_dir, port=0)  # port=0 for random available port
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
        html = resp.read().decode()
        assert "urika" in html.lower()
    finally:
        server.shutdown()

def test_api_tree(tmp_project_dir):
    """API returns project tree JSON."""
    # Similar setup, GET /api/tree, parse JSON, verify structure

def test_api_file_markdown(tmp_project_dir):
    """API renders markdown files as HTML."""
    # Create a .md file in tmp_project_dir, GET /api/file?path=..., verify HTML

def test_api_file_rejects_traversal(tmp_project_dir):
    """Path traversal outside project dir is rejected."""
    # GET /api/file?path=../../etc/passwd, verify 403

def test_api_stats(tmp_project_dir):
    """API returns project stats."""
    # GET /api/stats, verify JSON with expected keys
```

**Step 2: Implement `DashboardServer`**

Subclass `http.server.HTTPServer` with a custom `BaseHTTPRequestHandler`:

```python
class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self._serve_dashboard()
        elif self.path == "/api/tree":
            self._serve_tree()
        elif self.path.startswith("/api/file"):
            self._serve_file()
        elif self.path == "/api/methods":
            self._serve_methods()
        elif self.path == "/api/criteria":
            self._serve_criteria()
        elif self.path == "/api/stats":
            self._serve_stats()
        elif self.path.startswith("/api/raw"):
            self._serve_raw()
        else:
            self.send_error(404)
```

Path validation: resolve the requested path, confirm it's within `project_dir` using `Path.resolve()` and checking `.is_relative_to(project_dir)`.

`start_dashboard()` public function: creates server, opens browser via `webbrowser.open()`, serves until KeyboardInterrupt.

**Step 3: Run tests — verify they pass**

**Step 4: Commit**

```bash
git add src/urika/dashboard/server.py tests/test_dashboard/test_server.py
git commit -m "feat: dashboard HTTP server with API routes and path validation"
```

---

### Task 16: Add `dashboard` CLI command and REPL command

**Files:**
- Modify: `src/urika/cli.py`
- Modify: `src/urika/repl_commands.py`

**Step 1: Add CLI command**

```python
@cli.command("dashboard")
@click.option("--project", "-p", default=None, help="Project name")
@click.option("--port", default=8420, type=int, help="Server port")
def dashboard(project, port):
    """Open the project dashboard in your browser."""
    # Resolve project dir (same pattern as other commands)
    # Call start_dashboard(project_dir, port=port)
```

**Step 2: Add REPL command**

In `repl_commands.py`, add `cmd_dashboard(session, args)`:
- Parse `--port` from args (default 8420)
- Start server in background thread (daemon=True)
- Print URL
- Server auto-stops on REPL exit

Register in the command table.

**Step 3: Run CLI tests**

Run: `pytest tests/test_cli.py tests/test_repl/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/urika/cli.py src/urika/repl_commands.py
git commit -m "feat: add dashboard command to CLI and REPL"
```

---

### Task 17: Final integration test and polish

**Step 1: Run full test suite**

Run: `pytest -v 2>&1 | tail -30`
Expected: ALL PASS

**Step 2: Manual integration test — presentations**

Run `urika present --audience novice` on an existing project. Verify:
- Slides scale to fit browser window at different sizes
- Figures are zoomable (click to lightbox)
- Novice mode adds method explanations
- No content overflows the viewport

**Step 3: Manual integration test — dashboard**

Run `urika dashboard` on an existing project. Verify:
- Browser opens with three-panel layout
- Sidebar shows curated tree with experiments, projectbook, methods, criteria
- Click .md file → rendered in content area
- Click image → displayed with zoom
- Click presentation → opens in new tab
- Click .json → syntax highlighted
- Dark mode toggle works
- Footer shows stats
- Resize browser → responsive behavior

**Step 4: Fix any issues found**

**Step 5: Final commit**

```bash
git commit -m "feat: presentations audience modes + project dashboard — complete"
```

---

## Task Dependency Summary

```
Task 1 (ProjectConfig audience field)
  → Task 2 (prompt placeholders)
  → Task 3 (agent role passthrough)
  → Task 4 (orchestrator threading)
  → Task 5 (CLI/REPL flags)
  → Task 6 (CSS rewrite)          ← independent of 1-5
  → Task 7 (lightbox)             ← depends on 6
  → Task 8 (prompt layout rules)  ← independent
  → Task 9 (integration check)    ← depends on all above

Task 10 (markdown dep)            ← independent
  → Task 11 (module structure)
  → Task 12 (project tree)
  → Task 13 (file renderer)       ← depends on 10
  → Task 14 (HTML template)       ← independent
  → Task 15 (HTTP server)         ← depends on 12, 13, 14
  → Task 16 (CLI/REPL commands)   ← depends on 15
  → Task 17 (integration)         ← depends on all
```

**Parallelizable groups:**
- Tasks 1-5 (audience pipeline) can run in parallel with Tasks 6-8 (presentation layout)
- Tasks 10-14 (dashboard components) can be parallelized: 12, 13, 14 are independent
- Task 15 integrates 12+13+14
