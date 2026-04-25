"""JSON API routes — used by HTMX fragments and external callers."""

from __future__ import annotations

import asyncio
import json
import re
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
    spawn_experiment_run,
    spawn_finalize,
    spawn_present,
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

    if not name or not question:
        raise HTTPException(
            status_code=422, detail="name and question are required"
        )
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

    registry = ProjectRegistry()
    if name in registry.list_all():
        raise HTTPException(
            status_code=409, detail=f"Project '{name}' already exists"
        )

    data_paths = [
        p.strip() for p in data_paths_raw.splitlines() if p.strip()
    ]

    settings = load_settings()
    projects_root = Path(
        settings.get("projects_root", str(Path.home() / "urika-projects"))
    ).expanduser()
    projects_root.mkdir(parents=True, exist_ok=True)
    project_dir = projects_root / name

    if project_dir.exists():
        raise HTTPException(
            status_code=409, detail="Directory already exists on disk"
        )

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
    registry.register(name, project_dir)

    if request.headers.get("hx-request") == "true":
        return Response(
            status_code=201, headers={"HX-Redirect": f"/projects/{name}"}
        )
    return JSONResponse(
        {"name": name, "path": str(project_dir)}, status_code=201
    )


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
    * **Notifications**: per-channel ``project_notif_<ch>_state``
      ∈ {inherit, enabled, disabled} for email/slack/telegram. When all
      three are "inherit", the project has no override and the
      ``[notifications]`` block is removed; otherwise we write a project-
      local override with ``channels`` (enabled list) plus optional
      ``[notifications.email].extra_to`` and
      ``[notifications.telegram].override_chat_id``.
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
                if endpoint_val not in _VALID_ENDPOINTS:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"endpoint[{agent}] must be one of "
                            f"{sorted(_VALID_ENDPOINTS | {'inherit'})}"
                        ),
                    )
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

    # ---- privacy (Task 11D.1) ----
    # The Privacy tab posts ``project_privacy_mode`` ∈ {inherit, open,
    # private, hybrid}. ``inherit`` removes any [privacy] block — the
    # project falls back to the global config. The other three write a
    # project-local override.
    if "project_privacy_mode" in form:
        new_mode = (form.get("project_privacy_mode") or "").strip()
        if new_mode not in {"inherit", "open", "private", "hybrid"}:
            raise HTTPException(
                status_code=422,
                detail=(
                    "project_privacy_mode must be one of "
                    "{'inherit', 'open', 'private', 'hybrid'}"
                ),
            )

        old_privacy = data.get("privacy", {}) or {}
        old_mode = old_privacy.get("mode") if old_privacy else "inherit"
        if not old_mode:
            old_mode = "inherit"

        if new_mode == "inherit":
            if "privacy" in data:
                del data["privacy"]
                revisions.append(("privacy", old_mode, "inherit"))
        else:
            new_privacy: dict = {"mode": new_mode}
            if new_mode == "private":
                ep = {
                    "base_url": (
                        form.get("project_privacy_private_url") or ""
                    ).strip(),
                    "api_key_env": (
                        form.get("project_privacy_private_key_env") or ""
                    ).strip(),
                }
                new_privacy["endpoints"] = {"private": ep}
            elif new_mode == "hybrid":
                ep = {
                    "base_url": (
                        form.get("project_privacy_hybrid_private_url") or ""
                    ).strip(),
                    "api_key_env": (
                        form.get("project_privacy_hybrid_private_key_env") or ""
                    ).strip(),
                }
                new_privacy["endpoints"] = {"private": ep}
            # 'open' has no endpoint metadata — mode alone is the override.

            if new_privacy != old_privacy:
                data["privacy"] = new_privacy
                revisions.append(("privacy", old_mode, new_mode))

    # ---- notifications (Task 11D.2) ----
    # Per-channel state radios: ``project_notif_<ch>_state`` ∈ {inherit,
    # enabled, disabled}. When *every* channel is "inherit", the project
    # has no [notifications] override at all and we remove the block.
    has_new_notif = any(
        f"project_notif_{ch}_state" in form
        for ch in ("email", "slack", "telegram")
    )
    if has_new_notif:
        states = {
            ch: (form.get(f"project_notif_{ch}_state") or "inherit").strip()
            for ch in ("email", "slack", "telegram")
        }
        all_inherit = all(s == "inherit" for s in states.values())

        old_notif = data.get("notifications", {}) or {}

        if all_inherit:
            if "notifications" in data:
                del data["notifications"]
                revisions.append(("notifications", "override", "inherit"))
        else:
            new_notif: dict = {}
            channels: list[str] = []
            disabled: list[str] = []
            for ch, state in states.items():
                if state == "enabled":
                    channels.append(ch)
                elif state == "disabled":
                    disabled.append(ch)
            new_notif["channels"] = channels
            if disabled:
                # Sentinel: track explicitly-disabled channels so the page
                # can re-render the radio with the right value. Kept under
                # an underscore-prefixed key so it doesn't collide with a
                # real channel name.
                new_notif["_disabled"] = disabled

            # Per-channel overrides. We always pull these from the form
            # so the user can stash extras alongside an inherit/disable
            # choice (preferred over forcing them to leave the field blank).
            email_extra = (
                form.get("project_notif_email_extra_to") or ""
            ).strip()
            email_extra_list = [
                a.strip() for a in email_extra.split(",") if a.strip()
            ]
            if email_extra_list:
                new_notif["email"] = {"extra_to": email_extra_list}

            telegram_chat = (
                form.get("project_notif_telegram_override_chat_id") or ""
            ).strip()
            if telegram_chat:
                new_notif["telegram"] = {"override_chat_id": telegram_chat}

            if new_notif != old_notif:
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
      * ``privacy_mode`` ∈ ``{"open", "private", "hybrid"}``
      * ``default_audience`` ∈ ``VALID_AUDIENCES``
      * ``default_max_turns`` is a positive int
      * ``private`` mode requires endpoint URL + model
      * ``hybrid`` mode requires private endpoint URL + private model

    Returns an HTML fragment for HTMX swap, or JSON if the client sets
    ``Accept: application/json``.
    """
    form = await request.form()

    # ---- Validate privacy mode + audience + max_turns ------------------
    privacy_mode = (form.get("privacy_mode") or "").strip()
    if privacy_mode not in _VALID_PRIVACY_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"privacy_mode must be one of {sorted(_VALID_PRIVACY_MODES)}",
        )

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

    # ---- Privacy-mode-specific required fields -------------------------
    private_url = (form.get("privacy_private_url") or "").strip()
    private_key_env = (form.get("privacy_private_key_env") or "").strip()
    private_model = (form.get("privacy_private_model") or "").strip()
    open_model = (form.get("privacy_open_model") or "").strip()
    hybrid_cloud_model = (form.get("privacy_hybrid_cloud_model") or "").strip()
    hybrid_private_url = (form.get("privacy_hybrid_private_url") or "").strip()
    hybrid_private_key_env = (form.get("privacy_hybrid_private_key_env") or "").strip()
    hybrid_private_model = (form.get("privacy_hybrid_private_model") or "").strip()

    if privacy_mode == "private":
        if not private_url:
            raise HTTPException(
                status_code=422, detail="private mode requires privacy_private_url"
            )
        if not private_model:
            raise HTTPException(
                status_code=422, detail="private mode requires privacy_private_model"
            )
    elif privacy_mode == "hybrid":
        if not hybrid_private_url:
            raise HTTPException(
                status_code=422,
                detail="hybrid mode requires privacy_hybrid_private_url",
            )
        if not hybrid_private_model:
            raise HTTPException(
                status_code=422,
                detail="hybrid mode requires privacy_hybrid_private_model",
            )

    # ---- Load existing settings and mutate -----------------------------
    s = load_settings()

    # Privacy section
    privacy = s.setdefault("privacy", {})
    privacy["mode"] = privacy_mode
    endpoints = privacy.setdefault("endpoints", {})

    runtime = s.setdefault("runtime", {})
    runtime_models = runtime.setdefault("models", {})

    if privacy_mode == "open":
        # Cloud model goes to [runtime].model. Clear any private endpoint
        # entry to keep the file tidy (matches the CLI behavior).
        if open_model:
            runtime["model"] = open_model
        # Don't blow away other endpoints — just leave the section as-is.

    elif privacy_mode == "private":
        ep = endpoints.setdefault("private", {})
        ep["base_url"] = private_url
        ep["api_key_env"] = private_key_env
        if private_model:
            runtime["model"] = private_model

    elif privacy_mode == "hybrid":
        if hybrid_cloud_model:
            runtime["model"] = hybrid_cloud_model
        ep = endpoints.setdefault("private", {})
        ep["base_url"] = hybrid_private_url
        ep["api_key_env"] = hybrid_private_key_env
        # Wire data_agent → private model (mirrors the CLI hybrid setup).
        runtime_models["data_agent"] = {
            "model": hybrid_private_model,
            "endpoint": "private",
        }

    # ---- Models tab: top-level runtime_model + per-agent overrides ----
    runtime_model_field = (form.get("runtime_model") or "").strip()
    if runtime_model_field:
        # Explicit override of the privacy-block-computed model.
        runtime["model"] = runtime_model_field

    for key in form.keys():
        if key.startswith("model[") and key.endswith("]"):
            agent = key[len("model[") : -1]
            if agent not in _KNOWN_AGENTS:
                continue
            model_val = (form.get(key) or "").strip()
            endpoint_val = (form.get(f"endpoint[{agent}]") or "").strip()
            row: dict[str, str] = {}
            if model_val:
                row["model"] = model_val
            if endpoint_val and endpoint_val != "inherit":
                if endpoint_val not in _VALID_ENDPOINTS:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"endpoint[{agent}] must be one of "
                            f"{sorted(_VALID_ENDPOINTS | {'inherit'})}"
                        ),
                    )
                row["endpoint"] = endpoint_val
            if row:
                runtime_models[agent] = row
            elif agent in runtime_models and agent != "data_agent":
                # User cleared the row — drop the override (but don't blow
                # away the data_agent row we just wrote in hybrid mode).
                del runtime_models[agent]

    # Clean up empty containers so the TOML stays tidy.
    if not runtime_models:
        runtime.pop("models", None)
    if not runtime:
        s.pop("runtime", None)

    # ---- Preferences tab ----------------------------------------------
    prefs = s.setdefault("preferences", {})
    prefs["audience"] = default_audience
    prefs["max_turns_per_experiment"] = max_turns
    prefs["web_search"] = form.get("web_search") == "on"
    prefs["venv"] = form.get("venv") == "on"

    # ---- Notifications tab --------------------------------------------
    new_channels: list[str] = []
    notifications = s.setdefault("notifications", {})

    # Email
    if form.get("notifications_email_enabled") == "on":
        new_channels.append("email")
    email_to_raw = (form.get("notifications_email_to") or "").strip()
    email_to = [a.strip() for a in email_to_raw.split(",") if a.strip()]
    smtp_port_raw = (form.get("notifications_email_smtp_port") or "").strip()
    try:
        smtp_port = int(smtp_port_raw) if smtp_port_raw else 587
    except ValueError:
        smtp_port = 587
    email_section = {
        "from_addr": (form.get("notifications_email_from") or "").strip(),
        "to": email_to,
        "smtp_host": (form.get("notifications_email_smtp_host") or "").strip(),
        "smtp_port": smtp_port,
        "smtp_user": (form.get("notifications_email_smtp_user") or "").strip(),
        "smtp_password_env": (
            form.get("notifications_email_smtp_password_env") or ""
        ).strip(),
    }
    # Only persist the section if something is set; otherwise drop it.
    if (
        any(v for k, v in email_section.items() if k != "smtp_port" or v != 587)
        or "email" in new_channels
    ):
        notifications["email"] = email_section
    elif "email" in notifications:
        del notifications["email"]

    # Slack
    if form.get("notifications_slack_enabled") == "on":
        new_channels.append("slack")
    slack_section = {
        "channel": (form.get("notifications_slack_channel") or "").strip(),
        "token_env": (form.get("notifications_slack_token_env") or "").strip(),
    }
    if any(slack_section.values()) or "slack" in new_channels:
        notifications["slack"] = slack_section
    elif "slack" in notifications:
        del notifications["slack"]

    # Telegram
    if form.get("notifications_telegram_enabled") == "on":
        new_channels.append("telegram")
    telegram_section = {
        "chat_id": (form.get("notifications_telegram_chat_id") or "").strip(),
        "bot_token_env": (
            form.get("notifications_telegram_bot_token_env") or ""
        ).strip(),
    }
    if any(telegram_section.values()) or "telegram" in new_channels:
        notifications["telegram"] = telegram_section
    elif "telegram" in notifications:
        del notifications["telegram"]

    notifications["channels"] = new_channels
    if (
        not any(notifications.get(k) for k in ("email", "slack", "telegram"))
        and not new_channels
    ):
        s.pop("notifications", None)

    save_settings(s)

    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse(
            {
                "privacy_mode": privacy_mode,
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
    if audience and audience not in _FINALIZE_AUDIENCES:
        raise HTTPException(
            status_code=422,
            detail=f"audience must be one of {sorted(_FINALIZE_AUDIENCES)}",
        )

    pid = spawn_finalize(
        name, summary.path, instructions=instructions, audience=audience
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

    pid = spawn_present(
        name,
        summary.path,
        experiment_id,
        instructions=instructions,
        audience=audience,
    )
    return JSONResponse(
        {"status": "started", "pid": pid, "experiment_id": experiment_id}
    )


@router.post("/projects/{name}/advisor")
async def api_project_advisor(name: str, request: Request):
    """Run the advisor agent inline and return the response markdown.

    Unlike finalize/present (which spawn subprocesses for long-running
    work), the advisor is short and we call it synchronously inside
    the request handler. The advisor agent's runner uses asyncio so
    the route is async too — no threadpool hop needed.

    Returns ``{"response": <markdown_str>}`` on success. The browser
    typically renders this in a modal or appends it to a chat panel.
    """
    registry = ProjectRegistry().list_all()
    summary = load_project_summary(name, registry)
    if summary is None or summary.missing:
        raise HTTPException(status_code=404, detail="Unknown project")

    body = await request.form()
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="question is required")

    try:
        response_md = await _run_advisor_inline(summary.path, name, question)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"response": response_md}


async def _run_advisor_inline(project_path, project_name: str, question: str) -> str:
    """Build advisor config + context, await ``runner.run``, return text.

    Pulled out of the route so tests can stub this single function
    instead of mocking the whole agent stack. Mirrors the in-process
    pattern used by ``urika.cli.agents.advisor`` but trimmed for the
    dashboard's request/response cycle (no rolling-summary update,
    no suggestion offer, no usage recording).
    """
    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
    except ImportError as exc:
        raise RuntimeError(
            "Claude Agent SDK not installed. Run: pip install claude-agent-sdk"
        ) from exc

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("advisor_agent")
    if role is None:
        raise RuntimeError("Advisor agent not found in registry.")

    config = role.build_config(project_dir=project_path, experiment_id="")
    config.max_turns = 25  # Standalone chat needs more turns than in-loop advisor.

    context = f"Project: {project_name}\n"
    try:
        from urika.core.advisor_memory import load_context_summary

        summary_text = load_context_summary(project_path)
        if summary_text:
            context += (
                f"\n## Research Context (from previous sessions)\n\n{summary_text}\n\n"
            )
    except Exception:
        pass
    context += f"\nUser: {question}\n"

    result = await runner.run(config, context, on_message=lambda m: None)

    if not result.success:
        raise RuntimeError(result.error or "Advisor failed")
    return (result.text_output or "").strip()


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
