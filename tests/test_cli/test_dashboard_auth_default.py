"""``urika dashboard`` generates an auth token by default.

The FastAPI dashboard ships unauthenticated when ``create_app`` is
called with ``auth_token=None``. To avoid the default launch being a
fully-open mutating surface on 127.0.0.1, the CLI launch path must
generate a random token unless the user explicitly opts out with
``--no-auth``.

These tests monkeypatch the launcher's ``create_app`` (to capture the
token actually passed) and ``uvicorn`` (so nothing binds a port).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from urika.cli._base import cli


class _FakeServer:
    """Stand-in uvicorn.Server: reports started, exits immediately."""

    should_exit = True
    started = True

    def run(self) -> None:  # pragma: no cover - never spun in a thread here
        pass


@pytest.fixture
def captured(monkeypatch):
    """Patch create_app + uvicorn so the dashboard command runs without
    binding a port, and capture the auth_token passed to create_app."""
    box: dict = {}

    def fake_create_app(project_root=None, auth_token=None):
        box["auth_token"] = auth_token
        return object()  # opaque app; uvicorn is stubbed

    import urika.dashboard.app as app_module
    import urika.tui.dashboard_launcher as launcher

    # The launcher imports create_app lazily from urika.dashboard.app,
    # so patch it at the source module.
    monkeypatch.setattr(app_module, "create_app", fake_create_app)

    # Stub uvicorn.Config / uvicorn.Server so no event loop / socket runs.
    class _FakeConfig:
        def __init__(self, *a, **k):
            pass

    fake_server = _FakeServer()

    class _FakeUvicorn:
        Config = _FakeConfig

        @staticmethod
        def Server(config):  # noqa: N802 - mimic uvicorn API
            return fake_server

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", _FakeUvicorn())
    # Don't actually open a browser.
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *a, **k: None)
    return box


def test_dashboard_generates_token_by_default(captured) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["dashboard"])
    assert result.exit_code == 0, result.output
    token = captured.get("auth_token")
    assert token, f"expected a generated token, got {token!r}"
    assert isinstance(token, str) and len(token) >= 20
    # The tokenized URL is printed for the user to open.
    assert f"token={token}" in result.output


def test_dashboard_no_auth_flag_disables_token(captured) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["dashboard", "--no-auth"])
    assert result.exit_code == 0, result.output
    assert captured.get("auth_token") is None


def test_dashboard_explicit_token_is_used(captured) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["dashboard", "--auth-token", "my-explicit-token"])
    assert result.exit_code == 0, result.output
    assert captured.get("auth_token") == "my-explicit-token"


@pytest.fixture
def captured_launch(monkeypatch):
    """Patch ``start_dashboard_server`` to capture the kwargs the
    ``dashboard`` command passes (esp. ``open_browser``), without
    actually spinning a server thread or opening a browser."""
    box: dict = {}

    def fake_start(**kwargs):
        box.update(kwargs)
        return _FakeServer(), object(), kwargs.get("port") or 54321

    import urika.cli.config as config_module

    # The CLI imports start_dashboard_server lazily inside the command;
    # patch it at its source module so the lazy import resolves to ours.
    import urika.tui.dashboard_launcher as launcher

    monkeypatch.setattr(launcher, "start_dashboard_server", fake_start)
    monkeypatch.setattr(
        config_module,
        "_resolve_project",
        lambda name: (None, None),
        raising=False,
    )
    return box


def test_dashboard_default_launch_opens_browser(captured_launch) -> None:
    """Behaviour change (v0.7.x): the default generated-token launch now
    auto-opens the browser (``open_browser=True``). Previously it passed
    ``open_browser=not generated`` (i.e. False for the default case),
    which forced the user to copy-paste the tokenized URL. The launcher
    appends the ``?token=`` itself, so auto-open lands on an authed page.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["dashboard"])
    assert result.exit_code == 0, result.output
    assert captured_launch.get("open_browser") is True
    # The tokenized URL is still printed as a fallback.
    token = captured_launch.get("auth_token")
    assert token
    assert f"token={token}" in result.output


def test_dashboard_no_auth_launch_opens_browser(captured_launch) -> None:
    """The --no-auth path also opens the browser (it always did)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["dashboard", "--no-auth"])
    assert result.exit_code == 0, result.output
    assert captured_launch.get("open_browser") is True
