"""JSON API routes — used by HTMX fragments and external callers."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import tomllib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from urika.core.experiment import create_experiment
from urika.core.models import VALID_AUDIENCES, VALID_MODES, ProjectConfig
from urika.core.registry import ProjectRegistry
from urika.core.revisions import record_revision, update_project_field
from urika.core.settings import load_settings, save_settings
from urika.core.workspace import _write_toml
from urika.dashboard.projects import list_project_summaries, load_project_summary
from urika.dashboard.runs import (
    spawn_advisor,
    spawn_build_tool,
    spawn_evaluate,
    spawn_experiment_run,
    spawn_finalize,
    spawn_present,
    spawn_report,
    spawn_summarize,
)

# Hardcoded list of agent roles whose model/endpoint can be overridden.
# Mirrors KNOWN_AGENTS in dashboard/routers/pages.py — kept duplicated to
# avoid the api → pages import (pages already imports from api in some
# call paths). If the list ever grows, update both places.
_KNOWN_AGENTS = {
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
}
_VALID_ENDPOINTS = {"open", "private"}  # 'inherit' means "no override".

# Finalize CLI accepts a wider audience set than core/models VALID_AUDIENCES.
# See ``src/urika/cli/agents_finalize.py`` --audience choices.
_FINALIZE_AUDIENCES = {"novice", "standard", "expert"}

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


# Project name pattern: lowercase alphanumeric + hyphens, must not start
# with a hyphen. Mirrors the HTML pattern attribute on the New project form.
_PROJECT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@router.post("/projects")
async def api_create_project(request: Request):
    """Synchronously materialize a new project workspace.

    Builds a :class:`ProjectConfig` from the form, calls
    :func:`create_project_workspace` to lay down the directory tree
    + ``urika.toml`` on disk, and registers the project in the
    central :class:`ProjectRegistry`.

    Builder-agent invocation (data profiling, source scanning,
    knowledge ingestion) is intentionally deferred to a future phase
    — for now the user goes straight to the project home and runs
    experiments from there.
    """
    body = await request.form()
    name = (body.get("name") or "").strip()
    question = (body.get("question") or "").strip()
    description = (body.get("description") or "").strip()
    mode = (body.get("mode") or "exploratory").strip()
    audience = (body.get("audience") or "expert").strip()
    data_paths_raw = (body.get("data_paths") or "").strip()
    # ``privacy_mode`` is optional — defaults to ``open`` for legacy
    # callers and the New Project modal that doesn't yet expose it.
    privacy_mode = (body.get("privacy_mode") or "open").strip()

    if not name or not question:
        raise HTTPException(status_code=422, detail="name and question are required")
    if not _PROJECT_NAME_RE.match(name):
        raise HTTPException(
            status_code=422,
            detail="name must be lowercase alphanumeric + hyphens (no leading hyphen)",
        )
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
    if privacy_mode not in _VALID_PRIVACY_MODES:
        raise HTTPException(
            status_code=422,
            detail=(f"privacy_mode must be one of {sorted(_VALID_PRIVACY_MODES)}"),
        )

    # Hard gate: private/hybrid require a configured private endpoint
    # in global settings. Without one the runtime would raise
    # MissingPrivateEndpointError on the first agent invocation, so we
    # may as well refuse the project creation up front with a fix
    # instruction the user can act on.
    if privacy_mode in ("private", "hybrid"):
        from urika.core.settings import get_named_endpoints

        if not any((ep.get("base_url") or "").strip() for ep in get_named_endpoints()):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Privacy mode '{privacy_mode}' requires at least "
                    f"one endpoint with a non-empty base_url to be "
                    f"configured. Add one on the global Privacy tab "
                    f"(/settings) before creating a project in this "
                    f"mode."
                ),
            )

    registry = ProjectRegistry()
    if name in registry.list_all():
        raise HTTPException(status_code=409, detail=f"Project '{name}' already exists")

    data_paths = [p.strip() for p in data_paths_raw.splitlines() if p.strip()]

    settings = load_settings()
    projects_root = Path(
        settings.get("projects_root", str(Path.home() / "urika-projects"))
    ).expanduser()
    projects_root.mkdir(parents=True, exist_ok=True)
    project_dir = projects_root / name

    if project_dir.exists():
        raise HTTPException(status_code=409, detail="Directory already exists on disk")

    cfg = ProjectConfig(
        name=name,
        question=question,
        mode=mode,
        description=description,
        data_paths=data_paths,
        audience=audience,
    )

    from urika.core.workspace import create_project_workspace

    create_project_workspace(project_dir, cfg)

    # Persist any free-text builder instructions the user supplied. The
    # dashboard's create-project flow doesn't currently invoke the
    # project_builder agent, so we stash the instructions on disk so a
    # future builder-agent integration (Phase 13B+) can pick them up
    # rather than dropping the input on the floor.
    instructions = (body.get("instructions") or "").strip()
    if instructions:
        urika_dir = project_dir / ".urika"
        urika_dir.mkdir(parents=True, exist_ok=True)
        (urika_dir / "builder_instructions.txt").write_text(
            instructions, encoding="utf-8"
        )

    # Persist the privacy_mode in the new project's urika.toml. The
    # workspace writer always writes [project] + [preferences]; we
    # tack on a [privacy] block when the user picked a non-open mode
    # so the runtime loader sees it on the next agent invocation.
    if privacy_mode != "open":
        toml_path = project_dir / "urika.toml"
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        data.setdefault("privacy", {})["mode"] = privacy_mode
        _write_toml(toml_path, data)

    # Seed the new project's [notifications].channels list from the
    # global per-channel ``auto_enable`` flags. Channels with
    # ``auto_enable=true`` start ON for new projects; the rest stay
    # off and the user can opt-in later from the project Notifications
    # tab. Mirrors the CLI behavior so dashboard + ``urika new`` stay
    # in lockstep.
    from urika.core.settings import get_default_notifications_auto_enable

    auto = get_default_notifications_auto_enable()
    auto_channels = [ch for ch, on in auto.items() if on]
    if auto_channels:
        toml_path = project_dir / "urika.toml"
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        data.setdefault("notifications", {})["channels"] = auto_channels
        _write_toml(toml_path, data)

    registry.register(name, project_dir)

    if request.headers.get("hx-request") == "true":
        return Response(status_code=201, headers={"HX-Redirect": f"/projects/{name}"})
    return JSONResponse({"name": name, "path": str(project_dir)}, status_code=201)


@router.delete("/projects/{name}")
async def api_delete_project(name: str, request: Request):
    """Move a registered project to ``~/.urika/trash/`` and unregister it.

    Thin wrapper over :func:`urika.core.project_delete.trash_project`.
    Active ``.lock`` files anywhere under the project folder block the
    operation (422). Missing-folder entries are registry-only cleaned
    up (200 with ``registry_only: true``).

    HTMX callers receive an ``HX-Redirect: /projects`` header so the
    page navigates back to the project list (which no longer contains
    the trashed project).
    """
    from urika.core.project_delete import (
        ActiveRunError,
        ProjectNotFoundError,
        trash_project,
    )

    try:
        result = trash_project(name)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown project")
    except ActiveRunError as e:
        raise HTTPException(status_code=422, detail=str(e))

    payload = {
        "name": result.name,
        "trash_path": str(result.trash_path) if result.trash_path else None,
        "registry_only": result.registry_only,
    }
    if request.headers.get("hx-request") == "true":
        return Response(
            status_code=200,
            headers={"HX-Redirect": "/projects"},
        )
    return JSONResponse(payload)


@router.delete("/projects/{name}/experiments/{exp_id}")
async def api_delete_experiment(name: str, exp_id: str, request: Request):
    """Move an experiment to ``<project>/trash/`` and return the result.

    Thin wrapper over :func:`urika.core.experiment_delete.trash_experiment`.
    Active ``.lock`` files anywhere under the experiment block the
    operation (422). Unknown project → 404, unknown experiment → 422.

    HTMX callers receive an ``HX-Redirect: /projects/<name>/experiments``
    header so the page navigates back to the experiments list (which no
    longer contains the trashed experiment).
    """
    from urika.core.experiment_delete import (
        ActiveExperimentError,
        ExperimentNotFoundError,
        trash_experiment,
    )

    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    if not (summary.path / "experiments" / exp_id).is_dir():
        raise HTTPException(status_code=422, detail="Unknown experiment")

    try:
        result = trash_experiment(summary.path, name, exp_id)
    except ExperimentNotFoundError:
        raise HTTPException(status_code=422, detail="Unknown experiment")
    except ActiveExperimentError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if request.headers.get("hx-request") == "true":
        return Response(
            status_code=200,
            headers={"HX-Redirect": f"/projects/{name}/experiments"},
        )
    return JSONResponse(
        {
            "experiment_id": result.experiment_id,
            "trash_path": str(result.trash_path),
        }
    )


@router.delete("/projects/{name}/sessions/{session_id}")
async def api_session_delete(name: str, session_id: str) -> Response:
    """Trash an orchestrator session by ID. 204 on success, 404 if missing."""
    from urika.core.orchestrator_sessions import delete_session

    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    if not delete_session(summary.path, session_id):
        raise HTTPException(status_code=404, detail="Unknown session")
    return Response(status_code=204)


@router.put("/projects/{name}/settings")
async def api_project_settings_put(name: str, request: Request):
    """Atomically update project settings and record per-field revisions.

    Handles five families of fields posted by the tabbed settings form:

    * **Basics**: ``question``, ``description``, ``mode``, ``audience`` —
      written via :func:`update_project_field` (one revision entry per
      changed field).
    * **Data**: ``data_paths`` (newline-separated → list under
      ``[project]``) and ``success_criteria`` (``key=value`` lines →
      string-valued inline table under ``[project]``).
    * **Models**: ``runtime_model`` (sets ``[runtime].model``) and
      bracketed ``model[<agent>]`` / ``endpoint[<agent>]`` pairs
      (written under ``[runtime.models.<agent>]``).
    * **Notifications**: per-channel ``project_notif_<ch>_enabled``
      checkbox for email/slack/telegram. Enabled channels go into
      ``[notifications].channels``; unchecked channels are simply
      absent (no sentinel). When no channel is enabled and no
      per-channel override is set, the entire ``[notifications]``
      block is removed. Per-channel overrides survive independently
      of the enabled checkbox so the user doesn't lose typed values
      when toggling a channel off. Form fields keep the legacy names
      (``extra_to``, ``override_chat_id``) but the persisted TOML uses
      the canonical channel-readable keys (``to``, ``chat_id``) — the
      config loader merges/overrides on those keys.
    * **Privacy**: ``project_privacy_mode`` ∈ {inherit, open, private,
      hybrid}; non-inherit values write a project-local ``[privacy]``
      override (mode + optional ``[privacy.endpoints.private]``).

    Validates ``mode`` and ``audience`` against the canonical core sets;
    only writes fields whose value actually changed. For the structured
    families (data_paths, success_criteria, runtime_model, models,
    notifications) we load → mutate → ``_write_toml`` once per family
    and record exactly one :func:`record_revision` entry per top-level
    field touched.

    Returns an HTML fragment for HTMX swap, or JSON if the client sets
    ``Accept: application/json``.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    form = await request.form()
    question = (form.get("question") or "").strip()
    description = (form.get("description") or "").strip()
    mode = form.get("mode") or ""
    audience = form.get("audience") or ""

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

    # ---- Basics fields (one revision per changed field) -----------------
    new_values = {
        "question": question,
        "description": description,
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

    # ---- Structured fields: re-load TOML, mutate, write once ------------
    _apply_structured_settings(summary.path, form)

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


def _apply_structured_settings(project_path, form) -> None:
    """Apply the Data / Models / Notifications form fields to urika.toml.

    Loads the current TOML, mutates only the sections whose form fields
    were submitted, writes once via :func:`_write_toml`, and records one
    :func:`record_revision` entry per top-level field that actually
    changed.

    The "top-level field" labels used in revisions.json are intentionally
    coarse (``data_paths``, ``success_criteria``, ``runtime.model``,
    ``runtime.models``, ``notifications``) so the audit log stays
    readable — we don't enumerate every per-agent override or every
    channel checkbox.
    """
    toml_path = project_path / "urika.toml"
    if not toml_path.exists():
        return

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)

    project_section = data.setdefault("project", {})
    runtime_section = data.setdefault("runtime", {})

    # Track top-level fields that changed; emit one revision each at end.
    revisions: list[tuple[str, str, str]] = []

    # ---- data_paths ----
    if "data_paths" in form:
        raw = form.get("data_paths") or ""
        new_paths = [line.strip() for line in raw.splitlines() if line.strip()]
        old_paths = project_section.get("data_paths", [])
        if new_paths != old_paths:
            if new_paths:
                project_section["data_paths"] = new_paths
            elif "data_paths" in project_section:
                del project_section["data_paths"]
            revisions.append(
                (
                    "data_paths",
                    f"{len(old_paths)} paths",
                    f"{len(new_paths)} paths",
                )
            )

    # ---- success_criteria ----
    if "success_criteria" in form:
        raw = form.get("success_criteria") or ""
        new_sc: dict[str, str] = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            if k:
                new_sc[k] = v
        old_sc = project_section.get("success_criteria", {}) or {}
        if new_sc != old_sc:
            if new_sc:
                project_section["success_criteria"] = new_sc
            elif "success_criteria" in project_section:
                del project_section["success_criteria"]
            revisions.append(
                (
                    "success_criteria",
                    f"{len(old_sc)} keys",
                    f"{len(new_sc)} keys",
                )
            )

    # ---- runtime.model (project-wide override) ----
    if "runtime_model" in form:
        new_rm = (form.get("runtime_model") or "").strip()
        old_rm = runtime_section.get("model", "")
        if new_rm != old_rm:
            if new_rm:
                runtime_section["model"] = new_rm
            elif "model" in runtime_section:
                del runtime_section["model"]
            revisions.append(("runtime.model", old_rm, new_rm))

    # ---- runtime.models.<agent> (per-agent overrides) ----
    # Pull bracketed form fields. Form keys arrive as e.g. "model[task_agent]".
    #
    # Server-side endpoint constraint enforcement (defensive — the UI
    # already restricts these dropdowns):
    #   private mode → strip endpoint=open from any agent (cloud is
    #     hidden in private mode; defeats the point otherwise)
    #   hybrid mode  → strip endpoint=open ONLY for data_agent (it's
    #     hard-locked private; tool_builder defaults to private but the
    #     user can switch it to open)
    #
    # We resolve the effective mode from the form (if submitted) or fall
    # back to the existing TOML's [privacy].mode (or "open" as the
    # ultimate default — same rule the Privacy tab uses).
    _effective_mode = (form.get("project_privacy_mode") or "").strip()
    if _effective_mode not in {"open", "private", "hybrid"}:
        _effective_mode = (data.get("privacy", {}) or {}).get("mode") or "open"
    _HYBRID_LOCKED_PRIVATE = {"data_agent"}

    # Build the set of valid endpoint values: ``open`` (implicit cloud)
    # plus every named endpoint defined in the global settings AND any
    # endpoint already present in (or about to be written by this PUT
    # to) the project's own [privacy.endpoints.*].  A per-agent endpoint
    # pointing at a totally undefined name is a 422 — typos would
    # otherwise silently route to the default and confuse users.
    from urika.core.settings import get_named_endpoints as _get_named_endpoints

    _project_defined_endpoints = {ep["name"] for ep in _get_named_endpoints()}
    # Project-local endpoints (existing TOML).
    _project_defined_endpoints |= set(
        (data.get("privacy", {}) or {}).get("endpoints", {}) or {}
    )
    # If this PUT switches to private/hybrid mode, the privacy block
    # will create [privacy.endpoints.private] — count that too so the
    # per-agent endpoint validation in the same submission accepts
    # ``private`` even when globals have no such endpoint defined.
    if _effective_mode in ("private", "hybrid"):
        _project_defined_endpoints.add("private")
    _project_valid_endpoints = {"open"} | _project_defined_endpoints

    new_models: dict[str, dict[str, str]] = {}
    has_model_fields = False
    for key in form.keys():
        if key.startswith("model[") and key.endswith("]"):
            has_model_fields = True
            agent = key[len("model[") : -1]
            if agent not in _KNOWN_AGENTS:
                continue
            model_val = (form.get(key) or "").strip()
            endpoint_val = (form.get(f"endpoint[{agent}]") or "").strip()
            row: dict[str, str] = {}
            if model_val:
                row["model"] = model_val
            if endpoint_val and endpoint_val != "inherit":
                if endpoint_val not in _project_valid_endpoints:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"endpoint[{agent}] must be one of "
                            f"{sorted(_project_valid_endpoints | {'inherit'})}"
                        ),
                    )
                # Enforce per-mode endpoint constraints (silently strip
                # disallowed open endpoints — the UI already prevents
                # this; the server side is the defensive check).
                if endpoint_val == "open":
                    if _effective_mode == "private":
                        endpoint_val = ""
                    elif (
                        _effective_mode == "hybrid" and agent in _HYBRID_LOCKED_PRIVATE
                    ):
                        endpoint_val = ""
                if endpoint_val:
                    row["endpoint"] = endpoint_val
            if row:
                new_models[agent] = row

    if has_model_fields:
        old_models = runtime_section.get("models", {}) or {}
        if new_models != old_models:
            if new_models:
                runtime_section["models"] = new_models
            elif "models" in runtime_section:
                del runtime_section["models"]
            revisions.append(
                (
                    "runtime.models",
                    f"{len(old_models)} agents",
                    f"{len(new_models)} agents",
                )
            )

    # ---- privacy ----
    # The Privacy tab posts ``project_privacy_mode`` ∈ {open, private,
    # hybrid}.  ``inherit`` is gone — there is no system-wide default
    # mode any more, so each project owns its mode in [privacy].
    if "project_privacy_mode" in form:
        new_mode = (form.get("project_privacy_mode") or "").strip()
        if new_mode not in {"open", "private", "hybrid"}:
            raise HTTPException(
                status_code=422,
                detail=(
                    "project_privacy_mode must be one of {'open', 'private', 'hybrid'}"
                ),
            )

        old_privacy = data.get("privacy", {}) or {}
        old_mode = old_privacy.get("mode") or "open"

        # Gate: switching to private/hybrid requires at least one usable
        # private endpoint to be reachable from somewhere — the form's
        # submitted URL, the project's existing TOML, or globals. Without
        # that the runtime would hard-fail with
        # MissingPrivateEndpointError on the first agent invocation;
        # mirroring the POST /api/projects gate (Phase 12.6) keeps
        # save-time behavior in lockstep with run-time behavior.
        if new_mode in ("private", "hybrid"):
            url_field = (
                "project_privacy_private_url"
                if new_mode == "private"
                else "project_privacy_hybrid_private_url"
            )
            form_url = (form.get(url_field) or "").strip()

            existing_endpoints = old_privacy.get("endpoints", {}) or {}
            existing_url = ""
            if isinstance(existing_endpoints, dict):
                for ep_cfg in existing_endpoints.values():
                    if isinstance(ep_cfg, dict):
                        if (ep_cfg.get("base_url") or "").strip():
                            existing_url = ep_cfg.get("base_url", "").strip()
                            break

            from urika.core.settings import get_named_endpoints

            has_global_url = any(
                (ep.get("base_url") or "").strip() for ep in get_named_endpoints()
            )

            if not (form_url or existing_url or has_global_url):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Privacy mode '{new_mode}' requires at least "
                        f"one endpoint with a non-empty base_url to be "
                        f"configured. Provide one in the form, in the "
                        f"project's urika.toml, or on the global Privacy "
                        f"tab (/settings) before switching to this mode."
                    ),
                )

        new_privacy: dict = {"mode": new_mode}
        if new_mode == "private":
            url_val = (form.get("project_privacy_private_url") or "").strip()
            key_val = (form.get("project_privacy_private_key_env") or "").strip()
            # Blank URL + globals available → skip the endpoint write so
            # the runtime loader inherits the global endpoint (commit 1).
            # Stops the silent-stub-write that left projects "saved"
            # but unrunnable. The save-time gate above already refused
            # blank+no-globals.
            if url_val:
                new_privacy["endpoints"] = {
                    "private": {
                        "base_url": url_val,
                        "api_key_env": key_val,
                    }
                }
        elif new_mode == "hybrid":
            url_val = (form.get("project_privacy_hybrid_private_url") or "").strip()
            key_val = (form.get("project_privacy_hybrid_private_key_env") or "").strip()
            if url_val:
                new_privacy["endpoints"] = {
                    "private": {
                        "base_url": url_val,
                        "api_key_env": key_val,
                    }
                }
        # 'open' has no endpoint metadata — mode alone is the override.

        if new_privacy != old_privacy:
            data["privacy"] = new_privacy
            revisions.append(("privacy", old_mode, new_mode))

    # ---- notifications (2-state: enabled / disabled) ----
    # Per-channel checkboxes: ``project_notif_<ch>_enabled`` ∈ {"on",
    # absent}. Channels list is the source of truth — channels in the
    # list are ON, anything else is OFF. The previous 3-state
    # inherit/enabled/disabled radio (and ``_disabled`` sentinel)
    # are gone: with global ``auto_enable`` driving creation-time
    # defaults, "inherit" no longer adds anything.
    has_new_notif = any(
        f"project_notif_{ch}_enabled" in form
        or f"project_notif_{ch}_extra_to" in form
        or f"project_notif_{ch}_override_chat_id" in form
        for ch in ("email", "slack", "telegram")
    )
    # Require at least one toggle field on the form to consider this
    # tab as having been submitted. The Notifications tab always
    # includes the 3 enabled checkboxes (even when unchecked, the
    # form arrives with no key for that name) — so we look for the
    # ``project_notif_email_extra_to`` field which is always present
    # as a hidden text input on the tab. As a robust signal, we also
    # detect the per-channel override fields.
    notif_tab_submitted = (
        "project_notif_email_extra_to" in form
        or "project_notif_telegram_override_chat_id" in form
        or has_new_notif
    )
    if notif_tab_submitted:
        channels: list[str] = []
        for ch in ("email", "slack", "telegram"):
            if form.get(f"project_notif_{ch}_enabled") == "on":
                channels.append(ch)

        new_notif: dict = {}
        if channels:
            new_notif["channels"] = channels

        # Per-channel overrides — stashed even when the channel itself
        # is off so the user doesn't lose their typing on a disable.
        # The form field is named ``extra_to`` (a misnomer — these
        # addresses are merged into the channel's ``to`` list by the
        # config loader, not stored separately). The canonical TOML key
        # is ``to``: matches what ``build_active_notification_config``
        # in src/urika/notifications/__init__.py merges from.
        email_extra = (form.get("project_notif_email_extra_to") or "").strip()
        email_extra_list = [a.strip() for a in email_extra.split(",") if a.strip()]
        if email_extra_list:
            new_notif["email"] = {"to": email_extra_list}

        # Telegram: form field ``override_chat_id`` is a UI label;
        # canonical TOML key is ``chat_id`` — the loader does
        # ``cfg.update(project_ch)`` so the project key must match the
        # channel-readable key.
        telegram_chat = (
            form.get("project_notif_telegram_override_chat_id") or ""
        ).strip()
        if telegram_chat:
            new_notif["telegram"] = {"chat_id": telegram_chat}

        old_notif = data.get("notifications", {}) or {}

        if not new_notif:
            # No channels enabled and no overrides — drop the block.
            if "notifications" in data:
                del data["notifications"]
                revisions.append(("notifications", str(old_notif), "{}"))
        elif new_notif != old_notif:
            data["notifications"] = new_notif
            revisions.append(
                (
                    "notifications",
                    str(old_notif),
                    str(new_notif),
                )
            )

    # Clean up empty runtime section so we don't litter urika.toml.
    if not runtime_section:
        data.pop("runtime", None)

    if not revisions:
        return  # No structured changes — leave the file alone.

    _write_toml(toml_path, data)

    for field, old_value, new_value in revisions:
        record_revision(
            project_path,
            field=field,
            old_value=str(old_value),
            new_value=str(new_value),
        )


