"""HTML page routes — server-rendered Jinja templates."""

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
