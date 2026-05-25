"""Tests for ``urika.tui.dashboard_launcher``.

These tests stub out ``uvicorn.Server`` so no real socket is bound,
and replace ``webbrowser.open`` with a recorder. That keeps the
unit test fast and side-effect-free.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

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
    # Default-secure launch: path is preserved, and the opened tab carries
    # the auto-generated auth token as a ?token= query param so it
    # authenticates against the now-default-secure dashboard.
    parsed = urlparse(opened[0])
    assert parsed.scheme == "http"
    assert parsed.netloc == f"127.0.0.1:{port}"
    assert parsed.path == "/projects/foo"
    query = parse_qs(parsed.query)
    assert "token" in query, "opened URL must carry the default auth token"
    assert query["token"][0] == server.urika_auth_token
    assert isinstance(server, _StubServer)


def test_start_dashboard_server_no_auth_opens_plain_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``no_auth=True`` the launch is fully open (loopback only), so
    the opened URL carries no ``token`` query param."""
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

    server, _thread, port = start_dashboard_server(
        open_path="/projects/foo", no_auth=True
    )

    assert opened, "webbrowser.open should have been called"
    parsed = urlparse(opened[0])
    assert parsed.netloc == f"127.0.0.1:{port}"
    assert parsed.path == "/projects/foo"
    assert parse_qs(parsed.query) == {}, "no_auth launch must not carry a token"
    assert server.urika_auth_token is None


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
