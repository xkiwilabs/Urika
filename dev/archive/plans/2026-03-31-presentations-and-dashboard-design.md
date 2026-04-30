# Presentations, Reports & Project Dashboard — Design Document

**Date:** 2026-03-31
**Status:** Approved
**Version:** 0.2.0 targets

Two features for the next release: (1) improved presentations and reports with audience modes, and (2) a browser-based project dashboard.

---

## Feature 1: Presentations & Reports — Audience Modes + Layout Fixes

### 1.1 Audience System

Two tiers: **expert** (default, current behavior) and **novice**. Novice adds explanation; expert stays as-is. Current output is expert-level.

**Configuration:**

Default in `urika.toml`:
```toml
[preferences]
audience = "expert"    # or "novice"
```

Overridable per-command:
- CLI: `urika present --audience novice`, `urika report --audience novice`
- REPL: `/present --audience novice`, `/report --audience novice`

**Implementation:**

The audience level is injected into the presentation and report agent system prompts as a variable `{audience}` with a conditional prompt block appended based on the value:

- **expert**: "Assume domain expertise. Use technical terminology freely. Focus on results and methodology."
- **novice**: "Explain every method in plain language as if the reader has no statistics or ML background. For each method or model, add a 'What this means' paragraph. Define all technical terms. Explain why each approach was chosen. Walk through results step by step. Presentations should include 1-2 extra slides per method explaining the approach conceptually."

The agents handle the output differences — no template changes needed for audience mode, just richer prompt instructions that produce more content for novice.

**Affected agent prompts:**
- `presentation_agent_system.md` — add `{audience_instructions}` block
- `report_agent_system.md` — add `{audience_instructions}` block
- `finalizer_system.md` — findings.json `answer` field adapts to audience

**Affected code:**
- `src/urika/agents/roles/presentation_agent.py` — pass `audience` to prompt variables
- `src/urika/agents/roles/report_agent.py` — pass `audience` to prompt variables
- `src/urika/agents/roles/finalizer.py` — pass `audience` to prompt variables
- `src/urika/orchestrator/loop.py` — read audience from config, pass to agent builders
- `src/urika/orchestrator/finalize.py` — same
- `src/urika/cli.py` — add `--audience` option to `present`, `report`, `finalize`, `run` commands
- `src/urika/repl_commands.py` — add `--audience` parsing to `/present`, `/report`, `/finalize`, `/run`
- `src/urika/core/models.py` — add `audience` field to ProjectConfig (optional, default "expert")

### 1.2 Presentation Layout — Viewport-Locked, Scalable

**Core constraint:** Nothing falls below the fold. Every slide's content fits within the visible browser window at any reasonable resolution (1024x768 through 4K) and when resizing. No scrolling, no overflow.

**CSS strategy:**

1. **Flexbox containment:** All slide content uses `display: flex; flex-direction: column` with `overflow: hidden` and `max-height: 100%`. Text and images shrink proportionally rather than overflow.

2. **Percentage-based figure sizing:** Figures use `max-height: 55%` of slide height (within the reveal.js viewport context) instead of fixed pixel values like 340px/380px. This scales naturally with viewport.

3. **`clamp()` typography:** Font sizes use CSS `clamp()` functions so text scales down gracefully if the viewport is small, rather than overflowing:
   - h1: `clamp(22px, 3.5vw, 28px)`
   - h2: `clamp(18px, 2.8vw, 22px)`
   - body/li: `clamp(12px, 2vw, 15px)`
   - caption: `clamp(10px, 1.5vw, 12px)`
   - stat number: `clamp(48px, 9vw, 72px)`

4. **Content auto-shrink:** If a bullet list exceeds available space, `flex-shrink` and `font-size` scaling via container queries prevent overflow. Last resort: `overflow: hidden` clips rather than overflows.

**Layout changes:**

1. **Full-width figures as default:** The `figure` slide type (full-width) becomes the default recommendation. `figure-text` (two-column) is opt-in for simple visualizations only.

2. **Agent prompt update:** "Use full-width figure slides for all figures with multiple panels, small text, legends, or axis labels. Use figure-text only for simple single-panel visualizations like bar charts or pie charts where the key message can be summarized in 2-3 bullets alongside."

3. **Hard limits in prompt:** Max 4 bullets per slide, max 8 words per bullet, max 1 figure per slide. "If you have more content, split across slides."

