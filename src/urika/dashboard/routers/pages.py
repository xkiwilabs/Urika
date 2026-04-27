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
from urika.core.settings import get_named_endpoints, load_settings
from urika.core.workspace import load_project_config
from urika.dashboard.active_ops import list_active_operations
from urika.dashboard.projects import (
    list_project_summaries,
    load_project_summary,
)
from urika.knowledge.store import KnowledgeStore

VALID_PRIVACY_MODES = ["private", "open", "university"]

# Known cloud (Claude) model names surfaced as dropdown choices on
# both global and project Models tabs.  Mirrors the interactive CLI's
# ``_CLOUD_MODELS`` list (in ``urika.cli.config``) — any new Claude
# model the team wants users to pick from the dashboard goes here.
# Local-server model names stay free-text everywhere because they
# vary per deployment.
KNOWN_CLOUD_MODELS = [
    "claude-opus-4-7",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
]

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


def _project_template_context(name: str, summary) -> dict:
    """Common template context for any project-scoped page.

    Currently injects ``active_ops`` (read by ``_base.html`` to render
    the persistent running-ops banner). Phase B3 already pre-computes
    ``running_by_type`` / ``running_by_exp`` per-page; those callers
    keep doing so — the per-button maps and this flat list serve
    different surfaces (banner vs button state) and the helper just
    runs ``list_active_operations`` once more, which is cheap (a fixed
    set of stat calls plus one ``iterdir`` over experiments/).
    """
    return {"active_ops": list_active_operations(name, summary.path)}


