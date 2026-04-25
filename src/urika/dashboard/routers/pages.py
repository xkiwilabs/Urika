"""HTML page routes — server-rendered Jinja templates."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from urika.core.experiment import list_experiments, load_experiment
from urika.core.method_registry import load_methods
from urika.core.models import VALID_AUDIENCES, VALID_MODES, ExperimentConfig
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry
from urika.core.settings import load_settings
from urika.dashboard.projects import (
    list_project_summaries,
    load_project_summary,
)
from urika.knowledge.store import KnowledgeStore

VALID_PRIVACY_MODES = ["private", "open", "university"]

# The eleven agent roles whose model/endpoint can be overridden per-project.
# Hardcoded (rather than discovered from the AgentRegistry) so the dashboard
# stays decoupled from the agent loading machinery.
KNOWN_AGENTS = [
    "planning_agent",
    "task_agent",
    "evaluator",
    "advisor_agent",
    "tool_builder",
    "literature_agent",
    "presentation_agent",
    "report_agent",
    "project_builder",
    "data_agent",
    "finalizer",
]

# Endpoint choices for per-agent overrides on the Models tab.
# 'inherit' is the no-override sentinel; the API handler skips writing it.
ENDPOINT_CHOICES = ["inherit", "open", "private"]

router = APIRouter(tags=["pages"])


def _experiment_runs_summary(
    exp_dir: Path, exp: ExperimentConfig
) -> tuple[int, str, str]:
    """Return ``(runs_count, last_touched_iso, status)`` for an experiment.

    ``status`` is the live status from ``progress.json`` when present,
    otherwise the static ``experiment.status`` (which is initialized to
    ``"pending"`` at experiment creation and rarely overwritten).
    """
    progress_path = exp_dir / "progress.json"
    if not progress_path.exists():
        return 0, exp.created_at, exp.status
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, exp.created_at, exp.status
    status = progress.get("status") or exp.status
    runs = progress.get("runs", []) or []
    if not runs:
        return 0, exp.created_at, status
    timestamps = [r.get("timestamp", "") for r in runs if r.get("timestamp")]
    last = max(timestamps) if timestamps else exp.created_at
    return len(runs), last, status


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
        {
            "request": request,
            "projects": summaries,
            "valid_modes": sorted(VALID_MODES),
            "valid_audiences": sorted(VALID_AUDIENCES),
        },
    )


@router.get("/projects/{name}", response_class=HTMLResponse)
def project_home(request: Request, name: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    recent_raw = list_experiments(summary.path)[-5:][::-1]
    # Overlay live status from progress.json on top of the static
    # experiment.json so 'pending' defaults don't mask completed runs.
    recent = []
    for exp in recent_raw:
        exp_dir = summary.path / "experiments" / exp.experiment_id
        _, _, status = _experiment_runs_summary(exp_dir, exp)
        recent.append(
            {
                "experiment_id": exp.experiment_id,
                "name": exp.name,
                "status": status,
            }
        )
    book = summary.path / "projectbook"
    final_outputs = {
        "has_findings": (book / "findings.json").exists(),
        "has_report": (book / "report.md").exists(),
        "has_presentation": (
            (book / "presentation.html").exists()
            or (book / "presentation" / "index.html").exists()
        ),
    }
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "project_home.html",
        {
            "request": request,
            "project": summary,
            "recent_experiments": recent,
            "final_outputs": final_outputs,
        },
    )


# Keys finalize.json is documented to emit (see
# src/urika/agents/roles/prompts/finalizer_system.md). Each well-known key
# gets its own block in the template. Anything else lands in a "More"
# collapsible — but never as raw JSON.
WELL_KNOWN_FINDINGS_KEYS = {
    "question",
    "answer",
    "final_methods",
    "experiments_summary",
    "criteria_status",
    "progression",
    "limitations",
    "future_work",
}


@router.get("/projects/{name}/findings", response_class=HTMLResponse)
def project_findings(request: Request, name: str) -> HTMLResponse:
    """Render ``projectbook/findings.json`` as structured HTML.

    finalize writes a documented schema (question / answer /
    final_methods / experiments_summary / criteria_status / progression
    / limitations / future_work). Each well-known key gets its own
    block. Anything outside that set goes into a collapsible "More"
    block as plain text / list / dl — we never dump raw JSON.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    findings_path = summary.path / "projectbook" / "findings.json"
    if not findings_path.exists():
        raise HTTPException(status_code=404, detail="No findings yet")
    try:
        findings = json.loads(findings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail="findings.json is malformed"
        ) from exc
    if not isinstance(findings, dict):
        raise HTTPException(status_code=500, detail="findings.json must be an object")

    extras = {k: v for k, v in findings.items() if k not in WELL_KNOWN_FINDINGS_KEYS}
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "findings.html",
        {
            "request": request,
            "project": summary,
            "findings": findings,
            "extras": extras,
        },
    )


