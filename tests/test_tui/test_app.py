"""Integration tests for the Textual TUI app.

These tests pin the app-level contracts that don't belong to any
single widget: mount smoke-test, three-zone composition, session
injection, and usage-tracking lifecycle. Widget behavior lives in
the per-widget test files (test_output_panel.py, test_status_bar.py,
test_input_bar.py). Command dispatch behavior lives in
test_command_dispatch.py. Worker behavior lives in test_agent_worker.py.
"""

from __future__ import annotations

import pytest

from urika.repl.session import ReplSession
from urika.tui.app import UrikaApp


class TestUrikaAppMount:
    """The UrikaApp mounts cleanly and has the expected identity."""

    @pytest.mark.asyncio
    async def test_app_mounts(self) -> None:
        app = UrikaApp()
        async with app.run_test():
            assert app.title == "Urika"


class TestThreeZoneComposition:
    """All three zones — output panel, input bar, status bar — must
    be queryable after mount. This is the structural contract the
    whole TUI rests on, so pin it with a dedicated test rather than
    leaving it implicit in per-widget tests."""

    @pytest.mark.asyncio
    async def test_three_zones_present(self) -> None:
        app = UrikaApp()
        async with app.run_test():
            # query_one raises NoMatches if the widget isn't composed.
            assert app.query_one("OutputPanel") is not None
            assert app.query_one("InputBar") is not None
            assert app.query_one("StatusBar") is not None


class TestSessionIntegration:
    """Session state is injected via constructor and flows through
    the TUI's widgets and worker paths unchanged."""

    @pytest.mark.asyncio
    async def test_session_persists_when_injected(self) -> None:
        """An injected session is the one the app uses — not a
        fresh copy. Needed so test harnesses and cli callers can
        pass in pre-configured state."""
        session = ReplSession()
        app = UrikaApp(session=session)
        async with app.run_test():
            assert app.session is session

    @pytest.mark.asyncio
    async def test_usage_tracking_starts_on_mount(self) -> None:
        """The session starts timing from construction. elapsed_ms
        must be non-zero by the time the app has mounted — otherwise
        StatusBar would render '0ms' forever."""
        app = UrikaApp()
        async with app.run_test():
            assert app.session.elapsed_ms > 0
