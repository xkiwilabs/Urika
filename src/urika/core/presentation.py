"""Render slide JSON into a reveal.js HTML presentation."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any


def parse_slide_json(text: str) -> dict[str, Any] | None:
    """Extract slide deck JSON from agent output text."""
    pattern = re.compile(r"```json\s*\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(text):
        raw = match.group(1).strip()
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict) and "slides" in parsed:
            return parsed
    return None


def render_presentation(
    slide_data: dict[str, Any],
    output_dir: Path,
    *,
    theme: str = "light",
    experiment_dir: Path | None = None,
    project_dir: Path | None = None,
) -> Path:
    """Render slide data into an HTML presentation.

    Args:
        slide_data: Parsed slide JSON with title, subtitle, slides array.
        output_dir: Where to write the presentation files.
        theme: "light" or "dark".
        experiment_dir: Experiment directory for resolving figure paths
            (experiment-level decks).
        project_dir: Project root for resolving figures that live across many
            ``experiments/<id>/artifacts/`` dirs (project-level decks).

    Returns:
        Path to the output directory.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"

    # Copy reveal.js template files
    template_dir = Path(__file__).parent.parent / "templates" / "presentation"
    for f in (
        "reveal.min.js",
        "reveal.css",
        "theme-light.css",
        "theme-dark.css",
        # RevealNotes plugin: notes.js registers the S-key handler;
        # notes.html is the popup window's template (the plugin opens
        # it via window.open at a relative URL, so it must live next
        # to the deck).
        "notes.js",
        "notes.html",
    ):
        src = template_dir / f
        if src.exists():
            shutil.copy2(src, output_dir / f)

    # Build slides HTML
    slides_html = _render_title_slide(
        slide_data.get("title", ""),
        slide_data.get("subtitle", ""),
    )
    for slide in slide_data.get("slides", []):
        slide_type = slide.get("type", "bullets")
        if slide_type == "stat":
            slides_html += _render_stat_slide(slide)
        elif slide_type == "figure":
            slides_html += _render_figure_slide(
                slide, figures_dir, experiment_dir, project_dir
            )
        elif slide_type == "figure-text":
            slides_html += _render_two_col_slide(
                slide, figures_dir, experiment_dir, project_dir
            )
        elif slide_type == "explainer":
            slides_html += _render_explainer_slide(slide)
        else:
            slides_html += _render_bullets_slide(slide)

    # Read template and fill
    template_path = template_dir / "template.html"
    if template_path.exists():
        html = template_path.read_text(encoding="utf-8")
    else:
        html = _fallback_template()

    theme_css = f"theme-{theme}.css"
    html = html.replace("{{TITLE}}", slide_data.get("title", "Presentation"))
    html = html.replace("{{SUBTITLE}}", slide_data.get("subtitle", ""))
    html = html.replace("{{THEME_CSS}}", theme_css)
    html = html.replace("{{SLIDES_HTML}}", slides_html)

    from urika.core.report_writer import write_versioned

    write_versioned(output_dir / "index.html", html)
    return output_dir


def _render_title_slide(title: str, subtitle: str) -> str:
    """Render the title slide.

    Includes a small keyboard-shortcut hint reminding the viewer that
    reveal.js exposes ``S`` (speaker notes), ``F`` (fullscreen), and
    ``?`` (help overlay). Only on slide 1 — gets out of the way once
    the user has seen it.
    """
    sub = f'<p class="subtitle">{_escape(subtitle)}</p>' if subtitle else ""
    hint = (
        '<aside class="urika-keys-hint">'
        "Press <kbd>S</kbd> for speaker notes "
        "· <kbd>F</kbd> fullscreen "
        "· <kbd>?</kbd> help"
        "</aside>"
    )
    return f"""
            <section class="title-slide">
                <h1>{_escape(title)}</h1>
                {sub}
                {hint}
            </section>
"""


def _render_bullets_slide(slide: dict[str, Any]) -> str:
    """Render a bullets slide."""
    title = slide.get("title", "")
    bullets = slide.get("bullets", [])
    items = "\n".join(f"                    <li>{_escape(b)}</li>" for b in bullets)
    return f"""
            <section>
                <h2>{_escape(title)}</h2>
                <ul>
{items}
                </ul>
                {_render_notes(slide)}
            </section>
"""