@router.get("/projects/{name}/projectbook/report", response_class=HTMLResponse)
def projectbook_report(name: str, request: Request) -> HTMLResponse:
    """Render the project-level final report at ``projectbook/report.md``.

    Reuses ``report_view.html`` with an empty ``experiment_id`` and a
    ``title_override`` so the breadcrumb chain ends at the project,
    not an experiment.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    report_path = summary.path / "projectbook" / "report.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="No final report")
    from urika.dashboard.render import render_markdown

    # TODO: figures referenced from the project-level report (typically
    # under projectbook/artifacts/ or projectbook/figures/) currently
    # render broken in the dashboard. We don't yet have an artifact-viewer
    # route under projectbook to rewrite ``base_url`` to. The per-experiment
    # surface (where figures are actually used most) is fixed; this is a
    # follow-up.
    return request.app.state.templates.TemplateResponse(
        "report_view.html",
        {
            "request": request,
            "project": summary,
            "experiment_id": "",  # template handles empty
            "body_html": render_markdown(report_path.read_text(encoding="utf-8")),
            "title_override": "Final report",
        },
    )


@router.get("/projects/{name}/projectbook/presentation/{rest:path}")
def projectbook_presentation_asset(name: str, rest: str) -> FileResponse:
    """Serve sibling assets (CSS/JS/images) for the project-level deck.

    Without this, ``index.html`` loads but its relative
    ``<link rel="stylesheet" href="reveal.css">`` and
    ``<script src="reveal.min.js">`` references 404, and the deck
    renders as a single vertically-stacked page instead of slide-by-slide.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    if not rest or ".." in rest or rest.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    pres_root = (summary.path / "projectbook" / "presentation").resolve()
    asset_path = pres_root / rest
    if not asset_path.exists() or not asset_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    # Ensure we did not escape the presentation dir.
    if not asset_path.resolve().is_relative_to(pres_root):
        raise HTTPException(status_code=400, detail="Invalid path")
    return FileResponse(asset_path)