_VALID_PRIVACY_MODES = {"open", "private", "hybrid"}


def _validate_privacy_endpoint(project_path: Path) -> None:
    """Refuse to spawn an agent run when the project's privacy mode
    requires a private endpoint that isn't usable.

    Loads the project's :class:`RuntimeConfig` (which already merges in
    global per-mode defaults) plus :func:`get_named_endpoints` from
    globals.  When ``privacy_mode`` is ``private`` or ``hybrid`` the
    union of project-local + global endpoints must include at least
    one entry with a non-empty ``base_url``; otherwise we raise
    ``HTTPException(422, ...)`` with a clear fix instruction.

    Mirrors the runtime loader's hard fail
    (:class:`MissingPrivateEndpointError`) — same gate, moved earlier
    in the flow so the user gets the error from the dashboard before
    a subprocess is even started.
    """
    from urika.agents.config import load_runtime_config
    from urika.core.settings import get_named_endpoints

    runtime_config = load_runtime_config(project_path)
    if runtime_config.privacy_mode not in ("private", "hybrid"):
        return

    # Project-local endpoints (from urika.toml) take precedence; fall
    # back to the global named endpoints.
    project_endpoints = runtime_config.endpoints or {}
    has_project_url = any(
        (ep.base_url or "").strip() for ep in project_endpoints.values()
    )
    has_global_url = any(
        (ep.get("base_url") or "").strip() for ep in get_named_endpoints()
    )

    if not (has_project_url or has_global_url):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Privacy mode '{runtime_config.privacy_mode}' "
                f"requires a configured private endpoint, but no "
                f"endpoint with a non-empty base_url is defined for "
                f"this project or in global settings. Configure one "
                f"on the global Privacy tab (/settings) before "
                f"running this project."
            ),
        )