def _render_stat_slide(slide: dict[str, Any]) -> str:
    """Render a big-number stat slide."""
    title = slide.get("title", "")
    stat = slide.get("stat", "")
    label = slide.get("stat_label", "")
    bullets = slide.get("bullets", [])
    items = ""
    if bullets:
        items_html = "\n".join(
            f"                    <li>{_escape(b)}</li>" for b in bullets
        )
        items = f"<ul>{items_html}</ul>"
    return f"""
            <section class="slide-stat">
                <h2>{_escape(title)}</h2>
                <div class="big-number">{_escape(stat)}</div>
                <div class="stat-label">{_escape(label)}</div>
                {items}
                {_render_notes(slide)}
            </section>
"""


def _is_within(child: Path, parent: Path) -> bool:
    """True if ``child`` resolves to a path inside ``parent`` (or equal)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _resolve_figure_source(
    figure_path: str,
    experiment_dir: Path | None,
    project_dir: Path | None,
) -> tuple[Path, str] | None:
    """Resolve a slide's figure reference to (source_path, dest_name).

    Returns ``None`` if no safe source can be found. The dest name is chosen
    to be collision-free across experiments so two experiments with the same
    figure basename don't clobber each other in the shared ``figures/`` dir.

    A resolved source is rejected (treated as missing) if it escapes the
    boundary dir it was resolved under — this stops an agent-supplied path
    like ``../../etc/passwd`` from copying a file into a shareable deck.
    """
    if not figure_path:
        return None
    basename = Path(figure_path).name

    # 1. Experiment-level: unchanged behavior — dest name is the basename.
    if experiment_dir:
        src = experiment_dir / figure_path
        if src.is_file() and _is_within(src, experiment_dir):
            return src, basename

    # 2. Project-level resolution across many experiments.
    if project_dir:
        # 2a. Project-relative path. Two layouts are accepted: a path already
        # rooted at the project (projectbook/figures/x.png) and one rooted at
        # an experiment id (exp-001/artifacts/x.png) which lives under
        # experiments/. Trying both keeps same-basename figures from different
        # experiments distinct via their experiment-id prefix.
        for base in (project_dir, project_dir / "experiments"):
            src = base / figure_path
            if src.is_file() and _is_within(src, project_dir):
                return src, _project_dest_name(src, project_dir, basename)

        # 2b. Basename search across experiment artifacts (deterministic).
        experiments_dir = project_dir / "experiments"
        if experiments_dir.is_dir():
            for exp_dir in sorted(experiments_dir.iterdir()):
                candidate = exp_dir / "artifacts" / basename
                if candidate.is_file() and _is_within(candidate, project_dir):
                    return candidate, _project_dest_name(
                        candidate, project_dir, basename
                    )

        # 2c. Then the collected projectbook/figures dir (dest = basename).
        candidate = project_dir / "projectbook" / "figures" / basename
        if candidate.is_file() and _is_within(candidate, project_dir):
            return candidate, basename

    return None


def _project_dest_name(src: Path, project_dir: Path, basename: str) -> str:
    """Collision-free destination name for a project-level figure source.

    Figures under ``experiments/<exp>/artifacts/`` get an ``<exp>_`` prefix so
    two experiments sharing a basename land as distinct files. Anything else
    (e.g. projectbook/figures) keeps its basename.
    """
    try:
        rel = src.resolve().relative_to((project_dir / "experiments").resolve())
        exp_name = rel.parts[0]
        return f"{exp_name}_{basename}"
    except (ValueError, OSError):
        return basename


def _copy_figure_or_placeholder(
    figure_path: str,
    figures_dir: Path,
    experiment_dir: Path | None,
    caption: str,
    project_dir: Path | None = None,
) -> str:
    """Try to copy the figure to the output; return an <img> tag if it landed,
    or a visible ``figure-missing`` placeholder if no source can be resolved.

    The placeholder shows the intended path so the presenter can see exactly
    which reference failed — silently emitting a broken <img> used to mean
    the problem only became obvious when the deck was opened.

    This function controls BOTH the copy and the emitted ``<img src>`` so they
    always agree on the filename.
    """
    resolved = _resolve_figure_source(figure_path, experiment_dir, project_dir)
    if resolved is not None:
        src, dest_name = resolved
        figures_dir.mkdir(exist_ok=True)
        shutil.copy2(src, figures_dir / dest_name)
        return f'<img src="figures/{_escape(dest_name)}" alt="{_escape(caption)}">'
    return f'<div class="figure-missing">Figure missing: {_escape(figure_path)}</div>'


def _render_figure_slide(
    slide: dict[str, Any],
    figures_dir: Path,
    experiment_dir: Path | None,
    project_dir: Path | None = None,
) -> str:
    """Render a figure slide, copying the image to the output."""
    title = slide.get("title", "")
    figure_path = slide.get("figure", "")
    caption = slide.get("figure_caption", "")
    bullets = slide.get("bullets", [])

    fig_html = _copy_figure_or_placeholder(
        figure_path, figures_dir, experiment_dir, caption, project_dir
    )
    cap = f'<p class="caption">{_escape(caption)}</p>' if caption else ""
    items = ""
    if bullets:
        items_html = "\n".join(
            f"                    <li>{_escape(b)}</li>" for b in bullets
        )
        items = f"<ul>{items_html}</ul>"

    return f"""
            <section class="slide-figure">
                <h2>{_escape(title)}</h2>
                <div class="slide-figure">
                    {fig_html}
                    {cap}
                </div>
                {items}
                {_render_notes(slide)}
            </section>
