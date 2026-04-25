"""HTML page routes — server-rendered Jinja templates."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from urika.core.experiment import list_experiments
from urika.core.registry import ProjectRegistry
from urika.dashboard_v2.projects import (
    list_project_summaries,
    load_project_summary,
)

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


@router.get("/projects/{name}", response_class=HTMLResponse)
def project_home(request: Request, name: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    recent = list_experiments(summary.path)[-5:][::-1]
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "project_home.html",
        {
            "request": request,
            "project": summary,
            "recent_experiments": recent,
        },
    )