def _redirect_if_running(
    project_name: str,
    project_path: Path,
    op_type: str,
    request: Request,
    *,
    experiment_id: str | None = None,
) -> Response | JSONResponse | None:
    """Return a redirect/409 response if an op of this type is already
    running for this project (and matching experiment, if applicable);
    otherwise return ``None`` and let the caller spawn.

    For HTMX requests the response is 200 + ``HX-Redirect`` to the
    running op's log URL — same UX as a fresh spawn would produce. For
    non-HTMX (curl, scripts) we return 409 with a JSON body so callers
    can detect the duplicate explicitly instead of receiving a 200 they
    can't distinguish from a real start.

    Pass ``experiment_id`` for per-experiment ops so two different
    experiments running the same op type in parallel don't block each
    other; leave it ``None`` for project-level ops.
    """
    from urika.dashboard.active_ops import list_active_operations

    for op in list_active_operations(project_name, project_path):
        if op.type != op_type:
            continue
        if experiment_id is not None and op.experiment_id != experiment_id:
            continue
        if request.headers.get("hx-request") == "true":
            return Response(status_code=200, headers={"HX-Redirect": op.log_url})
        return JSONResponse(
            {
                "status": "already_running",
                "log_url": op.log_url,
                "type": op_type,
            },
            status_code=409,
        )
    return None


# Reserved endpoint name: ``open`` is the implicit cloud (Claude)
# endpoint and may not be redefined by the user.
_RESERVED_ENDPOINT_NAMES = {"open"}
_ENDPOINT_NAME_RE = re.compile(r"^[a-z0-9_-]+$")


def _parse_endpoints_form(
    form,
) -> tuple[list[dict[str, str]], bool]:
    """Pull multi-endpoint rows from the global Privacy form.

    Returns ``(rows, has_endpoints_field)``. ``has_endpoints_field`` is
    ``True`` if any ``endpoints[<i>][...]`` field was present in the
    submission — used by the caller to distinguish "user submitted no
    endpoints" (legitimate delete-all) from "Privacy tab wasn't part
    of this submission".

    Each row in ``rows`` is a fully-populated dict with keys
    ``name`` / ``base_url`` / ``api_key_env`` / ``default_model``.

    Validates:
      * ``name`` matches ``^[a-z0-9_-]+$`` → 422 otherwise
      * ``name`` is not in :data:`_RESERVED_ENDPOINT_NAMES` → 422

    Empty-name rows (where the user clicked "+ Add" but never typed a
    name, then submitted) are silently dropped.

    Accepts two equivalent submission shapes:
      * ``endpoints_json`` — single field carrying a JSON-serialized
        list of ``{name, base_url, api_key_env, default_model}`` dicts.
        Used by the dashboard form (Alpine :name= binding inside x-for
        is brittle; JSON sidesteps the timing).
      * ``endpoints[<i>][<field>]`` — indexed bracketed names. Kept for
        manual API callers and tests.
    """
    # Prefer JSON if the form provides it.
    json_blob = form.get("endpoints_json")
    if json_blob is not None:
        import json

        try:
            parsed = json.loads(json_blob) if json_blob else []
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422, detail="endpoints_json must be valid JSON"
            )
        if not isinstance(parsed, list):
            raise HTTPException(status_code=422, detail="endpoints_json must be a list")
        rows: list[dict[str, str]] = []
        seen_names: set[str] = set()
        for item in parsed:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name:
                continue
            if not _ENDPOINT_NAME_RE.match(name):
                raise HTTPException(
                    status_code=422,
                    detail=f"endpoint name '{name}' must match ^[a-z0-9_-]+$",
                )
            if name in _RESERVED_ENDPOINT_NAMES:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"endpoint name '{name}' is reserved (it's the "
                        "implicit cloud endpoint name)"
                    ),
                )
            if name in seen_names:
                raise HTTPException(
                    status_code=422,
                    detail=f"endpoint name '{name}' appears more than once",
                )
            seen_names.add(name)
            rows.append(
                {
                    "name": name,
                    "base_url": (item.get("base_url") or "").strip(),
                    "api_key_env": (item.get("api_key_env") or "").strip(),
                    "default_model": (item.get("default_model") or "").strip(),
                }
            )
        return rows, True

    # Find every index that appears in the form. We accept any of the
    # four bracketed keys as evidence that the row exists.
    indexed_re = re.compile(
        r"^endpoints\[(\d+)\]\[(name|base_url|api_key_env|default_model)\]$"
    )
    indices: set[int] = set()
    has_field = False
    for key in form.keys():
        m = indexed_re.match(key)
        if m:
            has_field = True
            indices.add(int(m.group(1)))

    rows: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for idx in sorted(indices):
        name = (form.get(f"endpoints[{idx}][name]") or "").strip()
        if not name:
            # Silently skip rows the user added but never named.
            continue
        if not _ENDPOINT_NAME_RE.match(name):
            raise HTTPException(
                status_code=422,
                detail=(f"endpoint name '{name}' must match ^[a-z0-9_-]+$"),
            )
        if name in _RESERVED_ENDPOINT_NAMES:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"endpoint name '{name}' is reserved (it's the "
                    "implicit cloud endpoint name)"
                ),
            )
        if name in seen_names:
            raise HTTPException(
                status_code=422,
                detail=f"endpoint name '{name}' appears more than once",
            )
        seen_names.add(name)
        rows.append(
            {
                "name": name,
                "base_url": (form.get(f"endpoints[{idx}][base_url]") or "").strip(),
                "api_key_env": (
                    form.get(f"endpoints[{idx}][api_key_env]") or ""
                ).strip(),
                "default_model": (
                    form.get(f"endpoints[{idx}][default_model]") or ""
                ).strip(),
            }
        )
    return rows, has_field


