"""JSON API routes — used by HTMX fragments and external callers."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from urika.core.models import VALID_AUDIENCES, VALID_MODES
from urika.core.registry import ProjectRegistry
from urika.core.revisions import update_project_field
from urika.core.settings import load_settings, save_settings
from urika.dashboard_v2.projects import list_project_summaries, load_project_summary

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/projects")
def api_projects() -> list[dict]:
    registry = ProjectRegistry().list_all()
    summaries = list_project_summaries(registry)
    return [
        {
            "name": s.name,
            "path": str(s.path),
            "question": s.question,
            "mode": s.mode,
            "description": s.description,
            "audience": s.audience,
            "experiment_count": s.experiment_count,
            "missing": s.missing,
        }
        for s in summaries
    ]


@router.put("/projects/{name}/settings")
def api_project_settings_put(
    name: str,
    request: Request,
    question: str = Form(""),
    description: str = Form(""),
    mode: str = Form(...),
    audience: str = Form(...),
):
    """Atomically update project settings and record per-field revisions.

    Validates ``mode`` and ``audience`` against the canonical core sets;
    only writes fields whose value actually changed (so revisions.json
    stays a faithful record of edits).

    Returns an HTML fragment for HTMX swap, or JSON if the client sets
    ``Accept: application/json``.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    if mode not in VALID_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"mode must be one of {sorted(VALID_MODES)}",
        )
    if audience not in VALID_AUDIENCES:
        raise HTTPException(
            status_code=422,
            detail=f"audience must be one of {sorted(VALID_AUDIENCES)}",
        )

    new_values = {
        "question": question.strip(),
        "description": description.strip(),
        "mode": mode,
        "audience": audience,
    }
    current = {
        "question": summary.question,
        "description": summary.description,
        "mode": summary.mode,
        "audience": summary.audience,
    }
    for field, new_v in new_values.items():
        if new_v != current.get(field, ""):
            update_project_field(summary.path, field=field, new_value=new_v)

    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        updated = load_project_summary(name, ProjectRegistry().list_all())
        return JSONResponse(
            {
                "name": updated.name,
                "question": updated.question,
                "description": updated.description,
                "mode": updated.mode,
                "audience": updated.audience,
            }
        )
    return HTMLResponse(content='<span class="text-success">Saved</span>')


@router.put("/settings")
def api_global_settings_put(
    request: Request,
    default_privacy_mode: str = Form(...),
    default_endpoint_url: str = Form(""),
    default_endpoint_key_env: str = Form(""),
    default_audience: str = Form(...),
    default_max_turns: str = Form(...),
):
    """Atomically rewrite ``~/.urika/settings.toml`` with the five
    global default fields.

    Endpoint URL/key are scoped under the chosen privacy mode in TOML;
    other modes' endpoint configs are preserved untouched.

    Returns an HTML fragment for HTMX swap, or JSON if the client sets
    ``Accept: application/json``.
    """
    if default_audience not in VALID_AUDIENCES:
        raise HTTPException(
            status_code=422,
            detail=f"audience must be one of {sorted(VALID_AUDIENCES)}",
        )
    try:
        max_turns = int(default_max_turns)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="default_max_turns must be an integer",
        ) from exc
    if max_turns <= 0:
        raise HTTPException(
            status_code=422,
            detail="default_max_turns must be > 0",
        )

    s = load_settings()
    s.setdefault("privacy", {})["mode"] = default_privacy_mode
    s["privacy"].setdefault("endpoints", {}).setdefault(
        default_privacy_mode, {}
    )["base_url"] = default_endpoint_url
    s["privacy"]["endpoints"][default_privacy_mode][
        "api_key_env"
    ] = default_endpoint_key_env
    s.setdefault("preferences", {})["audience"] = default_audience
    s["preferences"]["max_turns_per_experiment"] = max_turns

    save_settings(s)

    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse(
            {
                "default_privacy_mode": default_privacy_mode,
                "default_endpoint_url": default_endpoint_url,
                "default_endpoint_key_env": default_endpoint_key_env,
                "default_audience": default_audience,
                "default_max_turns": max_turns,
            }
        )
    return HTMLResponse(content='<span class="text-success">Saved</span>')
