"""HTML page routes — server-rendered Jinja templates."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from urika.core.experiment import list_experiments, load_experiment
from urika.core.method_registry import load_methods
from urika.core.models import VALID_AUDIENCES, VALID_MODES, ExperimentConfig
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry
from urika.core.settings import load_settings
from urika.dashboard_v2.projects import (
    list_project_summaries,
    load_project_summary,
)
from urika.knowledge.store import KnowledgeStore

VALID_PRIVACY_MODES = ["private", "open", "university"]

router = APIRouter(tags=["pages"])


def _active_experiment(project_path: Path) -> str | None:
    """Return the experiment_id of the currently running experiment, if any.

    A run is considered active when any subdirectory under
    ``<project>/experiments/`` contains a ``.lock`` file.
    """
    exp_root = project_path / "experiments"
    if not exp_root.exists():
        return None
    for exp_dir in sorted(exp_root.iterdir(), reverse=True):
        if exp_dir.is_dir() and (exp_dir / ".lock").exists():
            return exp_dir.name
    return None


def _experiment_runs_summary(exp_dir: Path, exp: ExperimentConfig) -> tuple[int, str]:
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


@router.get("/projects/{name}/methods", response_class=HTMLResponse)
def project_methods(request: Request, name: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    methods = load_methods(summary.path)
    # Collect the union of metric keys for the sort dropdown.
    metric_keys = sorted({k for m in methods for k in m.get("metrics", {})})
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "methods.html",
        {
            "request": request,
            "project": summary,
            "methods": methods,
            "metric_keys": metric_keys,
        },
    )


@router.get("/settings", response_class=HTMLResponse)
def global_settings(request: Request) -> HTMLResponse:
    """Render the global user-defaults settings page.

    Reads ``~/.urika/settings.toml`` (or the URIKA_HOME equivalent) and
    surfaces five fields the form posts back to ``PUT /api/settings``.
    """
    s = load_settings()
    privacy = s.get("privacy", {})
    mode = privacy.get("mode", "open")
    endpoint = privacy.get("endpoints", {}).get(mode, {})
    prefs = s.get("preferences", {})
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "global_settings.html",
        {
            "request": request,
            "values": {
                "default_privacy_mode": mode,
                "default_endpoint_url": endpoint.get("base_url", ""),
                "default_endpoint_key_env": endpoint.get("api_key_env", ""),
                "default_audience": prefs.get("audience", "expert"),
                "default_max_turns": prefs.get("max_turns_per_experiment", 10),
            },
            "valid_modes": VALID_PRIVACY_MODES,
            "valid_audiences": sorted(VALID_AUDIENCES),
        },
    )


@router.get("/projects/{name}/settings", response_class=HTMLResponse)
def project_settings(request: Request, name: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "project_settings.html",
        {
            "request": request,
            "project": summary,
            "valid_modes": sorted(VALID_MODES),
            "valid_audiences": sorted(VALID_AUDIENCES),
        },
    )


@router.get("/projects/{name}/run", response_class=HTMLResponse)
def project_run(request: Request, name: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    active_exp = _active_experiment(summary.path)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "run.html",
        {
            "request": request,
            "project": summary,
            "active_experiment_id": active_exp,
            "valid_modes": sorted(VALID_MODES),
            "valid_audiences": sorted(VALID_AUDIENCES),
        },
    )


@router.get("/projects/{name}/knowledge", response_class=HTMLResponse)
def project_knowledge(request: Request, name: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    store = KnowledgeStore(summary.path)
    entries = store.list_all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "knowledge.html",
        {
            "request": request,
            "project": summary,
            "entries": entries,
        },
    )


@router.get(
    "/projects/{name}/knowledge/{entry_id}",
    response_class=HTMLResponse,
)
def project_knowledge_entry(request: Request, name: str, entry_id: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    store = KnowledgeStore(summary.path)
    entry = store.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown entry")
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "knowledge_entry.html",
        {
            "request": request,
            "project": summary,
            "entry": entry,
        },
    )


@router.get(
    "/projects/{name}/experiments/{exp_id}/log",
    response_class=HTMLResponse,
)
def project_experiment_log(request: Request, name: str, exp_id: str) -> HTMLResponse:
    """Render the live log page for an experiment.

    The page itself is static HTML — its inline ``<script>`` opens an
    ``EventSource`` against the SSE endpoint
    (``/api/projects/<name>/runs/<exp_id>/stream``) and appends each
    incoming line to a ``<pre>``. We intentionally do *not* validate
    that the experiment dir exists, so the page can be loaded the
    instant ``POST /api/projects/<name>/run`` returns — before the
    orchestrator has flushed any output. The SSE endpoint tolerates
    that case and emits an ``event: status`` ``no_log`` event.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "run_log.html",
        {
            "request": request,
            "project": summary,
            "experiment_id": exp_id,
        },
    )


@router.get("/projects/{name}/experiments/{exp_id}", response_class=HTMLResponse)
def experiment_detail(request: Request, name: str, exp_id: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    try:
        exp = load_experiment(summary.path, exp_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Unknown experiment") from exc
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