@router.put("/settings")
async def api_global_settings_put(request: Request):
    """Atomically rewrite ``~/.urika/settings.toml`` from the 4-tab form.

    The page posts the full settings tree across four tabs (Privacy,
    Models, Preferences, Notifications). This handler:

    1. Validates required fields per privacy mode.
    2. Loads existing settings via :func:`load_settings`.
    3. Mutates the keys the user touched, preserving anything else.
    4. Calls :func:`save_settings` to write the merged dict.

    Validation:
      * ``default_audience`` ∈ ``VALID_AUDIENCES``
      * ``default_max_turns`` is a positive int

    The Privacy tab no longer carries a system-wide default mode — each
    project picks its own mode at creation.  This handler only persists
    the private endpoint connection details; per-mode model defaults
    live on the Models tab.

    Returns an HTML fragment for HTMX swap, or JSON if the client sets
    ``Accept: application/json``.
    """
    form = await request.form()

    # ---- Validate audience + max_turns ---------------------------------
    default_audience = (form.get("default_audience") or "").strip()
    if default_audience not in VALID_AUDIENCES:
        raise HTTPException(
            status_code=422,
            detail=f"audience must be one of {sorted(VALID_AUDIENCES)}",
        )

    try:
        max_turns = int(form.get("default_max_turns") or "")
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

    # ---- Privacy tab: multi-endpoint editor ----------------------------
    # Form fields arrive as ``endpoints[<i>][name]`` /
    # ``endpoints[<i>][base_url]`` / ``endpoints[<i>][api_key_env]`` /
    # ``endpoints[<i>][default_model]``.  We collect every index, then
    # diff-apply: endpoints in the submission overwrite/insert into
    # ``[privacy.endpoints.<name>]``; endpoints absent from the
    # submission get REMOVED so deletes work.
    #
    # Validation:
    #   * ``name`` must match ``^[a-z0-9_-]+$``
    #   * ``open`` is reserved (the implicit cloud endpoint name)
    #   * empty/whitespace ``name`` rows are silently ignored
    submitted_endpoints, has_endpoints_field = _parse_endpoints_form(form)

    # ---- Load existing settings and mutate -----------------------------
    s = load_settings()

    privacy = s.setdefault("privacy", {})
    endpoints = privacy.setdefault("endpoints", {})

    runtime = s.setdefault("runtime", {})
    runtime_models = runtime.setdefault("models", {})

    if has_endpoints_field:
        # Diff-apply: replace the endpoints map with what the user
        # submitted. Missing rows = deleted. Extra fields (e.g.
        # ``default_model``) survive.
        new_endpoints: dict[str, dict[str, str]] = {}
        for ep in submitted_endpoints:
            row: dict[str, str] = {
                "base_url": ep["base_url"],
                "api_key_env": ep["api_key_env"],
            }
            # ``default_model`` is optional — only persist when set.
            if ep["default_model"]:
                row["default_model"] = ep["default_model"]
            new_endpoints[ep["name"]] = row
        endpoints.clear()
        endpoints.update(new_endpoints)

    # Drop any stale [privacy].mode that older settings.toml files may
    # have carried — there is no system-wide default mode any more.
    privacy.pop("mode", None)
    if not endpoints:
        privacy.pop("endpoints", None)
    if not privacy:
        s.pop("privacy", None)

    # ---- Models tab: per-mode per-agent grids ------------------------
    # The form posts:
    #   runtime_modes_<mode>_model                    — default for mode
    #   runtime_modes_<mode>_models[<agent>][model]   — per-agent model
    #   runtime_modes_<mode>_models[<agent>][endpoint] — per-agent endpoint
    #
    # We parse each mode independently and write to
    #   [runtime.modes.<mode>].model
    #   [runtime.modes.<mode>.models.<agent>] = { model, endpoint }
    runtime_modes = runtime.setdefault("modes", {})

    # The set of valid per-agent endpoint values for *this* PUT.  It
    # covers the implicit cloud endpoint plus every endpoint the user
    # just defined (or that already lived in the TOML if the Privacy
    # tab wasn't part of this submission).  ``inherit`` is the
    # no-override sentinel.
    defined_endpoint_names = set(endpoints.keys())
    valid_endpoint_values = {"open"} | defined_endpoint_names

    for mode_name in ("open", "private", "hybrid"):
        default_field = f"runtime_modes_{mode_name}_model"
        if default_field not in form:
            # Mode block wasn't part of this submission — leave it alone.
            continue

        default_val = (form.get(default_field) or "").strip()
        mode_cfg = runtime_modes.setdefault(mode_name, {})

        if default_val:
            mode_cfg["model"] = default_val
        elif "model" in mode_cfg:
            del mode_cfg["model"]

        # Per-agent rows for this mode. Walk the form once and pick out
        # the bracketed names that belong here.
        prefix = f"runtime_modes_{mode_name}_models["
        new_per_agent: dict[str, dict[str, str]] = {}
        for key in form.keys():
            if not key.startswith(prefix) or not key.endswith("][model]"):
                continue
            # Extract <agent> from runtime_modes_<mode>_models[<agent>][model]
            agent = key[len(prefix) : -len("][model]")]
            if agent not in _KNOWN_AGENTS:
                continue
            model_val = (form.get(key) or "").strip()
            endpoint_val = (form.get(f"{prefix}{agent}][endpoint]") or "").strip()

            # Server-side enforcement of mode-specific endpoint constraints.
            # Private mode: ``open`` is hidden (defeats the point); coerce
            #   to ``private`` if defined, otherwise drop the override.
            # Hybrid mode: ONLY data_agent is hard-locked private —
            #   ``open`` collapses to ``private`` (when defined).
            #   tool_builder defaults to private but is user-switchable.
            # Open mode: any endpoint name is fine.
            if mode_name == "private" and endpoint_val == "open":
                endpoint_val = "private" if "private" in defined_endpoint_names else ""
            if mode_name == "hybrid" and agent == "data_agent":
                endpoint_val = "private" if "private" in defined_endpoint_names else ""

            if endpoint_val and endpoint_val not in valid_endpoint_values:
                # The user just renamed/removed an endpoint that this row
                # was previously pointing at — silently strip the override
                # instead of 422'ing. The runtime loader will fall back to
                # the mode default. This makes Privacy-tab edits non-
                # destructive to the rest of the form.
                endpoint_val = ""

            row: dict[str, str] = {}
            if model_val:
                row["model"] = model_val
            if endpoint_val:
                row["endpoint"] = endpoint_val
            if row:
                new_per_agent[agent] = row

        if new_per_agent:
            mode_cfg["models"] = new_per_agent
        elif "models" in mode_cfg:
            del mode_cfg["models"]

        if not mode_cfg:
            del runtime_modes[mode_name]

    # Legacy bare runtime_model field (kept for back-compat). Project
    # urika.toml still uses [runtime].model, so this lets the dashboard
    # configure that knob directly via the same form.
    runtime_model_field = (form.get("runtime_model") or "").strip()
    if runtime_model_field:
        runtime["model"] = runtime_model_field

    # Legacy bare model[<agent>] / endpoint[<agent>] (used by tests
    # written before the per-mode redesign). Still write to the flat
    # [runtime.models.<agent>] table for back-compat.
    for key in form.keys():
        if key.startswith("model[") and key.endswith("]"):
            agent = key[len("model[") : -1]
            if agent not in _KNOWN_AGENTS:
                continue
            model_val = (form.get(key) or "").strip()
            endpoint_val = (form.get(f"endpoint[{agent}]") or "").strip()
            row = {}
            if model_val:
                row["model"] = model_val
            if endpoint_val and endpoint_val != "inherit":
                if endpoint_val not in valid_endpoint_values:
                    # User likely renamed/removed an endpoint elsewhere
                    # in the same submission. Silently strip the now-
                    # invalid override (drop it) instead of 422'ing.
                    pass
                else:
                    row["endpoint"] = endpoint_val
            if row:
                runtime_models[agent] = row
            elif agent in runtime_models:
                del runtime_models[agent]

    # Clean up empty containers so the TOML stays tidy.
    if not runtime_models:
        runtime.pop("models", None)
    if not runtime_modes:
        runtime.pop("modes", None)
    if not runtime:
        s.pop("runtime", None)

    # ---- Preferences tab ----------------------------------------------
    prefs = s.setdefault("preferences", {})
    prefs["audience"] = default_audience
    prefs["max_turns_per_experiment"] = max_turns
    prefs["web_search"] = form.get("web_search") == "on"
    prefs["venv"] = form.get("venv") == "on"

    # ---- Notifications tab --------------------------------------------
    # Globally we only persist connection details. Per-channel
    # enablement is a per-project decision (see project settings).
    notifications = s.setdefault("notifications", {})

    # Each channel block also carries an ``auto_enable`` checkbox —
    # creation-time hint read by ``urika new`` and POST /api/projects
    # to seed the new project's channels list. The runtime notification
    # loader does NOT read this flag.
    email_auto_enable = form.get("notifications_email_auto_enable") == "on"
    slack_auto_enable = form.get("notifications_slack_auto_enable") == "on"
    telegram_auto_enable = form.get("notifications_telegram_auto_enable") == "on"

    # Email
    email_to_raw = (form.get("notifications_email_to") or "").strip()
    email_to = [a.strip() for a in email_to_raw.split(",") if a.strip()]
    smtp_port_raw = (form.get("notifications_email_smtp_port") or "").strip()
    try:
        smtp_port = int(smtp_port_raw) if smtp_port_raw else 587
    except ValueError:
        smtp_port = 587
    smtp_user_raw = (form.get("notifications_email_smtp_user") or "").strip()
    email_section = {
        "from_addr": (form.get("notifications_email_from") or "").strip(),
        "to": email_to,
        # Persist as ``smtp_server`` to match what EmailChannel and the
        # CLI config flow read at runtime — the form field is named
        # ``smtp_host`` for clarity but the canonical TOML key is
        # ``smtp_server`` (chosen by the original CLI implementation).
        "smtp_server": (form.get("notifications_email_smtp_host") or "").strip(),
        "smtp_port": smtp_port,
        # Canonical key — EmailChannel reads ``password_env``. (Earlier
        # versions wrote ``smtp_password_env`` here, which the channel
        # silently ignored, so saved credentials never reached SMTP.)
        "password_env": (
            form.get("notifications_email_smtp_password_env") or ""
        ).strip(),
        "auto_enable": email_auto_enable,
    }
    # Only persist username when explicitly set — empty means "fall back
    # to From address" via EmailChannel's own default. Storing an empty
    # string here would override the fallback with "".
    # Canonical key is ``username`` (matches EmailChannel); the form
    # field is ``smtp_user`` for clarity.
    if smtp_user_raw:
        email_section["username"] = smtp_user_raw
    # Only persist the section if something is set; otherwise drop it.
    # ``auto_enable`` and ``smtp_port`` alone aren't enough — those are
    # defaults that would survive even when the user hasn't entered any
    # connection details.
    has_email_data = any(
        v for k, v in email_section.items() if k not in ("smtp_port", "auto_enable")
    ) or (smtp_port != 587)
    if has_email_data or email_auto_enable:
        notifications["email"] = email_section
    elif "email" in notifications:
        del notifications["email"]

    # Slack
    # Canonical key is ``bot_token_env`` (matches SlackChannel). The form
    # field stays ``notifications_slack_token_env`` for backward-compat
    # with rendered HTML; only the persisted TOML key changes.
    slack_section: dict[str, object] = {
        "channel": (form.get("notifications_slack_channel") or "").strip(),
        "bot_token_env": (
            form.get("notifications_slack_token_env") or ""
        ).strip(),
        "auto_enable": slack_auto_enable,
    }
    # Inbound Socket Mode (optional). Empty fields are NOT written so the
    # TOML stays tidy — empty allow-lists in particular would be misleading
    # (the channel treats None as "no restriction").
    slack_app_token_env = (
        form.get("notifications_slack_app_token_env") or ""
    ).strip()
    if slack_app_token_env:
        slack_section["app_token_env"] = slack_app_token_env
    slack_allowed_channels_raw = (
        form.get("notifications_slack_allowed_channels") or ""
    ).strip()
    if slack_allowed_channels_raw:
        slack_section["allowed_channels"] = [
            s.strip()
            for s in slack_allowed_channels_raw.split(",")
            if s.strip()
        ]
    slack_allowed_users_raw = (
        form.get("notifications_slack_allowed_users") or ""
    ).strip()
    if slack_allowed_users_raw:
        slack_section["allowed_users"] = [
            s.strip()
            for s in slack_allowed_users_raw.split(",")
            if s.strip()
        ]
    has_slack_data = any(v for k, v in slack_section.items() if k != "auto_enable")
    if has_slack_data or slack_auto_enable:
        notifications["slack"] = slack_section
    elif "slack" in notifications:
        del notifications["slack"]

    # Telegram
    telegram_section = {
        "chat_id": (form.get("notifications_telegram_chat_id") or "").strip(),
        "bot_token_env": (
            form.get("notifications_telegram_bot_token_env") or ""
        ).strip(),
        "auto_enable": telegram_auto_enable,
    }
    has_telegram_data = any(
        v for k, v in telegram_section.items() if k != "auto_enable"
    )
    if has_telegram_data or telegram_auto_enable:
        notifications["telegram"] = telegram_section
    elif "telegram" in notifications:
        del notifications["telegram"]

    # Drop the notifications block entirely if no connection details
    # remain. Any pre-existing 'channels' list is left untouched —
    # global form does not write it.
    if not any(notifications.get(k) for k in ("email", "slack", "telegram")):
        # Preserve channels if a project relied on it
        if not notifications.get("channels"):
            s.pop("notifications", None)

    save_settings(s)

    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse(
            {
                "default_audience": default_audience,
                "default_max_turns": max_turns,
            }
        )
    return HTMLResponse(content='<span class="text-success">Saved</span>')


