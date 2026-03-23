# Presentation Agent Design

**Date:** 2026-03-22
**Status:** Approved

## Problem

After experiments complete, results are stored in JSON and sparse labbook MDs. Researchers have no easy way to present findings — they must manually create slides from raw data. A lab meeting presentation should be auto-generated after each experiment.

## Design

### Agent Role

New `presentation_agent` — read-only, follows the same pattern as evaluator/suggestion agents. Reads experiment data and outputs structured JSON describing slides. Does not write HTML directly.

- **Allowed tools:** Read, Glob, Grep
- **Max turns:** 10
- **When it runs:** After `_generate_reports` in the orchestrator, on experiment completion
- **Output:** JSON block with slides array

### Slide JSON Structure

The agent outputs structured JSON, not raw HTML:

```json
{
  "title": "Experiment: FOV-Constrained Local Models",
  "subtitle": "DHT Target Selection · 2026-03-22",
  "slides": [
    {
      "type": "bullets",
      "title": "Context",
      "bullets": ["Research question summary", "What we knew before"],
      "notes": "Speaker notes"
    },
    {
      "type": "figure",
      "title": "Model Comparison",
      "figure": "artifacts/model_comparison_bar.png",
      "figure_caption": "Accuracy across all models with LOSO cross-validation",
      "bullets": ["LightGBM outperforms conditional logit by 3.4pp"]
    },
    {
      "type": "stat",
      "title": "Key Result",
      "stat": "99.34%",
      "stat_label": "FOV-constrained prediction accuracy",
      "bullets": ["Beats nearest-distance baseline by 3.6 percentage points"]
    }
  ]
}
```

Three slide types: **bullets** (text), **figure** (image + caption + optional bullets), **stat** (big number hero).

Agent uses as many slides as needed — not fixed. One idea per slide. Prompt instructs:
- Max 4 short bullet points per slide (3-5 words each)
- Prefer figures over text where available
- Define acronyms on first use
- Explain methods in plain language, accessible to non-expert researchers
- Use descriptive figure captions

### HTML Template

Reveal.js based, bundled (no CDN dependency — works offline).

**Ships with Urika at:** `src/urika/templates/presentation/`

```
src/urika/templates/presentation/
  template.html      ← reveal.js + CSS + slide injection point
  reveal.min.js      ← bundled (~200KB)
  reveal.min.css     ← bundled
```

**Two themes:**
- **Light** (default): white background, dark text, blue accents
- **Dark**: dark background, light text, blue accents

Theme set in `urika.toml`:
```toml
[preferences]
presentation_theme = "light"
```

**Design principles:**
- Minimal, clean — lots of white space
- Urika branding: discovery dot icon in corner, blue accent color
- Figures large and centered (60-70% of slide area)
- Stat slides: big number centered, label below

### Rendering Pipeline

```
Agent outputs JSON → Python renderer → HTML file

1. Orchestrator calls presentation_agent after experiment completes
2. Agent reads experiment data, outputs structured JSON
3. Python renderer parses JSON, fills HTML template
4. Copies reveal.js/CSS + referenced figures into presentation/
5. Result: self-contained portable directory
```

**Output structure:**
```
experiments/exp-002/presentation/
  index.html          ← the slide deck (open in browser)
  reveal.min.js       ← bundled
  reveal.min.css      ← bundled
  figures/            ← copies of referenced artifacts
    model_comparison.png
    shap_beeswarm.png
```

Figures are copied (not linked) so the folder is fully portable — zip, email, push to GitHub.

### Orchestrator Integration

```python
complete_session(...)
await _generate_reports(...)       # labbook, README
await _generate_presentation(...)  # NEW
_print_run_summary(...)
```

Optional — skipped if agent fails or `presentation = false` in urika.toml.

### Accessibility Principle (Cross-Cutting)

All agent output throughout the system (not just presentations) should be accessible to researchers who may not be experts in the specific methods:
- Define acronyms on first use
- Explain methods in plain language
- Use descriptive labels, not variable names
- Avoid jargon without context

This applies to: presentation agent, evaluator, suggestion agent, labbook reports, README summaries.

### What Changes

| Component | Change |
|-----------|--------|
| `src/urika/agents/roles/presentation_agent.py` | New agent role (read-only) |
| `src/urika/agents/roles/prompts/presentation_agent_system.md` | Prompt for slide JSON |
| `src/urika/templates/presentation/` | reveal.js, CSS, HTML template |
| `src/urika/core/presentation.py` | Renderer: JSON → HTML, copy figures |
| `src/urika/orchestrator/loop.py` | Call presentation agent after reports |
| `src/urika/core/workspace.py` | Add presentation/ to experiment dirs |
| Agent prompts (all) | Add accessibility/plain-language instructions |
