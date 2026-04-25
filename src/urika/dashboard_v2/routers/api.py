"""JSON API routes — used by HTMX fragments and external callers."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from urika.core.experiment import create_experiment
from urika.core.models import VALID_AUDIENCES, VALID_MODES
from urika.core.registry import ProjectRegistry
from urika.core.revisions import update_project_field
from urika.core.settings import load_settings, save_settings
from urika.dashboard_v2.projects import list_project_summaries, load_project_summary
from urika.dashboard_v2.runs import spawn_experiment_run

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
    s["privacy"].setdefault("endpoints", {}).setdefault(default_privacy_mode, {})[
        "base_url"
    ] = default_endpoint_url
    s["privacy"]["endpoints"][default_privacy_mode]["api_key_env"] = (
        default_endpoint_key_env
    )
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


@router.post("/projects/{name}/run")
async def api_project_run_post(name: str, request: Request):
    """Materialize a new experiment and spawn ``urika run`` for it.

    Validates the form fields, calls ``create_experiment`` to lay
    down the experiment dir, then hands off to
    ``spawn_experiment_run`` which Popens the CLI and detaches a
    daemon thread to drain its stdout into ``run.log``. The
    dashboard process keeps running; the subprocess outlives the
    HTTP request.

    Returns JSON when ``Accept: application/json``, otherwise an
    HTMX-friendly HTML fragment linking to the live log.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    # Read the form directly to avoid the path-param/form-field name collision.
    form = await request.form()
    name_field = (form.get("name") or "").strip()
    hypothesis = (form.get("hypothesis") or "").strip()
    mode = form.get("mode") or ""
    audience = form.get("audience") or ""
    max_turns = form.get("max_turns") or "10"
    # ``instructions`` is accepted but currently unused at spawn time —
    # the CLI picks up its own instructions from project state.
    _ = form.get("instructions") or ""

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
    try:
        max_turns_int = int(max_turns)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="max_turns must be an integer"
        ) from exc
    if max_turns_int <= 0:
        raise HTTPException(status_code=422, detail="max_turns must be > 0")
    if not name_field:
        raise HTTPException(status_code=422, detail="name is required")
    if not hypothesis:
        raise HTTPException(status_code=422, detail="hypothesis is required")

    exp = create_experiment(summary.path, name=name_field, hypothesis=hypothesis)
    pid = spawn_experiment_run(name, summary.path, exp.experiment_id)

    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse(
            {
                "experiment_id": exp.experiment_id,
                "status": "started",
                "pid": pid,
            }
        )
    return HTMLResponse(
        content=(
            f'<a class="btn btn--primary" '
            f'href="/projects/{name}/experiments/{exp.experiment_id}/log">'
            f"View live log →</a>"
        )
    )


@router.get("/projects/{name}/experiments/{exp_id}/artifacts")
def api_experiment_artifacts(name: str, exp_id: str):
    """Report which artifact files exist for a given experiment.

    Cheap on-disk probe — just three ``Path.exists`` checks. Used by
    the live log page to decide whether to reveal "view report" /
    "view presentation" buttons once a run completes, and useful from
    any other page that needs the same kind of existence flags.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    exp_dir = summary.path / "experiments" / exp_id
    return {
        "has_report": (exp_dir / "report.md").exists(),
        "has_presentation": (exp_dir / "presentation.html").exists(),
        "has_log": (exp_dir / "run.log").exists(),
    }


@router.get("/projects/{name}/runs/{exp_id}/stream")
async def api_run_stream(name: str, exp_id: str):
    """Server-sent-events tail of an experiment's ``run.log``.

    Emits each existing log line as ``data: <line>\\n\\n``, then polls
    every 0.5s for new content. When the ``.lock`` file disappears
    (the run has finished), flushes any remaining lines and emits an
    ``event: status\\ndata: {"status":"completed"}\\n\\n`` event before
    closing the connection.

    The browser-side EventSource (Task 6.5) consumes this stream.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    log_path = summary.path / "experiments" / exp_id / "run.log"
    lock_path = summary.path / "experiments" / exp_id / ".lock"

    async def event_stream():
        # Initial backlog — drain whatever's already on disk.
        position = 0
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    yield f"data: {line.rstrip()}\n\n"
                position = f.tell()

        # Poll for new lines until the lockfile disappears.
        while lock_path.exists() or log_path.exists():
            new_data = ""
            if log_path.exists():
                with open(log_path, "r", encoding="utf-8") as f:
                    f.seek(position)
                    new_data = f.read()
                    position = f.tell()
            if new_data:
                for line in new_data.splitlines():
                    yield f"data: {line}\n\n"
            if not lock_path.exists():
                # Lock gone — run has finished. Emit completion and close.
                yield (
                    f"event: status\ndata: {json.dumps({'status': 'completed'})}\n\n"
                )
                return
            await asyncio.sleep(0.5)

        # Reached only when both log and lock were missing from the start.
        yield (f"event: status\ndata: {json.dumps({'status': 'no_log'})}\n\n")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/projects/{name}/runs/{exp_id}/stop")
def api_run_stop(name: str, exp_id: str) -> dict:
    """Request a graceful stop of an in-flight experiment run.

    Writes ``"stop"`` to ``<project>/.urika/pause_requested``; the
    orchestrator's PauseController polls that file and tears the run
    down at the next safe checkpoint. The flag is project-level
    (only one active run per project today), so ``exp_id`` is echoed
    back for symmetry with the streaming/launcher URLs but does not
    influence the file path.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    flag_dir = summary.path / ".urika"
    flag_dir.mkdir(parents=True, exist_ok=True)
    (flag_dir / "pause_requested").write_text("stop", encoding="utf-8")

    return {"status": "stop_requested", "experiment_id": exp_id}