@router.post("/settings/notifications/test-send")
async def api_notifications_test_send(request: Request) -> JSONResponse:
    """Send a test notification through every channel that the form configures.

    Builds channels from un-saved form data so users can validate
    creds before clicking Save. NEVER writes to ``settings.toml``.

    Body fields (form-encoded). All optional; channels with missing
    required fields are skipped:

    * Email (needs ``from`` AND ``to``):
      ``notifications_email_from``, ``notifications_email_to``,
      ``notifications_email_smtp_host``, ``notifications_email_smtp_port``,
      ``notifications_email_smtp_user``,
      ``notifications_email_smtp_password_env``.
    * Slack (needs ``channel``):
      ``notifications_slack_channel``, ``notifications_slack_token_env``,
      ``notifications_slack_app_token_env``,
      ``notifications_slack_allowed_channels``,
      ``notifications_slack_allowed_users``.
    * Telegram (needs ``chat_id`` AND ``bot_token_env``):
      ``notifications_telegram_chat_id``,
      ``notifications_telegram_bot_token_env``.

    Response (always JSON, status 200)::

        {"channels": [
            {"name": "EmailChannel", "status": "ok" | "error", "message": "..."},
            ...
        ]}

    Channels that fail to construct (e.g. ``slack-sdk`` not installed)
    appear in the result with ``status="error"`` and an explanatory
    message rather than crashing the request.
    """
    from urika.notifications.bus import NotificationBus
    from urika.notifications.test_send import send_test_through_bus

    form = await request.form()

    # Refresh secrets.env into os.environ so credentials added to the
    # secrets file by `urika notifications` (in another shell) since the
    # dashboard process started become visible to channel constructors.
    # load_secrets only sets vars that aren't already in os.environ, so
    # pre-existing exports take precedence.
    from urika.core.secrets import load_secrets
    load_secrets()

    bus = NotificationBus(project_name="test")
    construction_errors: list[dict[str, str]] = []

    # ---- Email --------------------------------------------------------
    email_from = (form.get("notifications_email_from") or "").strip()
    email_to_raw = (form.get("notifications_email_to") or "").strip()
    if email_from and email_to_raw:
        try:
            from urika.notifications.email_channel import EmailChannel

            smtp_port_raw = (
                form.get("notifications_email_smtp_port") or ""
            ).strip()
            try:
                smtp_port = int(smtp_port_raw) if smtp_port_raw else 587
            except ValueError:
                smtp_port = 587
            cfg = {
                "from_addr": email_from,
                "to": [t.strip() for t in email_to_raw.split(",") if t.strip()],
                "smtp_server": (
                    form.get("notifications_email_smtp_host") or "smtp.gmail.com"
                ).strip(),
                "smtp_port": smtp_port,
                "username": (
                    form.get("notifications_email_smtp_user") or email_from
                ).strip(),
                "password_env": (
                    form.get("notifications_email_smtp_password_env") or ""
                ).strip(),
            }
            bus.add_channel(EmailChannel(cfg))
        except Exception as exc:  # noqa: BLE001 — surface construction failures
            construction_errors.append(
                {"name": "EmailChannel", "status": "error", "message": str(exc)}
            )

    # ---- Slack --------------------------------------------------------
    slack_channel = (form.get("notifications_slack_channel") or "").strip()
    if slack_channel:
        try:
            from urika.notifications.slack_channel import SlackChannel

            allowed_channels_raw = (
                form.get("notifications_slack_allowed_channels") or ""
            ).strip()
            allowed_users_raw = (
                form.get("notifications_slack_allowed_users") or ""
            ).strip()
            allowed_channels: list[str] | None = (
                [s.strip() for s in allowed_channels_raw.split(",") if s.strip()]
                or None
            )
            allowed_users: list[str] | None = (
                [s.strip() for s in allowed_users_raw.split(",") if s.strip()]
                or None
            )
            cfg = {
                "channel": slack_channel,
                "bot_token_env": (
                    form.get("notifications_slack_token_env") or ""
                ).strip(),
                "app_token_env": (
                    form.get("notifications_slack_app_token_env") or ""
                ).strip(),
                "allowed_channels": allowed_channels,
                "allowed_users": allowed_users,
            }
            bus.add_channel(SlackChannel(cfg))
        except Exception as exc:  # noqa: BLE001 — surface import / config errors
            construction_errors.append(
                {"name": "SlackChannel", "status": "error", "message": str(exc)}
            )

    # ---- Telegram -----------------------------------------------------
    tg_chat_id = (form.get("notifications_telegram_chat_id") or "").strip()
    tg_bot_token_env = (
        form.get("notifications_telegram_bot_token_env") or ""
    ).strip()
    if tg_chat_id and tg_bot_token_env:
        try:
            from urika.notifications.telegram_channel import TelegramChannel

            cfg = {
                "chat_id": tg_chat_id,
                "bot_token_env": tg_bot_token_env,
            }
            bus.add_channel(TelegramChannel(cfg))
        except Exception as exc:  # noqa: BLE001 — surface construction failures
            construction_errors.append(
                {
                    "name": "TelegramChannel",
                    "status": "error",
                    "message": str(exc),
                }
            )

    results = send_test_through_bus(bus)
    channels_list = [
        {"name": k, **v} for k, v in results.items()
    ] + construction_errors
    return JSONResponse({"channels": channels_list})


@router.post("/settings/test-anthropic-key")
async def api_test_anthropic_key() -> JSONResponse:
    """Verify the configured ANTHROPIC_API_KEY against api.anthropic.com.

    Mirrors the CLI's ``urika config api-key --test`` path. Calls
    :func:`urika.core.anthropic_check.verify_anthropic_api_key`, which
    sends a minimal ``/v1/messages`` request and returns
    ``(ok, message)``. Always responds 200 so the dashboard can render
    the result inline; the ``ok`` field carries pass/fail.

    Refreshes ``~/.urika/secrets.env`` first so the test reflects a
    key added since the dashboard process launched.
    """
    import os as _os

    from urika.core.anthropic_check import verify_anthropic_api_key
    from urika.core.secrets import load_secrets

    load_secrets()
    key = _os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return JSONResponse(
            {"ok": False, "message": "ANTHROPIC_API_KEY is not set."}
        )
    ok, message = verify_anthropic_api_key(key)
    return JSONResponse({"ok": ok, "message": message})


