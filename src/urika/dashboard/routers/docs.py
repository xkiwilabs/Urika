"""Documentation viewer.

Renders ``docs/*.md`` from the repo root as HTML. The docs/ tree
ships with the source checkout but isn't included in pip wheels —
when missing, the page falls back to a friendly empty state instead
of 404'ing.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import urika

router = APIRouter(tags=["docs"])


def _docs_dir() -> Path | None:
    """Find the docs/ tree if it exists.

    Two layouts are supported:

    1. Editable install from a source checkout — docs live at
       ``<repo>/docs`` (four parents up from this file).
    2. Wheel / pip install — ``pyproject.toml`` force-includes the
       repo's ``docs/`` tree at ``urika/_docs`` inside the wheel, so it
       sits next to ``urika/__init__.py``.

    Returns ``None`` only if neither location exists.
    """
    candidate = Path(__file__).resolve().parents[4] / "docs"
    if candidate.is_dir():
        return candidate
    bundled = Path(urika.__file__).resolve().parent / "_docs"
    if bundled.is_dir():
        return bundled
    return None


def _list_docs(docs_dir: Path) -> list[dict]:
    """Return ``[{slug, label, path}]`` for every numbered ``.md`` doc.

    The leading ``NN-`` prefix on filenames orders the list and is
    stripped from the displayed label. ``README.md`` is excluded —
    it's the repo-level overview, not a dashboard doc.
    """
    out = []
    for p in sorted(docs_dir.glob("*.md")):
        slug = p.stem
        if slug.upper() == "README":
            continue
        label = slug
        if len(slug) > 3 and slug[2] == "-" and slug[:2].isdigit():
            label = slug[3:]
        label = label.replace("-", " ").replace("_", " ").capitalize()
        out.append({"slug": slug, "label": label, "path": p})
    return out


@router.get("/docs", response_class=HTMLResponse)
def docs_index(request: Request) -> HTMLResponse:
    docs_dir = _docs_dir()
    if docs_dir is None:
        return request.app.state.templates.TemplateResponse(
            request,
            "docs.html",
            {"docs": [], "current": None, "body_html": None},
        )
    docs = _list_docs(docs_dir)
    if not docs:
        return request.app.state.templates.TemplateResponse(
            request,
            "docs.html",
            {"docs": [], "current": None, "body_html": None},
        )
    # Prefer 01-getting-started; fall back to first numbered doc.
    first = next(
        (d for d in docs if d["slug"] == "01-getting-started"),
        docs[0],
    )
    return RedirectResponse(url=f"/docs/{first['slug']}", status_code=307)


@router.get("/docs/{slug}", response_class=HTMLResponse)
def docs_page(slug: str, request: Request) -> HTMLResponse:
    if "/" in slug or ".." in slug:
        raise HTTPException(status_code=400, detail="Invalid slug")
    docs_dir = _docs_dir()
    if docs_dir is None:
        raise HTTPException(status_code=404, detail="Documentation not available")
    docs = _list_docs(docs_dir)
    current = next((d for d in docs if d["slug"] == slug), None)
    if current is None:
        raise HTTPException(status_code=404, detail="Doc not found")

    from urika.dashboard.render import render_markdown

    body_html = render_markdown(
        current["path"].read_text(encoding="utf-8"),
        base_url="/docs",
    )
    return request.app.state.templates.TemplateResponse(
        request,
        "docs.html",
        {
            "docs": docs,
            "current": current,
            "body_html": body_html,
        },
    )
