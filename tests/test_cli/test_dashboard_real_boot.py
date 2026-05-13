"""``urika dashboard`` — real boot, no uvicorn stub.

The existing ``test_cli_remaining.py`` dashboard tests stub
``uvicorn.Server`` to set ``should_exit = True`` immediately, which
means the FastAPI app is never mounted and no real route is hit. Plus
they're ``skipif win32`` so Windows ships untested.

This spawns ``urika dashboard --port <free>`` as a real subprocess,
waits for the port to bind, hits ``/healthz`` to prove the app
mounted, then terminates the server. Catches: app-import errors,
route-registration breakage, the launcher's port-binding code,
``--auth-token`` actually being required when set.

Marked ``integration`` because it spawns a subprocess and binds a TCP
port; ~3-5 seconds per case.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, *, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _spawn_dashboard(tmp_path: Path, port: int, *extra_args: str) -> subprocess.Popen:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    projects = tmp_path / "projects"
    projects.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "URIKA_HOME": str(home),
        "URIKA_PROJECTS_DIR": str(projects),
        # Suppress the welcome banner / colour codes in subprocess output.
        "URIKA_NO_BANNER": "1",
    }
    # Use ``python -m urika`` so we don't depend on a ``urika`` console
    # script being installed on PATH (CI may use editable installs).
    cmd = [sys.executable, "-m", "urika", "dashboard", "--port", str(port), *extra_args]
    return subprocess.Popen(
        cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX-only subprocess signaling — Windows uses a different model",
)
def test_dashboard_starts_and_serves_healthz(tmp_path: Path) -> None:
    port = _find_free_port()
    proc = _spawn_dashboard(tmp_path, port)
    try:
        assert _wait_for_port(port, timeout=10.0), (
            "dashboard didn't bind within 10s; "
            f"stdout/stderr=\n{(proc.stdout.read() if proc.stdout else b'').decode(errors='replace')[:500]!r}"
        )
        # Hit /healthz with a tiny urllib request — no extra test deps.
        import urllib.request

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz", timeout=5
        ) as resp:
            assert resp.status == 200
            body = resp.read().decode()
            assert "ok" in body.lower() or '"status"' in body
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only")
def test_dashboard_with_auth_token_requires_bearer(tmp_path: Path) -> None:
    """When --auth-token is set, /healthz remains accessible (it's exempt)
    but other endpoints require the bearer token."""
    port = _find_free_port()
    proc = _spawn_dashboard(tmp_path, port, "--auth-token", "secret-token")
    try:
        assert _wait_for_port(port, timeout=10.0)
        import urllib.error
        import urllib.request

        # /healthz is exempt — works without auth.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz", timeout=5
        ) as resp:
            assert resp.status == 200

        # /projects requires the bearer header.
        req = urllib.request.Request(f"http://127.0.0.1:{port}/projects")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code in (401, 403)

        # With the right token it works.
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/projects",
            headers={"Authorization": "Bearer secret-token"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
