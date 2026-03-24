# Presentation Template Overhaul

## Current Problems

1. **Text overflow** — content runs below the browser window, gets cut off. No overflow protection.
2. **Font sizes too large** — h1 1.5em, h2 1.1em on top of reveal.js base sizing = too big.
3. **Final presentation figures broken** — figures at `projectbook/figures/` but presentation at `projectbook/final-presentation/` so relative path `figures/` doesn't resolve.
4. **Boring design** — minimal styling, no visual hierarchy, slides all look the same.
5. **No responsive content fitting** — long bullet lists overflow, tables don't fit.

## Fix Plan

### 1. Font sizing — smaller, responsive

```css
.reveal h1 { font-size: 1.3em; }
.reveal h2 { font-size: 0.95em; margin-bottom: 0.3em; }
.reveal ul, .reveal ol { font-size: 0.55em; line-height: 1.5; }
.reveal p { font-size: 0.55em; }
.reveal li { margin-bottom: 0.3em; }
```

### 2. Overflow protection — content must fit the slide

```css
.reveal section {
    overflow: hidden;
    max-height: 100%;
    box-sizing: border-box;
    padding: 20px 40px;
}
/* Auto-shrink if too much content */
.reveal .slides section {
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: center;
}
```

Plus reveal.js config:
```javascript
Reveal.initialize({
    width: 960,
    height: 700,        // taller slides
    margin: 0.04,       // less margin
    minScale: 0.1,      // allow more shrinking
    maxScale: 1.5,
    center: true,
});
```

### 3. Figure path fix for final presentations

In `orchestrator/finalize.py`, when rendering the final presentation, copy figures from `projectbook/figures/` into the presentation directory `projectbook/final-presentation/figures/`.

Or: the `render_presentation` function already handles figure copying from experiment dirs. For the final presentation, pass the `projectbook` as the experiment_dir so it finds `figures/` there.

### 4. Visual design improvements

**Title slide:**
- Larger title, gradient accent line below
- Subtitle in lighter weight
- Project name and date at bottom

**Content slides:**
- Left-aligned content with colored accent bar on the left edge
- Slide title with bottom border
- Proper spacing between elements

**Stat slides:**
- Big number with subtle background circle
- Cleaner label typography

**Figure slides:**
- Larger image area (70% width)
- Caption below in small italic
- Optional dark background for better contrast

**Two-column slides:**
- Equal columns with subtle divider
- Image fills its column properly

**Transitions:**
- Keep fade (clean)
- Add subtle slide-in for figures

**Color scheme:**
- Primary: Urika blue (#2563eb)
- Accent: lighter blue (#3b82f6)
- Text: dark grey (#1e293b) not black
- Muted: (#64748b) for labels/captions
- Background: clean white (#fafafa) not pure white
- Dark theme: dark bg (#0f172a), light text

### 5. Slide footer

Add a subtle footer to each slide:
- Left: Urika brand mark
- Center: slide title (dim)
- Right: slide number / total

## Implementation

Files to modify:
- `src/urika/templates/presentation/template.html` — CSS + JS overhaul
- `src/urika/templates/presentation/theme-light.css` — light theme colors
- `src/urika/templates/presentation/theme-dark.css` — dark theme colors
- `src/urika/core/presentation.py` — fix figure path for final presentations
- `src/urika/orchestrator/finalize.py` — copy figures to presentation dir
