"""Tests for ``urika.tui.dashboard_launcher``.

These tests stub out ``uvicorn.Server`` so no real socket is bound,
and replace ``webbrowser.open`` with a recorder. That keeps the
unit test fast and side-effect-free.
"""

from __future__ import annotations

import pytest

from urika.tui.dashboard_launcher import _find_free_port, start_dashboard_server


def test_find_free_port_returns_a_port() -> None:
    p = _find_free_port()
    assert isinstance(p, int)
    assert p > 1024


def test_start_dashboard_server_opens_browser_with_right_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uvicorn

    class _StubServer:
        def __init__(self, config: object) -> None:
            self.config = config
            self.started = True
            self.should_exit = False

        def run(self) -> None:
            return None

    monkeypatch.setattr(uvicorn, "Server", _StubServer)

    opened: list[str] = []
    monkeypatch.setattr(
        "urika.tui.dashboard_launcher.webbrowser.open",
        lambda u: opened.append(u),
    )

    server, thread, port = start_dashboard_server(open_path="/projects/foo")

    assert opened, "webbrowser.open should have been called"
    assert opened[0].endswith("/projects/foo")
    assert opened[0].startswith(f"http://127.0.0.1:{port}")
    assert isinstance(server, _StubServer)


def test_start_dashboard_server_no_browser_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uvicorn

    class _StubServer:
        def __init__(self, config: object) -> None:
            self.config = config
            self.started = True
            self.should_exit = False

        def run(self) -> None:
            return None

    monkeypatch.setattr(uvicorn, "Server", _StubServer)

    opened: list[str] = []
    monkeypatch.setattr(
        "urika.tui.dashboard_launcher.webbrowser.open",
        lambda u: opened.append(u),
    )

    server, _thread, _port = start_dashboard_server(
        open_path="/projects",
        open_browser=False,
    )
    assert opened == []
    assert isinstance(server, _StubServer)


def test_start_dashboard_server_uses_provided_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uvicorn

    captured_config: dict[str, object] = {}

    class _StubServer:
        def __init__(self, config: object) -> None:
            captured_config["config"] = config
            self.started = True
            self.should_exit = False

        def run(self) -> None:
            return None

    monkeypatch.setattr(uvicorn, "Server", _StubServer)
    monkeypatch.setattr(
        "urika.tui.dashboard_launcher.webbrowser.open",
        lambda u: None,
    )

    _server, _thread, port = start_dashboard_server(
        port=12345, open_path="/projects", open_browser=False
    )
    assert port == 12345
    cfg = captured_config["config"]
    assert getattr(cfg, "port", None) == 12345