"""


def _render_two_col_slide(
    slide: dict[str, Any],
    figures_dir: Path,
    experiment_dir: Path | None,
    project_dir: Path | None = None,
) -> str:
    """Render a two-column slide: figure left, text right."""
    title = slide.get("title", "")
    figure_path = slide.get("figure", "")
    caption = slide.get("figure_caption", "")
    bullets = slide.get("bullets", [])
    bottom = slide.get("bottom_text", "")

    fig_html = _copy_figure_or_placeholder(
        figure_path, figures_dir, experiment_dir, caption, project_dir
    )
    cap = f'<p class="caption">{_escape(caption)}</p>' if caption else ""
    items = ""
    if bullets:
        items_html = "\n".join(
            f"                        <li>{_escape(b)}</li>" for b in bullets
        )
        items = f"<ul>{items_html}</ul>"
    bot = f'<p class="bottom-text">{_escape(bottom)}</p>' if bottom else ""

    return f"""
            <section class="slide-two-col">
                <h2>{_escape(title)}</h2>
                <div class="columns">
                    <div class="col-figure slide-figure">
                        {fig_html}
                        {cap}
                    </div>
                    <div class="col-text">
                        {items}
                    </div>
                </div>
                {bot}
                {_render_notes(slide)}
            </section>
"""


def _render_explainer_slide(slide: dict[str, Any]) -> str:
    """Render an explainer slide: a lead sentence plus a short body paragraph.

    Intended for method-introduction slides that orient the audience before
    showing results.
    """
    title = slide.get("title", "")
    lead = slide.get("lead", "")
    body = slide.get("body", "")
    return f"""
            <section class="slide-explainer">
                <h2>{_escape(title)}</h2>
                <p class="lead">{_escape(lead)}</p>
                <p class="body">{_escape(body)}</p>
                {_render_notes(slide)}
            </section>
"""


def _render_notes(slide: dict[str, Any]) -> str:
    """Render reveal.js speaker notes aside, if the slide has a notes field."""
    notes = slide.get("notes", "")
    if not notes:
        return ""
    return f'<aside class="notes">{_escape(notes)}</aside>'


def _escape(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _fallback_template() -> str:
    """Minimal fallback template if reveal.js files not found."""
    return """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{TITLE}}</title>
    <style>
        body { font-family: sans-serif; max-width: 900px; margin: 0 auto; padding: 2em; }
        section { page-break-after: always; margin: 2em 0; padding: 2em; border: 1px solid #ddd; border-radius: 8px; }
        h1, h2 { color: #2563eb; }
        img { max-width: 100%; }
        .big-number { font-size: 4em; font-weight: bold; color: #2563eb; }
        .stat-label { font-size: 1.2em; color: #666; }
        .caption { font-size: 0.8em; color: #888; font-style: italic; }
    </style>
</head>
<body>
{{SLIDES_HTML}}
</body>
</html>"""
