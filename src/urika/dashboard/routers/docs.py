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
    """Find the repo's ``docs/`` directory if it exists.

    For an editable install this file lives at
    ``<repo>/src/urika/dashboard/routers/docs.py`` so the repo root is
    four parents up. For a wheel install we instead try the package's
    grandparent directory; in practice ``docs/`` is rarely shipped
    that way and we return ``None``.
    """
    candidate = Path(__file__).resolve().parents[4] / "docs"
    if candidate.is_dir():
        return candidate
    pkg_root = Path(urika.__file__).resolve().parent.parent
    candidate2 = pkg_root.parent / "docs"
    if candidate2.is_dir():
        return candidate2
    return None


def _list_docs(docs_dir: Path) -> list[dict]:
    """Return ``[{slug, label, path}]`` for every ``.md`` doc.

    The leading ``NN-`` prefix on filenames orders the list and is
    stripped from the displayed label; ``README.md`` is relabelled
    as "Overview" so it doesn't appear as a SHOUTING entry.
    """
    out = []
    for p in sorted(docs_dir.glob("*.md")):
        slug = p.stem
        label = slug
        if len(slug) > 3 and slug[2] == "-" and slug[:2].isdigit():
            label = slug[3:]
        label = label.replace("-", " ").replace("_", " ").capitalize()
        if slug.upper() == "README":
            label = "Overview"
        out.append({"slug": slug, "label": label, "path": p})
    return out


@router.get("/docs", response_class=HTMLResponse)
def docs_index(request: Request) -> HTMLResponse:
    docs_dir = _docs_dir()
    if docs_dir is None:
        return request.app.state.templates.TemplateResponse(
            "docs.html",
            {"request": request, "docs": [], "current": None, "body_html": None},
        )
    docs = _list_docs(docs_dir)
    if not docs:
        return request.app.state.templates.TemplateResponse(
            "docs.html",
            {"request": request, "docs": [], "current": None, "body_html": None},
        )
    # Prefer 01-getting-started; fall back to README; fall back to first.
    first = next(
        (d for d in docs if d["slug"] == "01-getting-started"),
        next((d for d in docs if d["slug"].upper() == "README"), docs[0]),
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
        "docs.html",
        {
            "request": request,
            "docs": docs,
            "current": current,
            "body_html": body_html,
        },
    )
