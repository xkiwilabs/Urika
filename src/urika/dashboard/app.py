"""FastAPI app factory for the Urika dashboard v2.

The factory takes the projects root (where individual project
directories live, normally ``~/urika-projects/``) so tests can pass
a tmp dir. Routers attach to the app inside this function.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from urika.dashboard.filters import humanize

_PKG_DIR = Path(__file__).parent
_TEMPLATES_DIR = _PKG_DIR / "templates"
_STATIC_DIR = _PKG_DIR / "static"


def _make_auth_dependency(token: str):
    """Build a FastAPI dependency that requires ``Authorization: Bearer <token>``.

    The token comparison uses :func:`secrets.compare_digest` so callers
    can't time-leak the expected value. Routes that should be exempt
    (``/healthz``, ``/static/...``) are registered without this
    dependency.
    """

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization is None:
            raise HTTPException(status_code=401, detail="Authorization required")
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(value, token):
            raise HTTPException(status_code=401, detail="Invalid token")

    return require_auth


def create_app(
    project_root: Path | None,
    auth_token: str | None = None,
) -> FastAPI:
    """Create a configured FastAPI app for the dashboard.

    ``project_root`` is the directory that contains all registered
    Urika projects (e.g. ``~/urika-projects``). The dashboard reads
    the project registry to enumerate them; it never writes outside a
    project's own directory.

    ``auth_token``, if provided, requires every page and API route to
    carry ``Authorization: Bearer <token>``. ``/healthz`` and
    ``/static/...`` are exempt so health probes and CSS still work.
    """
    app = FastAPI(title="Urika Dashboard", docs_url=None, redoc_url=None)
    app.state.project_root = project_root
    app.state.auth_token = auth_token
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.state.templates.env.filters["humanize"] = humanize
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # /healthz is registered before the authenticated routers so it
    # never picks up the Bearer requirement. Health probes don't carry
    # tokens.
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    deps = []
    if auth_token:
        deps.append(Depends(_make_auth_dependency(auth_token)))

    from urika.dashboard.routers import pages, api
    app.include_router(pages.router, dependencies=deps)
    app.include_router(api.router, dependencies=deps)

    return app