**Zoomable figures:**

Add a lightbox overlay to `template.html`:
- Click any figure → opens full-size in a dark modal overlay
- Close on click outside, Escape key, or X button
- Pure CSS + ~20 lines of JS in template — no dependencies
- `cursor: pointer` on images as visual affordance

**Modern professional aesthetic:**

- Clean sans-serif font stack: `Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif`
- Generous whitespace — content occupies ~70% of slide area
- Subtle fade transitions between slides
- Accent color (`--u-blue`) used sparingly — section dividers, stat numbers, figure borders
- Consistent visual rhythm — title always same position, content bounds fixed
- No decorative clutter — no gradients on body slides, no text shadows
- Slide footer: subtle Urika branding + slide number, 10px, muted

**Files to modify:**
- `src/urika/templates/presentation/template.html` — full CSS rewrite + lightbox JS
- `src/urika/templates/presentation/theme-light.css` — update to match new variables
- `src/urika/templates/presentation/theme-dark.css` — update to match new variables
- `src/urika/core/presentation.py` — update slide rendering HTML for new CSS classes
- `src/urika/agents/roles/prompts/presentation_agent_system.md` — layout guidelines, audience block

---

## Feature 2: Project Dashboard

### 2.1 Architecture

**Lightweight Python server** using `http.server` from stdlib. Zero new dependencies.

- `urika dashboard` (CLI) or `/dashboard` (REPL) starts a local server on `localhost:8420`
- Opens default browser automatically
- Serves until Ctrl+C (CLI) or runs in background thread (REPL)
- Project-scoped — one project per dashboard instance

**Markdown rendering:** Use Python's `markdown` library (add as lightweight core dependency, ~100KB) for server-side `.md` → HTML conversion. Alternatively, use a JS markdown renderer client-side (e.g., marked.js, ~40KB bundled) to avoid the dependency — decision deferred to implementation.

### 2.2 Layout

Three-panel layout: header, sidebar + content, footer.

```
┌──────────────────────────────────────────────────────┐
│  URIKA   project-name                    ○ Light/Dark │
├─────────────┬────────────────────────────────────────┤
│             │                                        │
│  ▸ Experiments  │     Main content area               │
│    ▸ exp-001    │                                     │
│      labbook    │     - Rendered markdown              │
│      artifacts  │     - Image viewer (zoom)            │
│      presentation│    - JSON syntax-highlighted        │
│    ▸ exp-002    │     - Criteria/metrics tables        │
│                 │     - Welcome/overview on load       │
│  ▸ Projectbook  │                                     │
│    findings     │                                     │
│    reports      │                                     │
│    presentation │                                     │
│                 │                                     │
│  ▸ Methods      │                                     │
│  ▸ Criteria     │                                     │
│  ▸ Data Profile │                                     │
│                 │                                     │
├─────────────┴────────────────────────────────────────┤
│  Experiments: 5 │ Methods: 12 │ Best: r²=0.73         │
└──────────────────────────────────────────────────────┘
```

### 2.3 Header

- Urika wordmark (left) — styled text, no image dependency
- Project name (center-left)
- Light/dark mode toggle (right) — switches CSS variables, persists in localStorage

### 2.4 Sidebar (left, ~250px, resizable)

Curated tree — not raw filesystem. Purpose-organized sections:

**Experiments** (expandable per experiment):
- Labbook: notes.md, summary.md, narrative.md
- Artifacts: all images (.png, .jpg, .svg, .gif)
- Presentation: link (opens in new tab)
- Suggestions: advisor suggestions if present

**Projectbook**:
- key-findings.md
- results-summary.md
- final-report.md
- Final presentation (opens in new tab)
- figures/ (all project-level figures)

**Methods**:
- List from methods.json with status badges (tested/failed/best)
- Click shows method card with metrics

**Criteria**:
- Current criteria version with thresholds
- Pass/fail indicators per metric

**Data Profile**:
- Dataset summary from urika.toml
- File list, row/column counts from scan results

**Tree behavior:**
- Expand/collapse with arrow icons
- Indent levels for hierarchy
- Subtle hover highlight
- Active item highlighted with accent color
- Sections remember expand/collapse state in localStorage

### 2.5 Main Content Area

Click any item in the sidebar to display in the main area:

