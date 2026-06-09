"""FastAPI app factory for the Urika dashboard v2.

The factory takes the projects root (where individual project
directories live, normally ``~/urika-projects/``) so tests can pass
a tmp dir. Routers attach to the app inside this function.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from urika.dashboard.filters import humanize, tag_status

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_PKG_DIR = Path(__file__).parent
_TEMPLATES_DIR = _PKG_DIR / "templates"
_STATIC_DIR = _PKG_DIR / "static"


def _make_auth_dependency(expected: str):
    """Build a FastAPI dependency that requires a matching token.

    The token can arrive via three channels, in priority order:

    1. ``Authorization: Bearer <token>`` header (programmatic clients,
       RPC tooling, ``curl``).
    2. A ``urika_token`` cookie (set after the first valid ``?token=``
       request — keeps HTMX/Alpine XHRs authenticated without rewriting
       every URL).
    3. A ``token`` query param (the link the CLI/TUI prints for the
       user to open in the browser).

    All comparisons use :func:`secrets.compare_digest` so callers can't
    time-leak the expected value. Routes that should be exempt
    (``/healthz``, ``/static/...``) are registered without this
    dependency.

    The captured token is bound as ``expected`` (not ``token``) so it
    doesn't shadow the ``token`` query-param parameter below.
    """

    def require_auth(
        authorization: str | None = Header(default=None),
        token: str | None = Query(default=None),
        urika_token: str | None = Cookie(default=None),
    ) -> None:
        candidate = None
        if authorization is not None:
            scheme, _, value = authorization.partition(" ")
            if scheme.lower() == "bearer":
                candidate = value
        if candidate is None:
            candidate = urika_token or token
        if candidate is None or not secrets.compare_digest(candidate, expected):
            raise HTTPException(status_code=401, detail="Invalid or missing token")

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
    # One-shot migration of stale ``claude-opus-4-7`` model pins (a
    # 0.3.0/0.3.1 dashboard default that breaks with the bundled CLI).
    # Idempotent via marker file. Runs once when the dashboard process
    # starts so users who launch the dashboard before any CLI command
    # also get migrated.
    from urika.core.settings import migrate_settings

    migrate_settings()

    app = FastAPI(title="Urika Dashboard", docs_url=None, redoc_url=None)
    app.state.project_root = project_root
    app.state.auth_token = auth_token
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.state.templates.env.filters["humanize"] = humanize
    app.state.templates.env.filters["tag_status"] = tag_status
    try:
        from importlib.metadata import version as _pkg_version

        _version = _pkg_version("urika")
    except Exception:
        _version = "dev"
    app.state.templates.env.globals["urika_version"] = _version
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

        # When the user opens the printed ``?token=<t>`` link, the auth
        # dependency lets the request through; this middleware then
        # pins a ``urika_token`` cookie on the response so subsequent
        # HTMX/Alpine XHRs (which carry no query param) stay
        # authenticated. Only set it when the query token matches and
        # the request didn't already present the cookie.
        @app.middleware("http")
        async def _set_token_cookie(request, call_next):  # noqa: ANN001
            response = await call_next(request)
            qp_token = request.query_params.get("token")
            if (
                qp_token is not None
                and secrets.compare_digest(qp_token, auth_token)
                and request.cookies.get("urika_token") != auth_token
            ):
                response.set_cookie(
                    "urika_token",
                    auth_token,
                    httponly=True,
                    samesite="strict",
                )
            return response

    # CSRF defense-in-depth: reject cross-origin state-changing requests.
    # Applies in BOTH authenticated and unauthenticated modes (it is
    # independent of the token), so it lives outside the ``if auth_token``
    # block above. Registered AFTER the cookie middleware so that, under
    # the reverse-order semantics of ``@app.middleware("http")``, it runs
    # FIRST and rejects a forged cross-origin POST before any other layer.
    #
    # Only non-safe methods are checked. Browsers always attach an
    # ``Origin`` header to cross-origin state-changing requests, so a
    # mismatch between the Origin netloc and the request ``Host`` is the
    # CSRF signal. Requests with no ``Origin`` header (curl, server-side
    # clients, some same-origin navigations) are allowed through.
    @app.middleware("http")
    async def _origin_guard(request, call_next):  # noqa: ANN001
        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None:
                host = request.headers.get("host", "")
                # Hostnames are case-insensitive (RFC 3986 §3.2.2);
                # some clients send an upper/mixed-case Origin host.
                if urlparse(origin).netloc.lower() != host.lower():
                    from starlette.responses import JSONResponse

                    return JSONResponse(
                        {"detail": "cross-origin request rejected"},
                        status_code=403,
                    )
        return await call_next(request)

    from urika.dashboard.routers import pages, api, docs as docs_router

    app.include_router(pages.router, dependencies=deps)
    app.include_router(api.router, dependencies=deps)
    app.include_router(docs_router.router, dependencies=deps)

    return app
