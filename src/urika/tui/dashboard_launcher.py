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

    Returns
    -------
    tuple
        ``(server, thread, port)`` where ``server`` is the
        ``uvicorn.Server`` instance (caller can set
        ``server.should_exit = True`` to stop), ``thread`` is the
        daemon thread running the event loop, and ``port`` is the
        actual port chosen.
    """
    import uvicorn

    from urika.dashboard_v2.app import create_app

    if port is None:
        port = _find_free_port()

    # Registry is read from URIKA_HOME; project_root=None lets the
    # dashboard use the registered project directories.
    app = create_app(project_root=None)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

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
        webbrowser.open(url)

    return server, t, port