| File type | Rendering |
|-----------|-----------|
| `.md` | Rendered HTML with proper typography, heading anchors |
| `.png`, `.jpg`, `.svg`, `.gif` | Displayed centered with click-to-zoom lightbox |
| `.json` | Syntax-highlighted, formatted with collapsible sections |
| `.py` | Syntax-highlighted code view |
| Presentations | Opens in new browser tab |
| Methods (from methods.json) | Card layout: name, status badge, metrics table, script path |
| Criteria | Formatted table with threshold bars and pass/fail |

**Content area styling:**
- Max reading width ~720px, centered
- Comfortable line-height (1.7)
- Code blocks with monospace font, subtle background
- Tables with alternating row colors
- Images with rounded corners and subtle shadow (matching presentation style)

**Welcome view (on load):**
- Project name and research question
- Quick stats: experiments run, methods tried, best result
- Links to key files: latest report, final presentation, criteria status

### 2.6 Footer Bar

Single-line project stats:
- Experiment count
- Method count
- Best metric result (name + value)
- Project mode (exploratory/confirmatory/pipeline)

### 2.7 Styling

**Urika brand colors** — same palette as presentations:
```css
--u-blue: #2563eb
--u-accent: #3b82f6
--u-text: #1e293b
--u-muted: #64748b
--u-border: #e2e8f0
--u-bg: #f8fafc
```

**Dark mode:** Toggle switches CSS variables. Same dark palette as presentation dark theme.

**Modern aesthetic:**
- System font stack (Inter if available)
- Sidebar: subtle hover highlights, smooth expand/collapse animations
- Content: comfortable reading width, generous padding
- Smooth transitions on all interactions (200ms ease)
- Responsive: sidebar collapses to hamburger menu below 768px

### 2.8 Server Implementation

Single Python `http.server.HTTPServer` subclass with custom request handler.

**Routes:**

| Route | Returns |
|-------|---------|
| `/` | Dashboard HTML (single-page, all JS/CSS inline or bundled in one file) |
| `/api/tree` | JSON — curated project tree structure |
| `/api/file?path=<relative>` | Rendered markdown HTML, raw image, syntax-highlighted JSON/Python |
| `/api/methods` | JSON — methods.json content |
| `/api/criteria` | JSON — criteria.json content |
| `/api/stats` | JSON — experiment count, method count, best metrics |
| `/api/raw?path=<relative>` | Raw file content (for images, downloads) |

**Security:**
- Path parameter validated against project directory — no traversal outside it
- Localhost binding only (127.0.0.1)
- No write endpoints

### 2.9 New Files

```
src/urika/
  dashboard/
    __init__.py          — public API: start_dashboard(project_dir, port=8420)
    server.py            — HTTPServer subclass, request handler, routing
    tree.py              — Build curated project tree from filesystem
    renderer.py          — Markdown→HTML, JSON syntax highlighting, code highlighting
    templates/
      __init__.py
      dashboard.html     — Single-page app (HTML + CSS + JS, all inline)
```

### 2.10 CLI / REPL Integration

**CLI:** `urika dashboard [--project NAME] [--port 8420]`
- Starts server, opens browser, blocks until Ctrl+C

**REPL:** `/dashboard [--port 8420]`
- Starts server in background thread
- Prints URL
- Server stops on REPL exit

### 2.11 What It Does NOT Do

- No editing — strictly read-only
- No live experiment monitoring — snapshot of current state (browser refresh to update)
- No authentication — localhost only
- No file upload or project management
- No experiment execution or agent interaction

---

## Summary of Changes

### New dependencies
- `markdown` (lightweight, for server-side .md rendering) — OR bundle a JS renderer client-side (decision deferred)

### New files
- `src/urika/dashboard/` — server, tree builder, renderer, template (5 files)
- Updated presentation template and CSS (3 files)

### Modified files
- Agent prompts: presentation, report, finalizer (3 prompt .md files)
- Agent roles: presentation, report, finalizer (3 .py files)
- Orchestrator: loop.py, finalize.py (audience passthrough)
- CLI: add `dashboard` command, `--audience` flag on existing commands
- REPL: add `/dashboard` command, `--audience` flag on existing commands
- Models: add `audience` to ProjectConfig
- pyproject.toml: add `markdown` dependency if needed
