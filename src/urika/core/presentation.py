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
) -> Path:
    """Render slide data into an HTML presentation.

    Args:
        slide_data: Parsed slide JSON with title, subtitle, slides array.
        output_dir: Where to write the presentation files.
        theme: "light" or "dark".
        experiment_dir: Experiment directory for resolving figure paths.

    Returns:
        Path to the output directory.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"

    # Copy reveal.js template files
    template_dir = Path(__file__).parent.parent / "templates" / "presentation"
    for f in ("reveal.min.js", "reveal.css", "theme-light.css", "theme-dark.css"):
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
            slides_html += _render_figure_slide(slide, figures_dir, experiment_dir)
        elif slide_type == "figure-text":
            slides_html += _render_two_col_slide(slide, figures_dir, experiment_dir)
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
    """Render the title slide."""
    sub = f'<p class="subtitle">{_escape(subtitle)}</p>' if subtitle else ""
    return f"""
            <section class="title-slide">
                <h1>{_escape(title)}</h1>
                {sub}
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


def _copy_figure_or_placeholder(
    figure_path: str,
    figures_dir: Path,
    experiment_dir: Path | None,
    caption: str,
) -> str:
    """Try to copy the figure to the output; return an <img> tag if it landed,
    or a visible ``figure-missing`` placeholder if the source doesn't exist.

    The placeholder shows the intended path so the presenter can see exactly
    which reference failed — silently emitting a broken <img> used to mean
    the problem only became obvious when the deck was opened.
    """
    fig_name = Path(figure_path).name
    if experiment_dir and figure_path:
        src = experiment_dir / figure_path
        if src.exists():
            figures_dir.mkdir(exist_ok=True)
            shutil.copy2(src, figures_dir / fig_name)
            return f'<img src="figures/{_escape(fig_name)}" alt="{_escape(caption)}">'
    return (
        f'<div class="figure-missing">'
        f'Figure missing: {_escape(figure_path)}'
        f'</div>'
    )


def _render_figure_slide(
    slide: dict[str, Any],
    figures_dir: Path,
    experiment_dir: Path | None,
) -> str:
    """Render a figure slide, copying the image to the output."""
    title = slide.get("title", "")
    figure_path = slide.get("figure", "")
    caption = slide.get("figure_caption", "")
    bullets = slide.get("bullets", [])

    fig_html = _copy_figure_or_placeholder(
        figure_path, figures_dir, experiment_dir, caption
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
) -> str:
    """Render a two-column slide: figure left, text right."""
    title = slide.get("title", "")
    figure_path = slide.get("figure", "")
    caption = slide.get("figure_caption", "")
    bullets = slide.get("bullets", [])
    bottom = slide.get("bottom_text", "")

    fig_html = _copy_figure_or_placeholder(
        figure_path, figures_dir, experiment_dir, caption
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