def _experiment_runs_summary(
    exp_dir: Path, exp: ExperimentConfig
) -> tuple[int, str, str]:
    """Return ``(runs_count, last_touched_iso, status)`` for an experiment.

    Status is the *live* status:
    1. If a live run-lock exists under the experiment dir (``.lock``
       with an alive PID) → ``"running"``. Catches the window between
       experiment-dir creation and the orchestrator's first
       progress.json write — without this override the row would
       say "pending" while the agent is actually working.
    2. Otherwise, the status from ``progress.json`` if present.
    3. Otherwise, the static ``experiment.status`` (initialized to
       ``"pending"`` at creation).
    """
    from urika.core.project_delete import _is_active_run_lock

    lock_path = exp_dir / ".lock"
    if lock_path.is_file() and _is_active_run_lock(lock_path):
        # Counts + timestamp still come from progress.json if present.
        runs_count = 0
        last = exp.created_at
        progress_path = exp_dir / "progress.json"
        if progress_path.exists():
            try:
                progress = json.loads(progress_path.read_text(encoding="utf-8"))
                runs = progress.get("runs", []) or []
                runs_count = len(runs)
                timestamps = [
                    r.get("timestamp", "") for r in runs if r.get("timestamp")
                ]
                if timestamps:
                    last = max(timestamps)
            except (OSError, json.JSONDecodeError):
                pass
        return runs_count, last, "running"

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
    from urika.core.settings import get_named_endpoints

    registry = ProjectRegistry().list_all()
    summaries = list_project_summaries(registry)
    templates = request.app.state.templates
    # Surface "is at least one private endpoint configured" so the New
    # Project modal can warn when the user picks private/hybrid.
    has_private_endpoint = any(
        (ep.get("base_url") or "").strip() for ep in get_named_endpoints()
    )
    return templates.TemplateResponse(
        "projects_list.html",
        {
            "request": request,
            "projects": summaries,
            "valid_modes": sorted(VALID_MODES),
            "valid_audiences": sorted(VALID_AUDIENCES),
            "has_private_endpoint": has_private_endpoint,
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
        # Either the finalize flow's report.md OR the report-agent's
        # narrative.md (written at the end of every run). The view
        # route picks whichever exists.
        "has_report": (book / "report.md").exists() or (
            book / "narrative.md"
        ).exists(),
        "has_presentation": (
            (book / "presentation.html").exists()
            or (book / "presentation" / "index.html").exists()
        ),
    }
    has_summary = (book / "summary.md").exists()
    # Phase B3: surface running ops so the Summarize / Finalize buttons
    # can flip to "running… view log" links instead of opening a modal.
    active = list_active_operations(name, summary.path)
    running_by_type = {op.type: op for op in active}
    templates = request.app.state.templates
    ctx = {
        "request": request,
        "project": summary,
        "recent_experiments": recent,
        "final_outputs": final_outputs,
        "has_summary": has_summary,
        "running_by_type": running_by_type,
    }
    ctx.update(_project_template_context(name, summary))
    return templates.TemplateResponse("project_home.html", ctx)


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
    ctx = {
        "request": request,
        "project": summary,
        "findings": findings,
        "extras": extras,
    }
    ctx.update(_project_template_context(name, summary))
    return templates.TemplateResponse("findings.html", ctx)


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
    # Prefer the finalize flow's polished report.md; fall back to the
    # report-agent's narrative.md (written at the end of every
    # ``urika run``). Whichever exists is what we render.
    book = summary.path / "projectbook"
    report_path = next(
        (p for p in (book / "report.md", book / "narrative.md") if p.exists()),
        None,
    )
    if report_path is None:
        raise HTTPException(status_code=404, detail="No final report")
    from urika.dashboard.render import render_markdown

    raw = report_path.read_text(encoding="utf-8")
    # Project-level reports reference figures in three relative shapes:
    #   ![alt](figures/foo.png)              → projectbook/figures/foo.png
    #   ![alt](artifacts/foo.png)            → projectbook/artifacts/foo.png
    #   ![alt](../<exp_id>/artifacts/foo.png) → experiments/<exp_id>/artifacts/foo.png
    # Pre-process the markdown to rewrite these to absolute URLs that
    # resolve through the existing per-experiment artifact viewer
    # (route: /projects/<n>/experiments/<exp_id>/artifacts/<file>) and
    # the new projectbook subpath viewer (added below).
    import re as _re

    raw = _re.sub(
        r"\]\(\.\./([^/)]+)/artifacts/([^)]+)\)",
        rf"](/projects/{name}/experiments/\1/artifacts/\2)",
        raw,
    )
    raw = _re.sub(
        r"\]\((figures|artifacts)/([^)]+)\)",
        rf"](/projects/{name}/projectbook/\1/\2)",
        raw,
    )
    ctx = {
        "request": request,
        "project": summary,
        "experiment_id": "",  # template handles empty
        "body_html": render_markdown(raw),
        "title_override": "Final report",
    }
    ctx.update(_project_template_context(name, summary))
    return request.app.state.templates.TemplateResponse("report_view.html", ctx)


@router.get("/projects/{name}/projectbook/summary", response_class=HTMLResponse)
def projectbook_summary(name: str, request: Request) -> HTMLResponse:
    """Render the project-level summary at ``projectbook/summary.md``.

    Reuses ``report_view.html`` with an empty ``experiment_id`` and a
    ``title_override`` so the breadcrumb chain ends at the project,
    not an experiment. The summarizer is read-only and never produces
    figures, so no markdown post-processing is required.

    Registered BEFORE the catch-all ``projectbook/{rest:path}`` route so
    the markdown is rendered through the template rather than served
    raw as a FileResponse.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    summary_path = summary.path / "projectbook" / "summary.md"
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="No project summary")
    from urika.dashboard.render import render_markdown

    raw = summary_path.read_text(encoding="utf-8")
    ctx = {
        "request": request,
        "project": summary,
        "experiment_id": "",
        "body_html": render_markdown(raw),
        "title_override": "Project summary",
    }
    ctx.update(_project_template_context(name, summary))
    return request.app.state.templates.TemplateResponse("report_view.html", ctx)


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
def projectbook_presentation(name: str) -> HTMLResponse:
    """Serve the project-level final presentation.

    Accepts either ``projectbook/presentation.html`` or the directory
    form ``projectbook/presentation/index.html``.

    Injects a ``<base href=".../presentation/">`` tag so that relative
    ``<link href="reveal.css">`` and ``<script src="reveal.min.js">``
    references resolve under the existing
    ``/presentation/{rest:path}`` sub-path route. Without the base,
    the bare URL (no trailing slash) causes the browser to resolve
    relative URLs against the parent path, 404'ing the assets.
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
            html = candidate.read_text(encoding="utf-8")
            base_url = f"/projects/{name}/projectbook/presentation/"
            html = _inject_base_tag(html, base_url)
            return HTMLResponse(content=html)
    raise HTTPException(status_code=404, detail="No final presentation")


def _inject_base_tag(html: str, base_url: str) -> str:
    """Inject ``<base href="{base_url}">`` into ``<head>`` if present."""
    base_tag = f'<base href="{base_url}">'
    if "<head>" in html:
        return html.replace("<head>", f"<head>\n  {base_tag}", 1)
    import re

    if re.search(r"<head[^>]*>", html):
        return re.sub(r"(<head[^>]*>)", r"\1\n  " + base_tag, html, count=1)
    return base_tag + html


@router.get("/projects/{name}/projectbook/{rest:path}")
def projectbook_asset(name: str, rest: str) -> FileResponse:
    """Serve arbitrary files under ``<project>/projectbook/<rest>``.

    Powers the figures and artifacts referenced from the project-level
    final report (``projectbook/report.md``).  Common subpaths:
    ``figures/foo.png``, ``artifacts/foo.csv``.

    Path-traversal protection: rejects ``..`` segments and ensures the
    resolved file stays under the projectbook root.

    Registered AFTER the specific ``projectbook/report`` and
    ``projectbook/presentation`` routes so those still win for their
    exact paths; only "everything else" falls through here.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    if not rest or ".." in rest or rest.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    book_root = (summary.path / "projectbook").resolve()
    asset_path = book_root / rest
    if not asset_path.exists() or not asset_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    if not asset_path.resolve().is_relative_to(book_root):
        raise HTTPException(status_code=400, detail="Invalid path")
    return FileResponse(asset_path)


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

    # Phase B3: any active experiment ``run`` blocks a fresh one (Phase B2
    # design — run is project-scoped). Surface it so the "+ New experiment"
    # button can flip to a link pointing at the running experiment's log.
    active = list_active_operations(name, summary.path)
    running_by_type = {op.type: op for op in active}

    templates = request.app.state.templates
    ctx = {
        "request": request,
        "project": summary,
        "experiments": rows,
        "valid_modes": sorted(VALID_MODES),
        "valid_audiences": sorted(VALID_AUDIENCES),
        "running_by_type": running_by_type,
    }
    ctx.update(_project_template_context(name, summary))
    return templates.TemplateResponse("experiments.html", ctx)


def _tools_to_rows(tool_registry) -> list[dict]:
    """Read every registered tool's name/description/category."""
    rows: list[dict] = []
    for tool_name in tool_registry.list_all():
        tool = tool_registry.get(tool_name)
        if tool is None:
            continue
        rows.append(
            {
                "name": tool.name(),
                "description": tool.description(),
                "category": tool.category(),
            }
        )
    return rows


@router.get("/tools", response_class=HTMLResponse)
def global_tools(request: Request) -> HTMLResponse:
    """List built-in tools shipped with Urika (global, project-independent)."""
    from urika.tools.registry import ToolRegistry

    tool_registry = ToolRegistry()
    tool_registry.discover()
    return request.app.state.templates.TemplateResponse(
        "tools.html",
        {
            "request": request,
            "project": None,
            "tools": _tools_to_rows(tool_registry),
            "scope": "global",
            # No project context → no running-ops lookup. The template
            # only consults this map under ``scope == "project"``.
            "running_by_type": {},
        },
    )


@router.get("/projects/{name}/tools", response_class=HTMLResponse)
def project_tools(name: str, request: Request) -> HTMLResponse:
    """List custom tools authored under ``<project>/tools/``.

    Built-in tools live on the global ``/tools`` page; this view shows
    ONLY the project's own ``tools/*.py`` modules so users can see
    what's been added on top of the built-in set.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    from urika.tools.registry import ToolRegistry

    tool_registry = ToolRegistry()
    project_tools_dir = summary.path / "tools"
    tool_registry.discover_project(project_tools_dir)
    # Phase B3: + Build tool button flips to a link when a build is in
    # flight (project-scoped — only one tool build per project at a time).
    active = list_active_operations(name, summary.path)
    running_by_type = {op.type: op for op in active}
    ctx = {
        "request": request,
        "project": summary,
        "tools": _tools_to_rows(tool_registry),
        "scope": "project",
        "running_by_type": running_by_type,
        # active_ops shadows the Phase B3 lookup but the helper is
        # cheap and keeps the banner data path identical to every
        # other project page.
        "active_ops": active,
    }
    return request.app.state.templates.TemplateResponse("tools.html", ctx)


@router.get("/projects/{name}/criteria", response_class=HTMLResponse)
def project_criteria(name: str, request: Request) -> HTMLResponse:
    """Render ``[project].success_criteria`` from urika.toml.

    Read-only viewer — editing is done from the project Settings page's
    Data tab (success_criteria is one of the structured fields handled
    by ``_apply_structured_settings``). When the block is empty or
    missing we render an empty state pointing at settings.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    toml_path = summary.path / "urika.toml"
    criteria: dict = {}
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        criteria = data.get("project", {}).get("success_criteria", {}) or {}
    ctx = {"request": request, "project": summary, "criteria": criteria}
    ctx.update(_project_template_context(name, summary))
    return request.app.state.templates.TemplateResponse("criteria.html", ctx)


def _supported_data_extensions() -> set[str]:
    """Return the set of file extensions the data-loader registry handles."""
    from urika.data.readers.registry import ReaderRegistry

    registry = ReaderRegistry()
    registry.discover()
    # Internal attribute — collect from every registered reader. Falls back
    # to {".csv"} when something goes wrong, since the CSV reader ships
    # with the project and is the only reader currently registered.
    try:
        exts: set[str] = set()
        for name in registry.list_all():
            for r in registry._readers.values():  # noqa: SLF001
                if r.name() == name:
                    exts.update(r.supported_extensions())
        return exts or {".csv"}
    except Exception:
        return {".csv"}


def _resolve_data_path(
    project_path: Path,
    data_paths: list[str],
    requested_path: str,
) -> Path:
    """Resolve ``requested_path`` and confirm it sits inside an allow-listed root.

    The allow-list is the project's registered ``data_paths`` plus the
    project's own ``<project>/data`` directory. Raises ``HTTPException(400)``
    when the resolved path escapes every allow-listed root, when the
    request is empty, or when the path includes a literal ``..`` segment
    (defence in depth — ``Path.resolve`` already collapses these but the
    early check produces a clearer 400).

    Symlinks pointing outside an allow-list root are rejected because
    ``Path.resolve(strict=False)`` walks symlinks before comparison.
    """
    if not requested_path:
        raise HTTPException(status_code=400, detail="Missing path")
    if ".." in Path(requested_path).parts:
        raise HTTPException(status_code=400, detail="Invalid path")
    try:
        resolved = Path(requested_path).resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Invalid path") from exc

    allow_roots: list[Path] = []
    for entry in data_paths:
        try:
            allow_roots.append(Path(entry).resolve())
        except OSError:
            continue
    # Always permit the project's bundled <project>/data directory.
    try:
        allow_roots.append((project_path / "data").resolve())
    except OSError:
        pass

    for root in allow_roots:
        # is_relative_to also returns True when resolved == root, so a
        # data_paths entry that points directly at a file still validates.
        if resolved == root or resolved.is_relative_to(root):
            return resolved
    raise HTTPException(status_code=400, detail="Path is outside data sources")


@router.get("/projects/{name}/data", response_class=HTMLResponse)
def project_data(request: Request, name: str) -> HTMLResponse:
    """List files registered as project data sources.

    Iterates over ``[project].data_paths`` from urika.toml. Each entry is
    a string path; if it resolves to a directory we list the files
    inside that the loader's reader registry can handle, otherwise we
    treat it as a single file. Each row carries enough metadata
    (existence, format-supported, size, row-count when cheap to read) to
    render the listing without spawning the loader for every file —
    schema/preview only happens on the dedicated inspect page.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    cfg = load_project_config(summary.path)
    supported_exts = _supported_data_extensions()

    rows: list[dict] = []
    seen: set[Path] = set()

    def _add_file(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            return
        seen.add(resolved)
        ext = path.suffix.lower()
        exists = path.exists()
        format_supported = ext in supported_exts
        size_bytes: int | None = None
        if exists and path.is_file():
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = None
        rows.append(
            {
                "path": str(path),
                "name": path.name,
                "exists": exists,
                "format_supported": format_supported,
                "extension": ext,
                "size_bytes": size_bytes,
            }
        )

    for entry in cfg.data_paths or []:
        p = Path(entry)
        if p.is_dir():
            for child in sorted(p.iterdir()):
                if child.is_file() and child.suffix.lower() in supported_exts:
                    _add_file(child)
        else:
            _add_file(p)

    templates = request.app.state.templates
    ctx = {
        "request": request,
        "project": summary,
        "rows": rows,
        "data_paths": cfg.data_paths or [],
    }
    ctx.update(_project_template_context(name, summary))
    return templates.TemplateResponse("data_list.html", ctx)


@router.get("/projects/{name}/data/inspect", response_class=HTMLResponse)
def project_data_inspect(request: Request, name: str, path: str = "") -> HTMLResponse:
    """Inspect one data file: schema + missing counts + head/tail preview.

    The ``path`` query parameter is validated against the project's
    registered ``data_paths`` (plus ``<project>/data``) by
    :func:`_resolve_data_path` — anything outside that allow-list 400s.
    Missing files 404 and unsupported formats render with an explanatory
    message rather than crashing.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    cfg = load_project_config(summary.path)

    resolved = _resolve_data_path(summary.path, cfg.data_paths or [], path)

    from urika.data.loader import load_dataset

    templates = request.app.state.templates
    error: str | None = None
    schema_rows: list[dict] = []
    head_rows: list[dict] = []
    tail_rows: list[dict] = []
    n_rows = 0
    n_columns = 0
    columns: list[str] = []
    try:
        view = load_dataset(resolved)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except ValueError:
        error = "Unsupported format"
        view = None  # type: ignore[assignment]

    if view is not None:
        s = view.summary
        n_rows = s.n_rows
        n_columns = s.n_columns
        columns = s.columns
        for col in s.columns:
            schema_rows.append(
                {
                    "name": col,
                    "dtype": s.dtypes.get(col, ""),
                    "missing": s.missing_counts.get(col, 0),
                    "stats": s.numeric_stats.get(col),
                }
            )
        # Head / tail preview — convert to records dicts so the template
        # can iterate without a pandas dependency.
        head_rows = view.data.head(10).to_dict("records")
        tail_rows = view.data.tail(10).to_dict("records")

    ctx = {
        "request": request,
        "project": summary,
        "file_path": str(resolved),
        "file_name": resolved.name,
        "error": error,
        "n_rows": n_rows,
        "n_columns": n_columns,
        "columns": columns,
        "schema_rows": schema_rows,
        "head_rows": head_rows,
        "tail_rows": tail_rows,
    }
    ctx.update(_project_template_context(name, summary))
    return templates.TemplateResponse("data_inspect.html", ctx)


@router.get("/projects/{name}/usage", response_class=HTMLResponse)
def project_usage(request: Request, name: str) -> HTMLResponse:
    """Render usage time-series + totals for the project.

    Reads ``<project>/usage.json`` (via :func:`load_usage` /
    :func:`get_totals`). The schema doesn't carry per-experiment or
    per-agent breakdown so the page sticks to time-series of total
    tokens and cost, plus a recent-sessions table capped at 50.
    Pre-computes ``tokens_series`` and ``cost_series`` arrays so the
    template can hand them to Chart.js as JSON without per-row JS work.
    """
    from urika.core.usage import get_totals, load_usage

    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    data = load_usage(summary.path)
    sessions = data.get("sessions", []) or []
    totals = get_totals(summary.path)

    tokens_series: list[dict] = []
    cost_series: list[dict] = []
    for s in sessions:
        ended = s.get("ended", "") or s.get("started", "")
        if not ended:
            continue
        tin = int(s.get("tokens_in", 0) or 0)
        tout = int(s.get("tokens_out", 0) or 0)
        tokens_series.append({"x": ended, "y": tin + tout})
        cost_series.append({"x": ended, "y": float(s.get("cost_usd", 0) or 0)})

    # Recent 50, newest-first. The on-disk order is append-only so the
    # last entry is the most recent.
    recent_sessions = list(reversed(sessions))[:50]

    templates = request.app.state.templates
    ctx = {
        "request": request,
        "project": summary,
        "totals": totals,
        "sessions": sessions,
        "recent_sessions": recent_sessions,
        "tokens_series": tokens_series,
        "cost_series": cost_series,
    }
    ctx.update(_project_template_context(name, summary))
    return templates.TemplateResponse("usage.html", ctx)


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
    ctx = {
        "request": request,
        "project": summary,
        "methods": methods,
        "metric_keys": metric_keys,
    }
    ctx.update(_project_template_context(name, summary))
    return templates.TemplateResponse("methods.html", ctx)


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
    endpoints = privacy.get("endpoints", {}) or {}
    runtime = s.get("runtime", {}) or {}
    # Multi-endpoint editor on the Privacy tab. Each entry shape:
    #   {"name", "base_url", "api_key_env", "default_model"}
    named_endpoints = get_named_endpoints()
    runtime_modes = runtime.get("modes", {}) or {}
    runtime_models = runtime.get("models", {}) or {}
    prefs = s.get("preferences", {}) or {}
    notifications = s.get("notifications", {}) or {}

    # Suggested cloud-model dropdown values; mirrors the interactive CLI.
    cloud_models = [
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
    ]

    # Per-mode per-agent grids (Models tab — full layout in commit 9).
    # Each mode dict surfaces the default model + per-agent rows so the
    # template can render three independent grids.
    mode_grids: dict[str, dict] = {}
    for mode_name in ("open", "private", "hybrid"):
        mode_cfg = runtime_modes.get(mode_name, {}) or {}
        per_agent_models = mode_cfg.get("models", {}) or {}
        rows = []
        for agent in KNOWN_AGENTS:
            row = per_agent_models.get(agent, {}) or {}
            rows.append(
                {
                    "agent": agent,
                    "model": row.get("model", ""),
                    "endpoint": row.get("endpoint", "inherit"),
                }
            )
        # Per-mode default model.  Cloud modes fall back to the
        # claude-opus-4-7 placeholder; private starts blank.
        default_model = mode_cfg.get("model", "")
        mode_grids[mode_name] = {
            "default_model": default_model,
            "rows": rows,
        }

    # Legacy per-agent rows for the Models tab — still used until the
    # commit 7 redesign replaces the single grid with per-mode grids.
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
    # List of defined endpoint names (sorted) for the Models tab's
    # per-agent endpoint <select>. The implicit ``open`` cloud endpoint
    # is added in-template based on mode constraints.
    defined_endpoint_names = [ep["name"] for ep in named_endpoints]
    # Private-mode rows pick an endpoint by name and the form auto-derives
    # the matching ``default_model`` for submission.  Only endpoints with
    # a ``default_model`` defined are eligible — without one, there is
    # nothing to populate the model field with.
    private_endpoint_options = [
        {"name": ep["name"], "default_model": ep["default_model"]}
        for ep in named_endpoints
        if ep.get("default_model")
    ]

    return templates.TemplateResponse(
        "global_settings.html",
        {
            "request": request,
            # Privacy tab — multi-endpoint editor.
            "named_endpoints": named_endpoints,
            "defined_endpoint_names": defined_endpoint_names,
            "private_endpoint_options": private_endpoint_options,
            # Models tab
            "runtime_model": runtime.get("model", ""),
            "model_rows": model_rows,
            "mode_grids": mode_grids,
            # Preferences tab
            "default_audience": prefs.get("audience", "novice"),
            "default_max_turns": prefs.get("max_turns_per_experiment", 10),
            "web_search": bool(prefs.get("web_search", False)),
            # venv default is OFF: use the global urika venv, not per-project.
            "venv": bool(prefs.get("venv", False)),
            # Notifications tab — connection details + per-channel
            # ``auto_enable`` flag. ``auto_enable`` is a creation-time
            # hint (read by ``urika new`` and POST /api/projects); the
            # runtime notification loader does not consult it.
            "notif_email": notifications.get("email", {}) or {},
            "notif_slack": notifications.get("slack", {}) or {},
            "notif_telegram": notifications.get("telegram", {}) or {},
            "notif_email_auto_enable": bool(
                (notifications.get("email", {}) or {}).get("auto_enable", False)
            ),
            "notif_slack_auto_enable": bool(
                (notifications.get("slack", {}) or {}).get("auto_enable", False)
            ),
            "notif_telegram_auto_enable": bool(
                (notifications.get("telegram", {}) or {}).get("auto_enable", False)
            ),
            # Choices
            "valid_modes": VALID_PRIVACY_MODES,
            "valid_privacy_modes": ["open", "private", "hybrid"],
            "valid_audiences": sorted(VALID_AUDIENCES),
            "cloud_models": cloud_models,
            "known_cloud_models": KNOWN_CLOUD_MODELS,
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

    # Privacy tab: mode is required (no inherit option).  When the
    # project has no [privacy] block, default to ``open`` for the radio.
    # The per-mode fields pull from [privacy.endpoints.private] and
    # [runtime] when present.
    project_privacy = toml_data.get("privacy", {}) or {}
    project_privacy_endpoints = project_privacy.get("endpoints", {}) or {}
    project_privacy_private_ep = project_privacy_endpoints.get("private", {}) or {}
    project_privacy_mode = project_privacy.get("mode") or "open"

    # Pre-shape per-agent rows for the Models tab so the template stays
    # logic-light. Each row carries:
    #   - agent: agent name
    #   - model: project override (empty if none)
    #   - endpoint: project override (empty/'inherit' if none)
    #   - placeholder_model: global per-mode default model for this agent
    #   - force_private: True for data_agent + tool_builder when mode=hybrid
    #   - endpoint_choices: list of allowed endpoint values for this row,
    #     computed from the project's mode + force_private flag.
    #
    # The placeholders surface live-inheritance from the global
    # [runtime.modes.<project_mode>] block: the user sees what they'd
    # inherit, and any field they edit becomes a project override.
    from urika.agents.config import _load_global_per_mode

    global_default_model, global_per_agent = _load_global_per_mode(project_privacy_mode)

    # Endpoint constraints by mode:
    #   open    → all agents may pick any defined endpoint + ``open``
    #   private → all agents private only (the implicit ``open`` cloud
    #             endpoint is hidden — defeats the point of private mode)
    #   hybrid  → data_agent + tool_builder private only; others may
    #             pick any defined endpoint + ``open``
    #
    # The dropdown's choices come from globals' [privacy.endpoints.*] —
    # any user-defined name (private, ollama, vllm_small, ...) shows up
    # as long as the mode allows it.
    # data_agent's hybrid endpoint is HARD-LOCKED to private (cloud is
    # excluded from its dropdown entirely). tool_builder DEFAULTS to
    # private but the user is free to switch it to open.
    _HYBRID_LOCKED_PRIVATE = {"data_agent"}
    _HYBRID_DEFAULT_PRIVATE = {"data_agent", "tool_builder"}
    _named_endpoints_full = get_named_endpoints()
    project_named_endpoints = [ep["name"] for ep in _named_endpoints_full]
    # Private-mode rows pick an endpoint by name and the form auto-derives
    # the matching ``default_model`` for submission.  Only endpoints with
    # a ``default_model`` defined are eligible.
    private_endpoint_options = [
        {"name": ep["name"], "default_model": ep["default_model"]}
        for ep in _named_endpoints_full
        if ep.get("default_model")
    ]

    def _endpoint_choices_for(agent: str) -> tuple[list[str], bool]:
        # Always sort defined endpoints for stable rendering.
        named = sorted(project_named_endpoints)
        if project_privacy_mode == "private":
            return (named, False)
        if project_privacy_mode == "hybrid" and agent in _HYBRID_LOCKED_PRIVATE:
            return (named, True)
        # Non-restricted: cloud + every named endpoint.
        return (["open"] + named, False)

    model_rows = []
    for agent in KNOWN_AGENTS:
        row = runtime_models.get(agent, {}) or {}
        gcfg = global_per_agent.get(agent)
        placeholder_model = gcfg.model if gcfg else ""
        choices, force_private = _endpoint_choices_for(agent)
        model_rows.append(
            {
                "agent": agent,
                "model": row.get("model", ""),
                "endpoint": row.get("endpoint", "inherit"),
                "placeholder_model": placeholder_model,
                "force_private": force_private,
                "endpoint_choices": choices,
            }
        )

    # Hybrid mode wires the data_agent override to the private model — mirror
    # the global page so we can re-populate the "private model" field.
    hybrid_data_agent = runtime_models.get("data_agent", {}) or {}

    # Inheritance hint for the Privacy tab. When globals define a usable
    # private endpoint AND the project doesn't override it, the URL field
    # may be left blank — the runtime loader (commit 1) inherits the
    # global endpoint at agent dispatch time. Surface what's available so
    # the user knows what they'd inherit.
    _inherited_private_ep = next(
        (
            ep
            for ep in _named_endpoints_full
            if ep.get("name") == "private" and (ep.get("base_url") or "").strip()
        ),
        None,
    )
    inherited_endpoint = {
        "private": _inherited_private_ep,
        "hybrid": _inherited_private_ep,
    }

    # Stringify list/dict-valued project-section fields for textarea display.
    data_paths_text = "\n".join(project_section.get("data_paths", []) or [])
    success_criteria = project_section.get("success_criteria", {}) or {}
    success_criteria_text = "\n".join(f"{k}={v}" for k, v in success_criteria.items())

    # Suggested cloud-model dropdown values; mirrors the global settings page.
    cloud_models = [
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
    ]

    # ---- Notifications tab: 2-state (enabled / disabled) per channel -------
    # The project's [notifications].channels list is the authority — a
    # channel listed there is on, anything else is off. New projects are
    # seeded from the global ``auto_enable`` flags at creation time
    # (see POST /api/projects). Per-channel overrides
    # (extra_to for email, override_chat_id for telegram) keep working.
    project_channels_explicit = notifications.get("channels", []) or []

    def _channel_enabled(channel: str) -> bool:
        return channel in project_channels_explicit

    notif_email = (notifications.get("email", {}) or {}) if notifications else {}
    notif_slack = (notifications.get("slack", {}) or {}) if notifications else {}
    notif_telegram = (notifications.get("telegram", {}) or {}) if notifications else {}

    # Danger zone: block trash if a live run-lock PID file is present
    # anywhere under the project (active run / evaluate / finalize /
    # build / etc.). Reuse the core helper so the UI matches the
    # server-side rule exactly — and so JSON write mutexes
    # (``criteria.json.lock``, ``usage.json.lock`` from
    # ``urika.core.filelock``) don't trigger a false positive. Wrap in
    # try/except so a permission error doesn't 500 the settings page.
    from urika.core.project_delete import _find_active_lock

    active_lock_path: Path | None = None
    try:
        active_lock_path = _find_active_lock(summary.path)
    except OSError:
        active_lock_path = None

    templates = request.app.state.templates
    ctx_extra = _project_template_context(name, summary)
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
            "runtime_model_placeholder": (global_default_model or "claude-opus-4-7"),
            "data_paths_text": data_paths_text,
            "success_criteria_text": success_criteria_text,
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
            "project_privacy_hybrid_private_model": hybrid_data_agent.get("model", ""),
            "cloud_models": cloud_models,
            "known_cloud_models": KNOWN_CLOUD_MODELS,
            "private_endpoint_options": private_endpoint_options,
            "inherited_endpoint": inherited_endpoint,
            "notifications": notifications,
            "notif_channels": notifications.get("channels", []) or [],
            "notif_suppress_level": notifications.get("suppress_level", ""),
            # 2-state per-channel enabled/disabled for the project
            # Notifications tab. The channels list is the authority.
            "notif_email_enabled": _channel_enabled("email"),
            "notif_slack_enabled": _channel_enabled("slack"),
            "notif_telegram_enabled": _channel_enabled("telegram"),
            "notif_email": notif_email,
            "notif_slack": notif_slack,
            "notif_telegram": notif_telegram,
            "active_lock_path": active_lock_path,
            **ctx_extra,
        },
    )


@router.get("/projects/{name}/summarize/log", response_class=HTMLResponse)
def project_summarize_log(name: str, request: Request) -> HTMLResponse:
    """Live-tail the project's summarize log via SSE.

    Mirrors :func:`project_finalize_log` but reads from
    ``projectbook/summarize.log`` (via the
    ``/api/projects/<n>/summarize/stream`` endpoint) and watches
    ``projectbook/.summarize.lock`` for completion.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    ctx = {"request": request, "project": summary}
    ctx.update(_project_template_context(name, summary))
    return request.app.state.templates.TemplateResponse("summarize_log.html", ctx)


@router.get("/projects/{name}/tools/build/log", response_class=HTMLResponse)
def project_tool_build_log(name: str, request: Request) -> HTMLResponse:
    """Live-tail the project's tool-build log via SSE.

    Mirrors :func:`project_finalize_log` but reads from ``tools/build.log``
    and watches ``tools/.build.lock`` for completion. The "back" link
    returns to the project Tools page rather than the project home.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    ctx = {"request": request, "project": summary}
    ctx.update(_project_template_context(name, summary))
    return request.app.state.templates.TemplateResponse("tool_build_log.html", ctx)


@router.get("/projects/{name}/finalize/log", response_class=HTMLResponse)
def project_finalize_log(name: str, request: Request) -> HTMLResponse:
    """Live-tail the project's finalize log via SSE.

    Mirrors :func:`project_experiment_log` but reads from
    ``projectbook/finalize.log`` (via the existing
    ``/api/projects/<n>/finalize/stream`` endpoint) and watches
    ``projectbook/.finalize.lock`` for completion. The page itself
    is static; the inline ``<script>`` opens an ``EventSource`` and
    appends each line to a ``<pre>``.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    ctx = {"request": request, "project": summary}
    ctx.update(_project_template_context(name, summary))
    return request.app.state.templates.TemplateResponse("finalize_log.html", ctx)


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
    ctx = {"request": request, "project": summary, "history": history}
    ctx.update(_project_template_context(name, summary))
    return request.app.state.templates.TemplateResponse("advisor_chat.html", ctx)


@router.get("/projects/{name}/run")
def project_run_redirect(name: str) -> RedirectResponse:
    """Back-compat redirect for the old standalone Run page.

    The /run page has been replaced by a "+ New experiment" modal on the
    experiments list. We keep this URL working for anyone who bookmarked
    it: the redirect lands on the experiments page with ``?new=1``, which
    Alpine reads on init to auto-open the modal.
    """
    return RedirectResponse(url=f"/projects/{name}/experiments?new=1", status_code=307)


@router.get("/projects/{name}/knowledge", response_class=HTMLResponse)
def project_knowledge(request: Request, name: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    store = KnowledgeStore(summary.path)
    entries = store.list_all()
    templates = request.app.state.templates
    ctx = {
        "request": request,
        "project": summary,
        "entries": entries,
    }
    ctx.update(_project_template_context(name, summary))
    return templates.TemplateResponse("knowledge.html", ctx)


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
    ctx = {
        "request": request,
        "project": summary,
        "entry": entry,
    }
    ctx.update(_project_template_context(name, summary))
    return templates.TemplateResponse("knowledge_entry.html", ctx)


_EXPERIMENT_LOG_TYPES = {"run", "evaluate", "report", "present"}


@router.get(
    "/projects/{name}/experiments/{exp_id}/log",
    response_class=HTMLResponse,
)
def project_experiment_log(
    request: Request, name: str, exp_id: str, type: str = "run"
) -> HTMLResponse:
    """Render the live log page for an experiment.

    The page itself is static HTML — its inline ``<script>`` opens an
    ``EventSource`` against the SSE endpoint
    (``/api/projects/<name>/runs/<exp_id>/stream``) and appends each
    incoming line to a ``<pre>``. We intentionally do *not* validate
    that the experiment dir exists, so the page can be loaded the
    instant ``POST /api/projects/<name>/run`` returns — before the
    orchestrator has flushed any output. The SSE endpoint tolerates
    that case and emits an ``event: status`` ``no_log`` event.

    ``type`` selects which log file the page tails — defaults to
    ``run``. Allowed values are ``run``, ``evaluate``, ``report``,
    ``present``. Unknown values silently fall back to ``run`` (we
    don't 422 on a flaky query string), and the allow-list also
    keeps untrusted input from leaking into the SSE stream URL.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    log_type = type if type in _EXPERIMENT_LOG_TYPES else "run"
    templates = request.app.state.templates
    ctx = {
        "request": request,
        "project": summary,
        "experiment_id": exp_id,
        "log_type": log_type,
    }
    ctx.update(_project_template_context(name, summary))
    return templates.TemplateResponse("run_log.html", ctx)


@router.get(
    "/projects/{name}/experiments/{exp_id}/report",
    response_class=HTMLResponse,
)
def experiment_report(request: Request, name: str, exp_id: str) -> HTMLResponse:
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    # Look for either the finalize flow's ``report.md`` (preferred —
    # polished, post-finalize) or the report-agent's
    # ``labbook/narrative.md`` (per-experiment narrative produced by
    # ``urika run``'s default report-generation pass). Whichever
    # exists is what we render.
    exp_dir = summary.path / "experiments" / exp_id
    candidates = [
        exp_dir / "report.md",
        exp_dir / "labbook" / "narrative.md",
    ]
    report_path = next((p for p in candidates if p.exists()), None)
    if report_path is None:
        raise HTTPException(status_code=404, detail="No report for this experiment")

    from urika.dashboard.render import render_markdown

    body_html = render_markdown(
        report_path.read_text(encoding="utf-8"),
        base_url=f"/projects/{name}/experiments/{exp_id}/artifacts",
    )
    templates = request.app.state.templates
    ctx = {
        "request": request,
        "project": summary,
        "experiment_id": exp_id,
        "body_html": body_html,
    }
    ctx.update(_project_template_context(name, summary))
    return templates.TemplateResponse("report_view.html", ctx)


# NOTE: must be registered BEFORE the bare ``/presentation`` route so
# FastAPI matches the asset variant when a sub-path is present. The
# ``{rest:path}`` converter requires a non-empty match (we enforce this
# with an explicit ``not rest`` check), so the bare-``/presentation``
# route below remains reachable.
@router.get("/projects/{name}/experiments/{exp_id}/presentation/{rest:path}")
def experiment_presentation_asset(name: str, exp_id: str, rest: str) -> FileResponse:
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
    pres_root = (summary.path / "experiments" / exp_id / "presentation").resolve()
    asset_path = pres_root / rest
    if not asset_path.exists() or not asset_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    # Ensure we did not escape the presentation dir.
    if not asset_path.resolve().is_relative_to(pres_root):
        raise HTTPException(status_code=400, detail="Invalid path")
    return FileResponse(asset_path)


@router.get("/projects/{name}/experiments/{exp_id}/presentation")
def experiment_presentation(name: str, exp_id: str) -> HTMLResponse:
    """Serve the per-experiment presentation.

    Injects a ``<base href=".../presentation/">`` tag so that relative
    ``<link href="reveal.css">`` and ``<script src="reveal.min.js">``
    references resolve under the existing
    ``/presentation/{rest:path}`` sub-path route. Without the base,
    the bare URL (no trailing slash) causes the browser to resolve
    relative URLs against the parent path, 404'ing the assets.
    """
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
            html = candidate.read_text(encoding="utf-8")
            base_url = f"/projects/{name}/experiments/{exp_id}/presentation/"
            html = _inject_base_tag(html, base_url)
            return HTMLResponse(content=html)
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
    exp_dir = summary.path / "experiments" / exp_id

    # Live status overlay: a live run-lock means the agent is actually
    # working RIGHT NOW, regardless of what progress.json says (which
    # may lag the orchestrator's first write).
    from urika.core.project_delete import _is_active_run_lock

    _live_lock = exp_dir / ".lock"
    if _live_lock.is_file() and _is_active_run_lock(_live_lock):
        experiment_status = "running"
    else:
        experiment_status = progress.get("status") or exp.status
    # Either the finalize flow's report.md OR the report-agent's
    # labbook/narrative.md (written by ``urika run`` at the end of every
    # successful run). Both surface as "View report".
    has_report = (exp_dir / "report.md").exists() or (
        exp_dir / "labbook" / "narrative.md"
    ).exists()
    # Presentation may be a single file (presentation.html) or a directory
    # containing index.html — accept both forms (matches the actual
    # presentation_agent output and the existing serve route).
    has_presentation = (exp_dir / "presentation.html").exists() or (
        exp_dir / "presentation" / "index.html"
    ).exists()
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

    # Phase B3: surface running per-experiment ops (evaluate / report /
    # present) keyed by ``(type, experiment_id)`` so each artifact-row
    # button can independently flip to a "running… view log" link
    # without affecting siblings on other experiments.
    active = list_active_operations(name, summary.path)
    running_by_exp = {(op.type, op.experiment_id): op for op in active}

    # Danger zone: block trash if a live run-lock PID file is present
    # under the experiment dir. Reuse the core helper so the UI matches
    # the server-side rule exactly (and JSON write mutexes don't trigger
    # a false positive).
    from urika.core.project_delete import _find_active_lock

    active_lock_path: Path | None = None
    try:
        active_lock_path = _find_active_lock(exp_dir)
    except OSError:
        active_lock_path = None

    templates = request.app.state.templates
    ctx = {
        "request": request,
        "project": summary,
        "experiment": exp,
        "experiment_status": experiment_status,
        "runs": runs,
        "has_report": has_report,
        "has_presentation": has_presentation,
        "has_log": has_log,
        "artifact_files": artifact_files,
        "running_by_exp": running_by_exp,
        # Banner reads the flat list — include it alongside the
        # per-button (type, exp_id) map.
        "active_ops": active,
        "active_lock_path": active_lock_path,
    }
    return templates.TemplateResponse("experiment_detail.html", ctx)