@router.post("/settings/test-endpoint")
async def api_test_endpoint(request: Request) -> JSONResponse:
    """Probe a private model endpoint for reachability.

    Pure read-only check used by the Privacy tab's "Test" button —
    the dashboard's analogue of the CLI's
    ``urika.cli._helpers._test_endpoint``.  NEVER writes to
    ``settings.toml``; the caller still has to save explicitly.

    Body fields (form-encoded):
      * ``base_url`` (required) — the endpoint URL to probe.
      * ``api_key_env`` (optional) — name of an env var that should
        carry the bearer token.  Empty / missing means "open
        endpoint, no key needed".

    Response (always JSON, status 200 even on unreachable):
      ``{reachable, api_key_env, api_key_set, details}``.

    ``details`` is a short generic string — never ``str(exception)``,
    which can carry creds embedded in misconfigured proxy URLs.
    """
    import os as _os

    from urika.cli._helpers import _probe_endpoint
    from urika.core.secrets import load_secrets

    # Refresh secrets vault into os.environ so a key added via
    # `urika config secret` (file backend OR OS keyring) since the
    # dashboard process started becomes visible to this check.
    # load_secrets only sets vars that aren't already in os.environ,
    # so pre-existing exports take precedence.
    load_secrets()

    form = await request.form()
    base_url = (form.get("base_url") or "").strip()
    raw_key_env = (form.get("api_key_env") or "").strip()
    api_key_env: str | None = raw_key_env or None

    if not base_url:
        raise HTTPException(status_code=422, detail="base_url is required")

    try:
        reachable, details = _probe_endpoint(base_url)
    except Exception as e:  # noqa: BLE001 — surface the type, not the message.
        reachable = False
        # Don't leak ``str(e)`` — could carry creds embedded in a
        # misconfigured proxy URL or auth header.
        details = f"error: {type(e).__name__}"

    api_key_set = False
    if api_key_env:
        api_key_set = bool(_os.environ.get(api_key_env, "").strip())

    return JSONResponse(
        {
            "reachable": reachable,
            "api_key_env": api_key_env,
            "api_key_set": api_key_set,
            "details": details,
        }
    )


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
    # The redesigned "+ New experiment" modal mirrors ``urika run``: no name,
    # no hypothesis, no mode. The planning agent picks a name + hypothesis
    # during the run, and mode is project-level, not per-experiment.
    form = await request.form()
    audience = form.get("audience") or ""
    max_turns = form.get("max_turns") or "10"
    instructions = (form.get("instructions") or "").strip()

    # Advanced options — mirror the corresponding ``urika run`` flags.
    auto = bool(form.get("auto"))
    max_experiments_raw = (form.get("max_experiments") or "").strip()
    auto_limit = (form.get("auto_limit") or "capped").strip()
    review_criteria = bool(form.get("review_criteria"))
    # Single checkbox: when on, ``urika run`` calls the advisor first
    # and the advisor's output streams in the experiment run log
    # alongside Planning / Task / Evaluator.
    advisor_first = bool(form.get("advisor_first"))
    # Resume is intentionally NOT read here — resume is a per-experiment
    # action exposed on the experiments list (failed / paused / stopped
    # rows get their own button), not a "new experiment" option.
    resume = False

    # Autonomous-unlimited mode: the user picked "Run until advisor
    # decides to stop". The CLI's meta-orchestrator only runs the
    # multi-experiment path when --max-experiments is set, but treats
    # the value as just a cap (meta_mode = "unlimited" if --auto). Send
    # a large cap so it acts as effectively unbounded.
    if auto and auto_limit == "unlimited":
        max_experiments_raw = "999"

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

    max_experiments_int: int | None = None
    if max_experiments_raw:
        try:
            max_experiments_int = int(max_experiments_raw)
            if max_experiments_int <= 0:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="max_experiments must be a positive integer",
            ) from exc

    # max_experiments only makes sense in autonomous mode — otherwise
    # the meta-orchestrator path isn't taken and the flag is dropped.
    if max_experiments_int is not None and not auto:
        raise HTTPException(
            status_code=422,
            detail="max_experiments requires --auto to be enabled",
        )

    # If a run is already in flight for any experiment in this project,
    # redirect to its live log instead of materializing a new experiment
    # dir and spawning a duplicate. Project-scoped check: the new
    # experiment_id isn't known yet (``create_experiment`` hasn't run),
    # so any active run blocks a fresh spawn — matches the user's
    # intent of "show me what's already running".
    existing = _redirect_if_running(name, summary.path, "run", request)
    if existing is not None:
        return existing

    # Pre-flight: if the project is in private/hybrid mode and no
    # private endpoint exists, fail before creating the experiment dir
    # so a stale .lock isn't left behind.
    _validate_privacy_endpoint(summary.path)

    # ``create_experiment`` still takes name + hypothesis as kwargs;
    # both are empty here. When ``advisor_first`` is set, the spawned
    # ``urika run`` calls the advisor first and writes the suggested
    # name + hypothesis back into experiment.json before the
    # orchestrator loop starts. Otherwise the orchestrator's turn-1
    # name-backfill picks the name from the first method.
    exp = create_experiment(summary.path, name="", hypothesis="")
    pid = spawn_experiment_run(
        name,
        summary.path,
        exp.experiment_id,
        instructions=instructions,
        max_turns=max_turns_int,
        audience=audience,
        auto=auto,
        max_experiments=max_experiments_int,
        review_criteria=review_criteria,
        resume=resume,
        advisor_first=advisor_first,
    )

    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse(
            {
                "experiment_id": exp.experiment_id,
                "status": "started",
                "pid": pid,
            }
        )
    # The "+ New experiment" modal posts via HTMX; on success we want the
    # browser to navigate the whole page to the live log. HTMX honours an
    # HX-Redirect response header by doing a full-page navigation.
    if request.headers.get("hx-request") == "true":
        log_url = f"/projects/{name}/experiments/{exp.experiment_id}/log"
        return Response(status_code=200, headers={"HX-Redirect": log_url})
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

    artifacts_dir = exp_dir / "artifacts"
    files = []
    if artifacts_dir.exists():
        for p in sorted(artifacts_dir.iterdir()):
            if p.is_file():
                files.append(
                    {
                        "name": p.name,
                        "size": p.stat().st_size,
                        "url": (
                            f"/projects/{name}/experiments/{exp_id}/artifacts/{p.name}"
                        ),
                    }
                )

    return {
        "has_report": (exp_dir / "report.md").exists(),
        "has_presentation": (exp_dir / "presentation.html").exists()
        or (exp_dir / "presentation" / "index.html").exists(),
        "has_log": (exp_dir / "run.log").exists(),
        "files": files,
    }


