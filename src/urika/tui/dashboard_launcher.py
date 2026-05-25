"""Launch the dashboard FastAPI app on a random free port in a
background daemon thread, and open the browser at the right URL.

Used by:

- TUI ``/dashboard`` slash command (Task 8.1)
- ``urika dashboard`` CLI (Task 8.3)
- ``urika new`` post-creation prompt (Task 8.2 — though that one
  spawns the CLI as a subprocess instead, to keep the parent
  command from blocking on uvicorn)
"""

from __future__ import annotations

import socket
import threading
import time
import webbrowser
from contextlib import closing
from typing import Any


def _find_free_port() -> int:
    """Return an available TCP port on 127.0.0.1.

    Asks the OS for any free port by binding to port 0, then closes
    the socket. There is a tiny TOCTOU window before uvicorn binds,
    but it's harmless in practice (a retry would just pick another
    port).
    """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_dashboard_server(
    *,
    port: int | None = None,
    open_path: str = "/projects",
    open_browser: bool = True,
    auth_token: str | None = None,
    no_auth: bool = False,
) -> tuple[Any, threading.Thread, int]:
    """Start the FastAPI dashboard on a background daemon thread.

    Parameters
    ----------
    port:
        Port to bind. If ``None`` a random free port is picked.
    open_path:
        Path component of the URL to open in the browser
        (e.g. ``"/projects"`` or ``"/projects/<name>"``).
    open_browser:
        If ``True`` (default), call ``webbrowser.open`` once the
        server reports started. Set to ``False`` for tests.
    auth_token:
        If set, every page and API request must carry the token via
        ``Authorization: Bearer <token>``, a ``urika_token`` cookie, or
        a ``?token=`` query param. ``/healthz`` and ``/static/...``
        remain accessible without it. If ``None`` (and ``no_auth`` is
        False) a random token is generated here so the default launch
        is never fully open.
    no_auth:
        If ``True``, launch without auth even when ``auth_token`` is
        ``None`` (fully open on 127.0.0.1). Callers that already made
        the auth decision (e.g. the CLI ``dashboard`` command) pass an
        explicit ``auth_token`` and leave this False.

    Returns
    -------
    tuple
        ``(server, thread, port)`` where ``server`` is the
        ``uvicorn.Server`` instance (caller can set
        ``server.should_exit = True`` to stop), ``thread`` is the
        daemon thread running the event loop, and ``port`` is the
        actual port chosen.

    The generated/effective ``auth_token`` is also stashed on the
    returned server as ``server.urika_auth_token`` so callers can print
    the tokenized URL.
    """
    import secrets as _secrets

    import uvicorn

    from urika.dashboard.app import create_app

    if port is None:
        port = _find_free_port()

    # Default-secure: when no token was supplied and the caller didn't
    # opt out, generate one so the launch path is never fully open.
    # ``create_app``'s own ``auth_token=None`` default is left intact
    # for tests — the decision lives in the launch path, not the
    # factory.
    if auth_token is None and not no_auth:
        auth_token = _secrets.token_urlsafe(24)

    # Registry is read from URIKA_HOME; project_root=None lets the
    # dashboard use the registered project directories.
    app = create_app(project_root=None, auth_token=auth_token)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    # Stash the effective token so callers can print the tokenized URL.
    server.urika_auth_token = auth_token

    def _run() -> None:
        # uvicorn manages its own event loop; run it in the daemon thread.
        server.run()

    t = threading.Thread(target=_run, daemon=True, name="urika-dashboard-server")
    t.start()

    # Wait briefly for the server to be ready before opening the browser.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if getattr(server, "started", False):
            break
        time.sleep(0.05)

    if open_browser:
        url = f"http://127.0.0.1:{port}{open_path}"
        # Append the token so the opened tab authenticates (and the
        # server pins the urika_token cookie for follow-up XHRs).
        if auth_token:
            sep = "&" if "?" in open_path else "?"
            url = f"{url}{sep}token={auth_token}"
        webbrowser.open(url)

    return server, t, port