@router.get("/projects/{name}/projectbook/presentation")
def projectbook_presentation(name: str) -> FileResponse:
    """Serve the project-level final presentation.

    Accepts either ``projectbook/presentation.html`` or the directory
    form ``projectbook/presentation/index.html``.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    book = summary.path / "projectbook"
    for candidate in (
        book / "presentation.html",
        book / "presentation" / "index.html",
    ):
        if candidate.exists():
            return FileResponse(candidate, media_type="text/html")
    raise HTTPException(status_code=404, detail="No final presentation")


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
        runs_count, last_touched, status = _experiment_runs_summary(exp_dir, exp)
        rows.append(
            {
                "experiment_id": exp.experiment_id,
                "name": exp.name,
                "status": status,
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
            "valid_modes": sorted(VALID_MODES),
            "valid_audiences": sorted(VALID_AUDIENCES),
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
    """Render the global user-defaults settings page (4 tabs).

    Reads ``~/.urika/settings.toml`` (or the URIKA_HOME equivalent) and
    surfaces the full settings tree across four tabs (Privacy / Models /
    Preferences / Notifications). The form PUTs the entire config back
    to ``PUT /api/settings`` in a single payload.
    """
    s = load_settings()
    privacy = s.get("privacy", {})
    mode = privacy.get("mode", "open")
    endpoints = privacy.get("endpoints", {}) or {}
    private_ep = endpoints.get("private", {}) or {}
    runtime = s.get("runtime", {}) or {}
    runtime_models = runtime.get("models", {}) or {}
    prefs = s.get("preferences", {}) or {}
    notifications = s.get("notifications", {}) or {}

    # Suggested cloud-model dropdown values; mirrors the interactive CLI.
    cloud_models = ["claude-sonnet-4-5", "claude-opus-4-6", "claude-haiku-4-5"]

    # In hybrid mode the data_agent override carries the private model.
    hybrid_data_agent = runtime_models.get("data_agent", {}) or {}

    # Per-agent rows for the Models tab, mirroring the project settings page.
    model_rows = []
    for agent in KNOWN_AGENTS:
        row = runtime_models.get(agent, {}) or {}
        model_rows.append(
            {
                "agent": agent,
                "model": row.get("model", ""),
                "endpoint": row.get("endpoint", "inherit"),
            }
        )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "global_settings.html",
        {
            "request": request,
            # Privacy tab values
            "privacy_mode": mode,
            "privacy_open_model": runtime.get("model", "") if mode == "open" else "",
            "privacy_private_url": private_ep.get("base_url", ""),
            "privacy_private_key_env": private_ep.get("api_key_env", ""),
            "privacy_private_model": (
                runtime.get("model", "") if mode == "private" else ""
            ),
            "privacy_hybrid_cloud_model": (
                runtime.get("model", "") if mode == "hybrid" else ""
            ),
            "privacy_hybrid_private_url": (
                private_ep.get("base_url", "") if mode == "hybrid" else ""
            ),
            "privacy_hybrid_private_key_env": (
                private_ep.get("api_key_env", "") if mode == "hybrid" else ""
            ),
            "privacy_hybrid_private_model": hybrid_data_agent.get("model", ""),
            # Models tab
            "runtime_model": runtime.get("model", ""),
            "model_rows": model_rows,
            # Preferences tab
            "default_audience": prefs.get("audience", "expert"),
            "default_max_turns": prefs.get("max_turns_per_experiment", 10),
            "web_search": bool(prefs.get("web_search", False)),
            "venv": bool(prefs.get("venv", True)),
            # Notifications tab
            "notif_channels": notifications.get("channels", []) or [],
            "notif_email": notifications.get("email", {}) or {},
            "notif_slack": notifications.get("slack", {}) or {},
            "notif_telegram": notifications.get("telegram", {}) or {},
            # Choices
            "valid_modes": VALID_PRIVACY_MODES,
            "valid_privacy_modes": ["open", "private", "hybrid"],
            "valid_audiences": sorted(VALID_AUDIENCES),
            "cloud_models": cloud_models,
            "known_agents": KNOWN_AGENTS,
            "endpoint_choices": ENDPOINT_CHOICES,
        },
    )


@router.get("/projects/{name}/settings", response_class=HTMLResponse)
def project_settings(request: Request, name: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    # Load the full urika.toml so the template can render the structured
    # tabs (Data, Models, Privacy, Notifications) which need fields the
    # ProjectSummary dataclass doesn't expose.
    toml_path = summary.path / "urika.toml"
    try:
        with open(toml_path, "rb") as f:
            toml_data = tomllib.load(f)
    except FileNotFoundError:
        toml_data = {}

    project_section = toml_data.get("project", {})
    runtime_section = toml_data.get("runtime", {}) or {}
    runtime_models = runtime_section.get("models", {}) or {}
    notifications = toml_data.get("notifications", {}) or {}

    # Pre-shape per-agent rows for the Models tab so the template stays
    # logic-light. Each row carries the existing override (if any) so the
    # form re-populates after a save.
    model_rows = []
    for agent in KNOWN_AGENTS:
        row = runtime_models.get(agent, {}) or {}
        model_rows.append(
            {
                "agent": agent,
                "model": row.get("model", ""),
                "endpoint": row.get("endpoint", "inherit"),
            }
        )

    # Privacy tab: editable with "Inherit from global" semantics.
    # When the project has no [privacy] block in urika.toml, the radio
    # snaps to "inherit" and the per-mode fields are blank. When a block
    # exists, the radio reflects [privacy].mode and the per-mode fields
    # pull from [privacy.endpoints.private] and [runtime].
    global_settings = load_settings()
    global_privacy_mode = global_settings.get("privacy", {}).get("mode", "open")
    project_privacy = toml_data.get("privacy", {}) or {}
    project_privacy_endpoints = project_privacy.get("endpoints", {}) or {}
    project_privacy_private_ep = project_privacy_endpoints.get("private", {}) or {}
    project_privacy_mode = project_privacy.get("mode") if project_privacy else "inherit"
    if not project_privacy_mode:
        project_privacy_mode = "inherit"

    # Hybrid mode wires the data_agent override to the private model — mirror
    # the global page so we can re-populate the "private model" field.
    hybrid_data_agent = runtime_models.get("data_agent", {}) or {}

    # Stringify list/dict-valued project-section fields for textarea display.
    data_paths_text = "\n".join(project_section.get("data_paths", []) or [])
    success_criteria = project_section.get("success_criteria", {}) or {}
    success_criteria_text = "\n".join(f"{k}={v}" for k, v in success_criteria.items())

    # Suggested cloud-model dropdown values; mirrors the global settings page.
    cloud_models = ["claude-sonnet-4-5", "claude-opus-4-6", "claude-haiku-4-5"]

    # ---- Notifications tab: per-channel inherit / enabled / disabled --------
    # The project's [notifications] block, when present, overrides the global
    # one. Each known channel resolves to a per-channel state:
    #   * inherit  — channel absent from any project override
    #   * enabled  — channel listed in [notifications].channels
    #   * disabled — project explicitly excluded the channel (sentinel)
    # The disabled-sentinel is encoded as a key under [notifications._disabled]
    # so we can round-trip it without polluting the channels list.
    has_project_notifications = bool(notifications)
    project_disabled = (
        (notifications.get("_disabled", []) or []) if notifications else []
    )
    project_channels_explicit = notifications.get("channels", []) or []

    def _channel_state(channel: str) -> str:
        if not has_project_notifications:
            return "inherit"
        if channel in project_channels_explicit:
            return "enabled"
        if channel in project_disabled:
            return "disabled"
        return "inherit"

    notif_email = (notifications.get("email", {}) or {}) if notifications else {}
    notif_slack = (notifications.get("slack", {}) or {}) if notifications else {}
    notif_telegram = (
        (notifications.get("telegram", {}) or {}) if notifications else {}
    )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "project_settings.html",
        {
            "request": request,
            "project": summary,
            "valid_modes": sorted(VALID_MODES),
            "valid_audiences": sorted(VALID_AUDIENCES),
            "known_agents": KNOWN_AGENTS,
            "endpoint_choices": ENDPOINT_CHOICES,
            "model_rows": model_rows,
            "runtime_model": runtime_section.get("model", ""),
            "data_paths_text": data_paths_text,
            "success_criteria_text": success_criteria_text,
            "global_privacy_mode": global_privacy_mode,
            "project_privacy": project_privacy,
            "project_privacy_mode": project_privacy_mode,
            "project_privacy_open_model": (
                runtime_section.get("model", "")
                if project_privacy_mode == "open"
                else ""
            ),
            "project_privacy_private_url": project_privacy_private_ep.get(
                "base_url", ""
            ),
            "project_privacy_private_key_env": project_privacy_private_ep.get(
                "api_key_env", ""
            ),
            "project_privacy_private_model": (
                runtime_section.get("model", "")
                if project_privacy_mode == "private"
                else ""
            ),
            "project_privacy_hybrid_cloud_model": (
                runtime_section.get("model", "")
                if project_privacy_mode == "hybrid"
                else ""
            ),
            "project_privacy_hybrid_private_url": (
                project_privacy_private_ep.get("base_url", "")
                if project_privacy_mode == "hybrid"
                else ""
            ),
            "project_privacy_hybrid_private_key_env": (
                project_privacy_private_ep.get("api_key_env", "")
                if project_privacy_mode == "hybrid"
                else ""
            ),
            "project_privacy_hybrid_private_model": hybrid_data_agent.get(
                "model", ""
            ),
            "cloud_models": cloud_models,
            "notifications": notifications,
            "notif_channels": notifications.get("channels", []) or [],
            "notif_suppress_level": notifications.get("suppress_level", ""),
            # New per-channel inherit/enable/disable state for 11D.2
            "notif_email_state": _channel_state("email"),
            "notif_slack_state": _channel_state("slack"),
            "notif_telegram_state": _channel_state("telegram"),
            "notif_email": notif_email,
            "notif_slack": notif_slack,
            "notif_telegram": notif_telegram,
        },
    )


@router.get("/projects/{name}/advisor", response_class=HTMLResponse)
def project_advisor(name: str, request: Request) -> HTMLResponse:
    """Render the advisor chat panel.

    Reads ``projectbook/advisor-history.json`` (via
    :func:`urika.core.advisor_memory.load_history`) and renders one
    message bubble per entry plus an input form. The form submits via
    inline JS to the existing ``POST /api/projects/<n>/advisor``
    endpoint and appends the response to the transcript without
    reloading the page.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    from urika.core.advisor_memory import load_history

    history = load_history(summary.path)
    return request.app.state.templates.TemplateResponse(
        "advisor_chat.html",
        {"request": request, "project": summary, "history": history},
    )