@router.get("/projects/{name}/artifacts/projectbook")
def api_projectbook_artifacts(name: str):
    """Report which projectbook artifact files exist for a project.

    Cheap on-disk probe — four ``Path.exists`` checks under
    ``<project>/projectbook``. Used by the summarize / finalize live
    log pages to decide which "view the result" buttons to reveal
    once the operation completes. Mirrors the per-experiment
    ``api_experiment_artifacts`` endpoint above.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    book = summary.path / "projectbook"

    return {
        "has_summary": (book / "summary.md").exists(),
        "has_report": (book / "report.md").exists(),
        "has_presentation": (book / "presentation.html").exists()
        or (book / "presentation" / "index.html").exists(),
        "has_findings": (book / "findings.json").exists(),
    }


@router.post("/projects/{name}/active-ops/clear-stale")
def api_clear_stale_locks(name: str) -> dict:
    """Remove run-lock files whose recorded PID is no longer alive.

    User-facing recovery for the case where a previous agent
    subprocess crashed without removing its ``.lock`` file. Without
    this, the running-op detector keeps reporting the project as
    "running" forever and the user can't start new experiments or
    resume the failed one.

    Only locks where the PID is dead, the file is empty, or the
    content is non-numeric get removed. Locks pointing at live PIDs
    are LEFT ALONE — this isn't a kill operation.
    """
    from urika.dashboard.active_ops import clear_stale_locks

    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    cleared = clear_stale_locks(summary.path)
    return {
        "cleared": [
            {
                "path": str(c.path),
                "pid": c.pid,
                "reason": c.reason,
            }
            for c in cleared
        ],
        "count": len(cleared),
    }


@router.get("/projects/{name}/active-ops")
def api_active_ops(name: str) -> list[dict]:
    """Return the project's currently-running agent operations.

    Polled by the in-page ``urika-active-ops-poll.js`` script every few
    seconds; when the returned set changes (op started OR finished) the
    page reloads so the running banner and trigger-button states catch
    up without a manual refresh. Server is read-only — same shape as
    ``list_active_operations`` minus ``lock_path`` (a server-side
    absolute path that's not useful to clients).
    """
    from urika.dashboard.active_ops import list_active_operations

    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    ops = list_active_operations(name, summary.path)
    return [
        {
            "type": op.type,
            "experiment_id": op.experiment_id,
            "log_url": op.log_url,
        }
        for op in ops
    ]


@router.get("/projects/{name}/usage/totals")
def api_usage_totals(name: str) -> dict:
    """Live usage totals for the project — polled by the log-page footer.

    Reads from ``urika.core.usage.get_totals`` which already aggregates
    the project's session records into ``tokens_in / tokens_out /
    cost_usd / agent_calls``. Read-only.
    """
    from urika.core.usage import get_totals

    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    totals = get_totals(summary.path)
    return {
        "tokens_in": totals.get("total_tokens_in", 0),
        "tokens_out": totals.get("total_tokens_out", 0),
        "cost_usd": totals.get("total_cost_usd", 0.0),
        "agent_calls": totals.get("total_agent_calls", 0),
    }


_EXPERIMENT_LOG_TYPES: dict[str, tuple[str, str]] = {
    # type → (log_filename, lock_filename)
    "run": ("run.log", ".lock"),
    "evaluate": ("evaluate.log", ".evaluate.lock"),
    "report": ("report.log", ".report.lock"),
    "present": ("present.log", ".present.lock"),
}


@router.get("/projects/{name}/runs/{exp_id}/stream")
async def api_run_stream(name: str, exp_id: str, type: str = "run"):
    """Server-sent-events tail of an experiment's per-agent log file.

    Emits each existing log line as ``data: <line>\\n\\n``, then polls
    every 0.5s for new content. When the lock file disappears (the run
    has finished), flushes any remaining lines and emits an
    ``event: status\\ndata: {"status":"completed"}\\n\\n`` event before
    closing the connection.

    ``type`` selects which log/lock pair to tail (default ``run``):

    * ``run`` → ``run.log`` + ``.lock``
    * ``evaluate`` → ``evaluate.log`` + ``.evaluate.lock``
    * ``report`` → ``report.log`` + ``.report.lock``
    * ``present`` → ``present.log`` + ``.present.lock``

    Unknown values silently fall back to ``run`` so a flaky query
    string can't 422 the page; the allow-list also keeps untrusted
    input from being interpolated into a filesystem path.

    The browser-side EventSource (Task 6.5) consumes this stream.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    log_name, lock_name = _EXPERIMENT_LOG_TYPES.get(type, _EXPERIMENT_LOG_TYPES["run"])
    log_path = summary.path / "experiments" / exp_id / log_name
    lock_path = summary.path / "experiments" / exp_id / lock_name

    async def event_stream():
        # Initial backlog — drain whatever's already on disk.
        position = 0
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    yield _format_log_line(line.rstrip())
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
                    yield _format_log_line(line)
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


_PROMPT_PREFIX = "URIKA-PROMPT:"


def _format_log_line(line: str) -> str:
    """Format a single run.log line as an SSE event.

    Lines beginning with ``URIKA-PROMPT:`` are emitted as ``event: prompt``
    SSE events with the trailing JSON payload as the data line, so the
    browser can render an inline answer form. All other lines are emitted
    as plain ``data:`` events.

    The orchestrator-side emission of ``URIKA-PROMPT:`` markers is
    deferred to Phase 12 — this consumer is shipped first so the
    dashboard side can be tested with a fabricated log line.
    """
    if line.startswith(_PROMPT_PREFIX):
        payload = line[len(_PROMPT_PREFIX) :].strip()
        return f"event: prompt\ndata: {payload}\n\n"
    return f"data: {line}\n\n"


@router.post("/projects/{name}/finalize")
async def api_project_finalize(name: str, request: Request):
    """Spawn ``urika finalize <project> --json`` for a project.

    Mirrors the ``/run`` endpoint shape: validates the project exists,
    pulls form fields (instructions, audience), and hands off to
    ``spawn_finalize`` which Popens the CLI and detaches a daemon thread
    to drain its stdout into ``projectbook/finalize.log``. Returns JSON
    with the spawned PID.

    ``audience`` follows the finalize CLI allow-list
    (``{"novice", "standard", "expert"}``), which differs from the core
    ``VALID_AUDIENCES`` set.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    body = await request.form()
    instructions = (body.get("instructions") or "").strip()
    audience_raw = (body.get("audience") or "").strip()
    audience = audience_raw or None
    draft = bool(body.get("draft"))
    if audience and audience not in _FINALIZE_AUDIENCES:
        raise HTTPException(
            status_code=422,
            detail=f"audience must be one of {sorted(_FINALIZE_AUDIENCES)}",
        )

    # If a finalize is already running for this project, redirect to
    # its live log instead of spawning a duplicate.
    existing = _redirect_if_running(name, summary.path, "finalize", request)
    if existing is not None:
        return existing

    # Pre-flight privacy gate — same rule as /run.
    _validate_privacy_endpoint(summary.path)

    pid = spawn_finalize(
        name,
        summary.path,
        instructions=instructions,
        audience=audience,
        draft=draft,
    )
    # The "Finalize project" button on the project home posts via HTMX;
    # on success we want the browser to navigate the whole page to the
    # live finalize log so the user can watch streaming output. HTMX
    # honours an HX-Redirect response header by doing a full-page
    # navigation.
    if request.headers.get("hx-request") == "true":
        log_url = f"/projects/{name}/finalize/log"
        return Response(status_code=200, headers={"HX-Redirect": log_url})
    return JSONResponse({"status": "started", "pid": pid})


@router.get("/projects/{name}/finalize/stream")
async def api_finalize_stream(name: str):
    """Server-sent-events tail of ``projectbook/finalize.log``.

    Same shape as ``/runs/<exp>/stream`` but reads from the project
    book and watches ``.finalize.lock`` for completion.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    log_path = summary.path / "projectbook" / "finalize.log"
    lock_path = summary.path / "projectbook" / ".finalize.lock"

    async def event_stream():
        position = 0
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    yield f"data: {line.rstrip()}\n\n"
                position = f.tell()

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
                yield (
                    f"event: status\ndata: {json.dumps({'status': 'completed'})}\n\n"
                )
                return
            await asyncio.sleep(0.5)

        yield (f"event: status\ndata: {json.dumps({'status': 'no_log'})}\n\n")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/projects/{name}/summarize")
async def api_project_summarize(name: str, request: Request):
    """Spawn ``urika summarize <project> --json`` for a project.

    Mirrors the ``/finalize`` endpoint shape: validates the project
    exists, pulls the optional ``instructions`` form field, and hands
    off to ``spawn_summarize`` which Popens the CLI and detaches a
    daemon thread to drain its stdout into ``projectbook/summarize.log``.
    Returns JSON with the spawned PID, or HX-Redirects to the live log
    when called from HTMX.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    body = await request.form()
    instructions = (body.get("instructions") or "").strip()

    # If a summarize is already running for this project, redirect to
    # its live log instead of spawning a duplicate.
    existing = _redirect_if_running(name, summary.path, "summarize", request)
    if existing is not None:
        return existing

    # Pre-flight privacy gate — same rule as /run, /finalize, /present.
    _validate_privacy_endpoint(summary.path)

    pid = spawn_summarize(
        name,
        summary.path,
        instructions=instructions,
    )
    if request.headers.get("hx-request") == "true":
        log_url = f"/projects/{name}/summarize/log"
        return Response(status_code=200, headers={"HX-Redirect": log_url})
    return JSONResponse({"status": "started", "pid": pid})


@router.get("/projects/{name}/summarize/stream")
async def api_summarize_stream(name: str):
    """Server-sent-events tail of ``projectbook/summarize.log``.

    Same shape as :func:`api_finalize_stream` but reads from
    ``projectbook/summarize.log`` and watches ``.summarize.lock`` for
    completion.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    log_path = summary.path / "projectbook" / "summarize.log"
    lock_path = summary.path / "projectbook" / ".summarize.lock"

    async def event_stream():
        position = 0
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    yield f"data: {line.rstrip()}\n\n"
                position = f.tell()

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
                yield (
                    f"event: status\ndata: {json.dumps({'status': 'completed'})}\n\n"
                )
                return
            await asyncio.sleep(0.5)

        yield (f"event: status\ndata: {json.dumps({'status': 'no_log'})}\n\n")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/projects/{name}/tools/build")
async def api_project_build_tool(name: str, request: Request):
    """Spawn ``urika build-tool <project> <instructions> --json``.

    Validates the project exists, requires a non-empty ``instructions``
    form field (the tool description — the build-tool CLI takes it as
    a positional argument and would otherwise block on an interactive
    prompt). Hands off to ``spawn_build_tool`` which Popens the CLI
    and detaches a daemon thread to drain stdout into
    ``<project>/tools/build.log``.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    body = await request.form()
    instructions = (body.get("instructions") or "").strip()
    if not instructions:
        raise HTTPException(status_code=422, detail="instructions is required")

    # If a build-tool run is already in flight for this project,
    # redirect to its live log instead of spawning a duplicate.
    existing = _redirect_if_running(name, summary.path, "build_tool", request)
    if existing is not None:
        return existing

    # Pre-flight privacy gate — tool_builder runs in private mode under
    # hybrid, so the gate must apply here too.
    _validate_privacy_endpoint(summary.path)

    pid = spawn_build_tool(
        name,
        summary.path,
        instructions=instructions,
    )
    if request.headers.get("hx-request") == "true":
        log_url = f"/projects/{name}/tools/build/log"
        return Response(status_code=200, headers={"HX-Redirect": log_url})
    return JSONResponse({"status": "started", "pid": pid})


@router.get("/projects/{name}/tools/build/stream")
async def api_build_tool_stream(name: str):
    """Server-sent-events tail of ``tools/build.log``.

    Same shape as :func:`api_finalize_stream` but reads from
    ``tools/build.log`` and watches ``tools/.build.lock`` for completion.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    log_path = summary.path / "tools" / "build.log"
    lock_path = summary.path / "tools" / ".build.lock"

    async def event_stream():
        position = 0
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    yield f"data: {line.rstrip()}\n\n"
                position = f.tell()

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
                yield (
                    f"event: status\ndata: {json.dumps({'status': 'completed'})}\n\n"
                )
                return
            await asyncio.sleep(0.5)

        yield (f"event: status\ndata: {json.dumps({'status': 'no_log'})}\n\n")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/projects/{name}/experiments/{exp_id}/report")
async def api_experiment_report(name: str, exp_id: str, request: Request):
    """Spawn ``urika report <project> --experiment <exp_id>``.

    Mirrors the per-experiment evaluate endpoint. Validates the project
    + experiment, pulls ``instructions`` and ``audience`` from the form,
    validates audience against the CLI's allow-list, and hands off to
    ``spawn_report``. When called from HTMX, redirects to the live log
    so the user can watch the report agent's stream.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    if not (summary.path / "experiments" / exp_id).is_dir():
        raise HTTPException(status_code=422, detail="Unknown experiment")

    body = await request.form()
    instructions = (body.get("instructions") or "").strip()
    audience_raw = (body.get("audience") or "").strip()
    audience = audience_raw or None
    if audience and audience not in _FINALIZE_AUDIENCES:
        raise HTTPException(
            status_code=422,
            detail=f"audience must be one of {sorted(_FINALIZE_AUDIENCES)}",
        )

    # If a report run is already in flight for THIS experiment, redirect
    # to its live log instead of spawning a duplicate. Different
    # experiments don't block each other.
    existing = _redirect_if_running(
        name,
        summary.path,
        "report",
        request,
        experiment_id=exp_id,
    )
    if existing is not None:
        return existing

    # Pre-flight privacy gate — same rule as /run, /finalize, /present.
    _validate_privacy_endpoint(summary.path)

    pid = spawn_report(
        name,
        summary.path,
        exp_id,
        instructions=instructions,
        audience=audience,
    )

    if request.headers.get("hx-request") == "true":
        log_url = f"/projects/{name}/experiments/{exp_id}/log?type=report"
        return Response(status_code=200, headers={"HX-Redirect": log_url})
    return JSONResponse({"status": "started", "pid": pid, "experiment_id": exp_id})


@router.post("/projects/{name}/experiments/{exp_id}/evaluate")
async def api_experiment_evaluate(name: str, exp_id: str, request: Request):
    """Spawn ``urika evaluate <project> <exp_id>`` for an experiment.

    Mirrors the ``/run`` endpoint shape: validates project + experiment,
    pulls the optional ``instructions`` form field, and hands off to
    ``spawn_evaluate`` which Popens the CLI and detaches a daemon thread
    to drain stdout into ``<exp>/evaluate.log``. When called from HTMX,
    responds with an ``HX-Redirect`` to the experiment's live log page so
    the user can watch the evaluator's stream.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    if not (summary.path / "experiments" / exp_id).is_dir():
        raise HTTPException(status_code=422, detail="Unknown experiment")

    # If an evaluate run is already in flight for THIS experiment,
    # redirect to its live log instead of spawning a duplicate.
    # Different experiments don't block each other.
    existing = _redirect_if_running(
        name,
        summary.path,
        "evaluate",
        request,
        experiment_id=exp_id,
    )
    if existing is not None:
        return existing

    # Pre-flight privacy gate — same rule as /run, /finalize, /present.
    _validate_privacy_endpoint(summary.path)

    body = await request.form()
    instructions = (body.get("instructions") or "").strip()

    pid = spawn_evaluate(
        name,
        summary.path,
        exp_id,
        instructions=instructions,
    )

    if request.headers.get("hx-request") == "true":
        log_url = f"/projects/{name}/experiments/{exp_id}/log?type=evaluate"
        return Response(status_code=200, headers={"HX-Redirect": log_url})
    return JSONResponse({"status": "started", "pid": pid, "experiment_id": exp_id})


@router.post("/projects/{name}/experiments/{exp_id}/resume")
async def api_experiment_resume(name: str, exp_id: str, request: Request):
    """Resume a paused / failed / stopped experiment.

    Spawns ``urika run --experiment <exp_id> --resume`` so the
    orchestrator picks up where it left off. Validates the project
    and experiment exist; runs the same privacy + already-running
    pre-flight checks as the new-experiment endpoint. Returns an
    HX-Redirect to the live log on HTMX, JSON elsewhere.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    if not (summary.path / "experiments" / exp_id).is_dir():
        raise HTTPException(status_code=422, detail="Unknown experiment")

    existing = _redirect_if_running(name, summary.path, "run", request)
    if existing is not None:
        return existing

    _validate_privacy_endpoint(summary.path)

    pid = spawn_experiment_run(
        name,
        summary.path,
        exp_id,
        resume=True,
    )
    if request.headers.get("hx-request") == "true":
        log_url = f"/projects/{name}/experiments/{exp_id}/log"
        return Response(status_code=200, headers={"HX-Redirect": log_url})
    return JSONResponse({"status": "started", "pid": pid, "experiment_id": exp_id})


@router.post("/projects/{name}/present")
async def api_project_present(name: str, request: Request):
    """Spawn ``urika present <project> --experiment <id>`` for an experiment.

    Mirrors the ``/run`` endpoint shape: validates the project and the
    experiment dir, then hands off to ``spawn_present`` which Popens
    the CLI and detaches a daemon thread to drain its stdout into
    ``<exp>/present.log``. Returns JSON with the spawned PID and
    experiment ID.

    ``audience`` follows the present CLI's allow-list (the same one
    finalize uses), which is wider than the core/models VALID_AUDIENCES set.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    body = await request.form()
    experiment_id = (body.get("experiment_id") or "").strip()
    if not experiment_id:
        raise HTTPException(status_code=422, detail="experiment_id is required")
    if not (summary.path / "experiments" / experiment_id).is_dir():
        raise HTTPException(status_code=422, detail="Unknown experiment")

    instructions = (body.get("instructions") or "").strip()
    audience_raw = (body.get("audience") or "").strip()
    audience = audience_raw or None
    if audience and audience not in _FINALIZE_AUDIENCES:
        raise HTTPException(
            status_code=422,
            detail=f"audience must be one of {sorted(_FINALIZE_AUDIENCES)}",
        )

    # If a present run is already in flight for THIS experiment,
    # redirect to its live log instead of spawning a duplicate.
    # Different experiments don't block each other.
    existing = _redirect_if_running(
        name,
        summary.path,
        "present",
        request,
        experiment_id=experiment_id,
    )
    if existing is not None:
        return existing

    # Pre-flight privacy gate — same rule as /run.
    _validate_privacy_endpoint(summary.path)

    pid = spawn_present(
        name,
        summary.path,
        experiment_id,
        instructions=instructions,
        audience=audience,
    )

    if request.headers.get("hx-request") == "true":
        log_url = f"/projects/{name}/experiments/{experiment_id}/log?type=present"
        return Response(status_code=200, headers={"HX-Redirect": log_url})
    return JSONResponse(
        {"status": "started", "pid": pid, "experiment_id": experiment_id}
    )


