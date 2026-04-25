"""FastAPI app factory for the Urika dashboard v2.

The factory takes the projects root (where individual project
directories live, normally ``~/urika-projects/``) so tests can pass
a tmp dir. Routers attach to the app inside this function.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_PKG_DIR = Path(__file__).parent
_TEMPLATES_DIR = _PKG_DIR / "templates"
_STATIC_DIR = _PKG_DIR / "static"


def create_app(project_root: Path | None) -> FastAPI:
    """Create a configured FastAPI app for the dashboard.

    ``project_root`` is the directory that contains all registered
    Urika projects (e.g. ``~/urika-projects``). The dashboard reads
    the project registry to enumerate them; it never writes outside a
    project's own directory.
    """
    app = FastAPI(title="Urika Dashboard", docs_url=None, redoc_url=None)
    app.state.project_root = project_root
    app.state.templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
