"""HTML page routes — server-rendered Jinja templates."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from urika.core.experiment import list_experiments, load_experiment
from urika.core.models import ExperimentConfig
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry
from urika.dashboard_v2.projects import (
    list_project_summaries,
    load_project_summary,
)

router = APIRouter(tags=["pages"])


def _experiment_runs_summary(
    exp_dir: Path, exp: ExperimentConfig
) -> tuple[int, str]:
    """Return ``(runs_count, last_touched_iso)`` for an experiment."""
    progress_path = exp_dir / "progress.json"
    if not progress_path.exists():
        return 0, exp.created_at
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, exp.created_at
    runs = progress.get("runs", []) or []
    if not runs:
        return 0, exp.created_at
    timestamps = [r.get("timestamp", "") for r in runs if r.get("timestamp")]
    last = max(timestamps) if timestamps else exp.created_at
    return len(runs), last


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


@router.get("/projects/{name}/experiments", response_class=HTMLResponse)
def project_experiments(request: Request, name: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    experiments = list_experiments(summary.path)
    rows = []
    for exp in experiments:
        exp_dir = summary.path / "experiments" / exp.experiment_id
        runs_count, last_touched = _experiment_runs_summary(exp_dir, exp)
        rows.append(
            {
                "experiment_id": exp.experiment_id,
                "name": exp.name,
                "status": exp.status,
                "runs_count": runs_count,
                "last_touched": last_touched,
            }
        )
    # Newest-first for display (list_experiments returns oldest-first by ID).
    rows.reverse()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "experiments.html",
        {
            "request": request,
            "project": summary,
            "experiments": rows,
        },
    )


@router.get(
    "/projects/{name}/experiments/{exp_id}", response_class=HTMLResponse
)
def experiment_detail(
    request: Request, name: str, exp_id: str
) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    try:
        exp = load_experiment(summary.path, exp_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Unknown experiment"
        ) from exc
    progress = load_progress(summary.path, exp_id)
    runs = progress.get("runs", []) or []

    exp_dir = summary.path / "experiments" / exp_id
    has_report = (exp_dir / "report.md").exists()
    has_presentation = (exp_dir / "presentation.html").exists()
    has_log = (exp_dir / "run.log").exists()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "experiment_detail.html",
        {
            "request": request,
            "project": summary,
            "experiment": exp,
            "runs": runs,
            "has_report": has_report,
            "has_presentation": has_presentation,
            "has_log": has_log,
        },
    )
