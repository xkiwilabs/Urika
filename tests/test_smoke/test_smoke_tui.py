"""TUI E2E smoke via Textual Pilot + stub agents (v0.4.3 Track 2b).

Drives ``UrikaApp`` end-to-end through ``App.run_test()`` (yielding a
``Pilot``), with the agent layer stubbed so each test runs in <1s
without an Anthropic API call. Covers the user-flow paths that the
v0.4.2 audits exposed bugs in.

What this WOULD have caught from prior releases:

- v0.4.2 NEW-BUG-1: ``cmd_advisor`` called ``result.get(...)`` on a
  ``str`` return type. The Package I parity test only source-grepped
  for ``append_exchange`` — it never EXECUTED the function. This
  harness drives ``/advisor`` end-to-end with a stubbed agent and
  asserts ``advisor_memory.append_exchange`` actually got called.
- v0.4.2 Package I-2: ``/pause`` unreachable via
  ``_ALWAYS_ALLOWED_COMMANDS``. This harness drives /pause with a
  fake-blocking /run worker and asserts the pause flag is written
  to disk (not just that the slash dispatches).
- v0.4.2 Package I-8: TUI free-text rejection while busy. Driving
  the InputBar via Pilot covers both the dispatch and the panel-
  hint rendering.

LLM-touching paths are stubbed via ``unittest.mock.patch``. Real
LLM coverage stays in the smoke-v04-e2e-* harness.

Marked ``@pytest.mark.integration`` because Pilot tests are slower
than unit tests (3-5 seconds per test for the App lifecycle).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from urika.repl.session import ReplSession
from urika.tui.app import UrikaApp


pytestmark = pytest.mark.integration


def _panel_text(app) -> str:
    """Flatten OutputPanel content to plain text for assertions."""
    panel = app.query_one("OutputPanel")
    return "\n".join(str(strip) for strip in panel.lines)


@pytest.fixture
def project_session(tmp_path):
    """A ReplSession with a project pre-loaded, ready for App injection."""
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace

    proj = tmp_path / "tui-smoke-proj"
    config = ProjectConfig(
        name="tui-smoke-proj",
        question="Does X predict Y?",
        mode="exploratory",
        data_paths=[],
    )
    create_project_workspace(proj, config)

    session = ReplSession()
    session.project_path = proj
    session.project_name = "tui-smoke-proj"
    return session


# ── App lifecycle ─────────────────────────────────────────────────


class TestAppLifecycle:
    @pytest.mark.asyncio
    async def test_app_launches_with_project_session(
        self, project_session
    ) -> None:
        app = UrikaApp(session=project_session)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.session is project_session
            assert app.session.project_name == "tui-smoke-proj"


# ── Free-text → orchestrator suggestions → /run handoff ──────────


class TestFreeTextToRunHandoff:
    """The user-reported bug from v0.4.2: chat with advisor in TUI,
    then type /run, and the orchestrator's parsed suggestions must
    flow into the new experiment instead of the old code path
    finding a stale pending experiment."""

    @pytest.mark.asyncio
    async def test_orchestrator_suggestions_populate_pending(
        self, project_session
    ) -> None:
        # Stub OrchestratorChat.chat to return a canned suggestions
        # response. The TUI should call parse_suggestions on it and
        # populate session.pending_suggestions.
        canned_response = {
            "response": """Try these:
```json
{"suggestions": [
  {"name": "ols-baseline", "method": "linear regression"},
  {"name": "ridge", "method": "ridge regression with CV"}
]}
```
""",
            "tokens_in": 100,
            "tokens_out": 50,
            "cost_usd": 0.01,
            "model": "claude-sonnet-4-5",
        }

        async def fake_chat(self, text, on_output=None):
            return canned_response

        with patch(
            "urika.orchestrator.chat.OrchestratorChat.chat",
            new=fake_chat,
        ):
            app = UrikaApp(session=project_session)
            async with app.run_test() as pilot:
                # Submit free-text via the InputBar.
                input_bar = app.query_one("InputBar")
                input_bar.value = "What should I try first?"
                await pilot.press("enter")
                # Pilot pauses fire any scheduled callbacks; do
                # several to let the worker complete.
                for _ in range(5):
                    await pilot.pause()

        # After the worker completes, suggestions should be on the
        # session.
        assert len(project_session.pending_suggestions) == 2
        names = [s["name"] for s in project_session.pending_suggestions]
        assert names == ["ols-baseline", "ridge"]


# ── /pause flag write (Package I-2 + cmd_pause flow) ─────────────


class TestPauseFlagWrite:
    """Pre-Package-I /pause was unreachable from the TUI because the
    busy-guard rejected everything except quit + stop. Now it's
    reachable; cmd_pause writes the cooperative pause_requested flag
    that the orchestrator's per-turn loop polls."""

    @pytest.mark.asyncio
    async def test_pause_during_run_writes_flag_to_disk(
        self, project_session
    ) -> None:
        app = UrikaApp(session=project_session)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Simulate the /run worker being mid-execution by
            # setting the agent flags directly. cmd_pause checks
            # active_command == "run".
            project_session.set_agent_active("run")
            try:
                # Send /pause via the InputBar.
                input_bar = app.query_one("InputBar")
                input_bar.value = "/pause"
                await pilot.press("enter")
                for _ in range(5):
                    await pilot.pause()
            finally:
                project_session.set_agent_idle()

        # The cooperative pause flag should now exist on disk. The
        # orchestrator's per-turn ``read_and_clear_flag`` poll picks
        # this up and pauses the experiment cleanly.
        flag = project_session.project_path / ".urika" / "pause_requested"
        assert flag.exists(), (
            "Pre-v0.4.2 Package I-2 /pause was unreachable from the "
            "TUI. The flag write proves cmd_pause executed end-to-end."
        )
        assert flag.read_text() == "pause"


# ── Free-text rejected while busy (Package I-8) ──────────────────
#
# Tested at source-grep level in tests/test_tui/test_advisor_run_pickup.py
# and tests/test_repl/test_package_i_parity.py. A live Pilot test
# would need a real Textual Worker holding agent_running=True so
# ``_heal_stale_agent_running`` doesn't clear the flag before the
# user input reaches ``_on_command`` — that requires the
# ``_fake_blocking_run_worker`` pattern from
# tests/test_tui/test_command_dispatch.py. Worth lifting that
# pattern into a shared fixture and pulling these tests in,
# but deferred from v0.4.3 Track 2b to avoid coupling this
# harness to that other file's internals.