@router.post("/projects/{name}/advisor")
async def api_project_advisor(name: str, request: Request):
    """Spawn ``urika advisor <project> <question>`` as a subprocess.

    Mirrors the ``/summarize`` endpoint shape: validates the project
    exists, requires a non-empty ``question`` form field, refuses a
    duplicate spawn when one is already running, and hands off to
    ``spawn_advisor`` which Popens the CLI and detaches a daemon thread
    to drain its stdout into ``projectbook/advisor.log``.

    The CLI subprocess writes the user message + advisor reply to
    ``projectbook/advisor-history.json`` itself after the run
    completes; the dashboard's ``/advisor`` transcript view picks
    those entries up on next render.

    Returns JSON with the spawned PID, or HX-Redirects to the live
    log when called from HTMX so the user lands on the streaming
    page immediately.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    body = await request.form()
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="question is required")

    # If an advisor is already running for this project, redirect to
    # its live log instead of spawning a duplicate.
    existing = _redirect_if_running(name, summary.path, "advisor", request)
    if existing is not None:
        return existing

    # Pre-flight privacy gate — same rule as /run, /finalize, /summarize.
    _validate_privacy_endpoint(summary.path)

    pid = spawn_advisor(name, summary.path, question)

    if request.headers.get("hx-request") == "true":
        log_url = f"/projects/{name}/advisor/log"
        return Response(status_code=200, headers={"HX-Redirect": log_url})
    return JSONResponse({"status": "started", "pid": pid})


@router.get("/projects/{name}/advisor/stream")
async def api_advisor_stream(name: str):
    """Server-sent-events tail of ``projectbook/advisor.log``.

    Same shape as :func:`api_summarize_stream` but reads from
    ``projectbook/advisor.log`` and watches ``.advisor.lock`` for
    completion.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    log_path = summary.path / "projectbook" / "advisor.log"
    lock_path = summary.path / "projectbook" / ".advisor.lock"

    async def event_stream():
        position = 0
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    yield f"data: {line.rstrip()}\n\n"
                position = f.tell()

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
                yield (
                    f"event: status\ndata: {json.dumps({'status': 'completed'})}\n\n"
                )
                return
            await asyncio.sleep(0.5)

        yield (f"event: status\ndata: {json.dumps({'status': 'no_log'})}\n\n")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/projects/{name}/knowledge")
async def api_knowledge_add(name: str, request: Request):
    """Ingest a knowledge source (URL or local file path) via the form.

    Wraps :class:`urika.knowledge.store.KnowledgeStore.ingest`, which
    auto-detects the source type (URL / PDF / text) and writes the new
    entry to ``<project>/knowledge/index.json``. Returns ``HX-Redirect``
    back to the knowledge page when invoked from the modal so the new
    entry appears in the list immediately.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    body = await request.form()
    source = (body.get("source") or "").strip()
    if not source:
        raise HTTPException(status_code=422, detail="source is required")
    from urika.knowledge.store import KnowledgeStore

    store = KnowledgeStore(summary.path)
    try:
        entry = store.ingest(source)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}")
    if request.headers.get("hx-request") == "true":
        return Response(
            status_code=201,
            headers={"HX-Redirect": f"/projects/{name}/knowledge"},
        )
    return JSONResponse({"id": entry.id, "title": entry.title}, status_code=201)


@router.post("/projects/{name}/runs/{exp_id}/respond")
async def api_run_respond(name: str, exp_id: str, request: Request):
    """Record a user's answer to an inline prompt from the live log page.

    The browser-side prompt form (rendered by ``run_log.html`` when the
    SSE stream emits an ``event: prompt`` event) POSTs ``prompt_id`` and
    ``answer`` here. We persist the answer at
    ``<exp>/.prompts/<prompt_id>.answer`` so the orchestrator can pick
    it up on its next poll cycle.

    The orchestrator-side answer-file polling (and the symmetric
    ``URIKA-PROMPT:`` emission) is deferred to Phase 12 — this endpoint
    is shipped first so the dashboard side can be exercised end to end.

    Path-traversal protection: ``prompt_id`` may not contain ``/`` or
    ``..``. Empty ``prompt_id`` is a 422.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")
    body = await request.form()
    prompt_id = (body.get("prompt_id") or "").strip()
    answer = (body.get("answer") or "").strip()
    if not prompt_id:
        raise HTTPException(status_code=422, detail="prompt_id is required")
    # Path-traversal protection
    if "/" in prompt_id or ".." in prompt_id:
        raise HTTPException(status_code=400, detail="Invalid prompt_id")
    answers_dir = summary.path / "experiments" / exp_id / ".prompts"
    answers_dir.mkdir(parents=True, exist_ok=True)
    (answers_dir / f"{prompt_id}.answer").write_text(answer, encoding="utf-8")
    return {"status": "answer_recorded", "prompt_id": prompt_id}


@router.post("/projects/{name}/runs/{exp_id}/stop")
def api_run_stop(name: str, exp_id: str) -> dict:
    """Send SIGTERM to the running experiment subprocess.

    Reads the PID from ``<exp>/.lock`` and signals it. The orchestrator
    subprocess's in-flight HTTP request to the LLM gets a
    ``ConnectionResetError`` (which the runner catches) and the run
    tears down. The drainer thread cleans up the lock file. Status
    will be ``stopped`` in the orchestrator's final teardown — or
    ``failed`` if it dies before reaching its cleanup path. Both are
    resumable from the dashboard's Resume button.

    Returns ``{"status": "stop_signaled", "pid": pid}`` on success or
    ``{"status": "not_running"}`` when no live process is found
    (lock missing, unreadable, or PID dead).
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    lock_path = summary.path / "experiments" / exp_id / ".lock"
    if not lock_path.exists():
        return {"status": "not_running"}
    try:
        pid_text = lock_path.read_text(encoding="utf-8").strip()
        pid = int(pid_text)
    except (OSError, ValueError):
        return {"status": "not_running"}

    # Probe whether the PID is still alive by sending signal 0
    # (existence check; raises ProcessLookupError if the process is gone).
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return {"status": "not_running"}
    except PermissionError:
        # Process exists but we can't signal it — treat as "running"
        # and fall through to the SIGTERM attempt below.
        pass
    except OSError:
        return {"status": "not_running"}

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return {"status": "not_running"}

    return {"status": "stop_signaled", "pid": pid}


@router.post("/projects/{name}/runs/{exp_id}/pause")
def api_run_pause(name: str, exp_id: str) -> dict:
    """Request a graceful pause at the next turn boundary.

    Writes ``"pause"`` to ``<project>/.urika/pause_requested``. The
    orchestrator loop polls this file each turn and forwards the
    request into its in-memory ``PauseController``; the existing
    turn-loop check then pauses the session at the next safe
    checkpoint. The flag is project-level (only one active run per
    project today), so ``exp_id`` is echoed back for symmetry with
    the streaming/launcher URLs but does not influence the file path.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    flag_dir = summary.path / ".urika"
    flag_dir.mkdir(parents=True, exist_ok=True)
    (flag_dir / "pause_requested").write_text("pause", encoding="utf-8")

    return {"status": "pause_requested", "experiment_id": exp_id}