@router.get("/projects/{name}/run")
def project_run_redirect(name: str) -> RedirectResponse:
    """Back-compat redirect for the old standalone Run page.

    The /run page has been replaced by a "+ New experiment" modal on the
    experiments list. We keep this URL working for anyone who bookmarked
    it: the redirect lands on the experiments page with ``?new=1``, which
    Alpine reads on init to auto-open the modal.
    """
    return RedirectResponse(
        url=f"/projects/{name}/experiments?new=1", status_code=307
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


@router.get(
    "/projects/{name}/experiments/{exp_id}/report",
    response_class=HTMLResponse,
)
def experiment_report(request: Request, name: str, exp_id: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    report_path = summary.path / "experiments" / exp_id / "report.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="No report for this experiment")

    from urika.dashboard.render import render_markdown

    body_html = render_markdown(
        report_path.read_text(encoding="utf-8"),
        base_url=f"/projects/{name}/experiments/{exp_id}/artifacts",
    )
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "report_view.html",
        {
            "request": request,
            "project": summary,
            "experiment_id": exp_id,
            "body_html": body_html,
        },
    )


# NOTE: must be registered BEFORE the bare ``/presentation`` route so
# FastAPI matches the asset variant when a sub-path is present. The
# ``{rest:path}`` converter requires a non-empty match (we enforce this
# with an explicit ``not rest`` check), so the bare-``/presentation``
# route below remains reachable.
@router.get("/projects/{name}/experiments/{exp_id}/presentation/{rest:path}")
def experiment_presentation_asset(
    name: str, exp_id: str, rest: str
) -> FileResponse:
    """Serve sibling assets (CSS/JS/images) for the per-experiment deck.

    Without this, ``index.html`` loads but its relative
    ``<link rel="stylesheet" href="reveal.css">`` and
    ``<script src="reveal.min.js">`` references 404, and the deck
    renders as a single vertically-stacked page instead of slide-by-slide.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    if not rest or ".." in rest or rest.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    pres_root = (
        summary.path / "experiments" / exp_id / "presentation"
    ).resolve()
    asset_path = pres_root / rest
    if not asset_path.exists() or not asset_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    # Ensure we did not escape the presentation dir.
    if not asset_path.resolve().is_relative_to(pres_root):
        raise HTTPException(status_code=400, detail="Invalid path")
    return FileResponse(asset_path)


@router.get("/projects/{name}/experiments/{exp_id}/presentation")
def experiment_presentation(name: str, exp_id: str) -> FileResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    exp_dir = summary.path / "experiments" / exp_id
    # presentation.html OR presentation/index.html — try both
    for candidate in (
        exp_dir / "presentation.html",
        exp_dir / "presentation" / "index.html",
    ):
        if candidate.exists():
            return FileResponse(candidate, media_type="text/html")
    raise HTTPException(status_code=404, detail="No presentation for this experiment")


@router.get("/projects/{name}/experiments/{exp_id}/artifacts/{filename}")
def experiment_artifact_file(name: str, exp_id: str, filename: str) -> FileResponse:
    """Serve a single file from ``<exp>/artifacts/`` for the dashboard.

    Used by the experiment detail page to render clickable
    thumbnails / links for figures, tables, and other artifact files
    written by the run. We resist path-traversal by rejecting any
    filename that contains a slash or ``..``; FastAPI URL-decodes
    path params before they reach the handler, so an encoded
    ``%2F`` shows up here as a literal ``/``.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    artifact_path = summary.path / "experiments" / exp_id / "artifacts" / filename
    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(artifact_path)


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
    # Live status overlays the static experiment.status default.
    experiment_status = progress.get("status") or exp.status

    exp_dir = summary.path / "experiments" / exp_id
    has_report = (exp_dir / "report.md").exists()
    # Presentation may be a single file (presentation.html) or a directory
    # containing index.html — accept both forms (matches the actual
    # presentation_agent output and the existing serve route).
    has_presentation = (
        (exp_dir / "presentation.html").exists()
        or (exp_dir / "presentation" / "index.html").exists()
    )
    has_log = (exp_dir / "run.log").exists()

    artifacts_dir = exp_dir / "artifacts"
    artifact_files: list[dict] = []
    if artifacts_dir.exists():
        for p in sorted(artifacts_dir.iterdir()):
            if p.is_file():
                artifact_files.append(
                    {
                        "name": p.name,
                        "url": f"/projects/{name}/experiments/{exp_id}/artifacts/{p.name}",
                        "size": p.stat().st_size,
                    }
                )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "experiment_detail.html",
        {
            "request": request,
            "project": summary,
            "experiment": exp,
            "experiment_status": experiment_status,
            "runs": runs,
            "has_report": has_report,
            "has_presentation": has_presentation,
            "has_log": has_log,
            "artifact_files": artifact_files,
        },
    )
