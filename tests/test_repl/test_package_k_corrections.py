"""Tests for v0.4.2 Package K — Package I+J corrections + minor fixes.

Each test EXECUTES the affected code (not just source-greps) so a
regression of the kind that shipped under Package I (the
``cmd_advisor`` str/dict bug) surfaces immediately.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch


from urika.repl.session import ReplSession


# ── NEW-BUG-1: cmd_advisor str return handling ────────────────────


class TestCmdAdvisorHandlesStringReturn:
    """``_run_single_agent`` returns a ``str`` (declared on
    ``helpers.py:65``), not a dict. Pre-K ``cmd_advisor`` did
    ``result.get("response", "")`` which raised AttributeError on
    every successful call. The error was swallowed by the wrapping
    ``except Exception: pass``, silently skipping advisor_memory
    persistence and suggestion parsing.
    """

    def test_str_response_is_persisted_and_parsed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Drive ``cmd_advisor`` with a stub agent that returns a
        string containing a suggestions JSON block. After the call,
        ``advisor-history.json`` must contain both the user message
        and the advisor reply, and ``session.pending_suggestions``
        must be populated.
        """
        # Build a project dir with the minimum structure cmd_advisor needs.
        project_dir = tmp_path / "proj"
        (project_dir / "projectbook").mkdir(parents=True)
        (project_dir / "experiments").mkdir()

        # Stub the actual agent runner to skip the real Anthropic call.
        # _run_single_agent returns a str; we return a string with a
        # suggestions JSON block embedded so parse_suggestions populates
        # pending_suggestions.
        fake_response = """Here are two ideas:

```json
{"suggestions": [
  {"name": "ols-baseline", "method": "linear regression"},
  {"name": "ridge", "method": "ridge regression with CV"}
]}
```
"""

        with patch(
            "urika.repl.cmd_agents._run_single_agent",
            return_value=fake_response,
        ):
            session = ReplSession()
            session.project_path = project_dir
            session.project_name = "proj"

            from urika.repl.cmd_agents import cmd_advisor

            cmd_advisor(session, "what should I try first?")

        # Suggestion parsing must have populated pending_suggestions.
        assert len(session.pending_suggestions) == 2
        assert session.pending_suggestions[0]["name"] == "ols-baseline"
        assert session.pending_suggestions[1]["name"] == "ridge"

        # advisor-history.json must contain both user and advisor turns.
        import json

        history_path = project_dir / "projectbook" / "advisor-history.json"
        assert history_path.exists(), (
            "Pre-K bug: append_exchange was never called because "
            "result.get() raised AttributeError on the str return."
        )
        history = json.loads(history_path.read_text())
        assert len(history) == 2
        roles = {entry["role"] for entry in history}
        assert roles == {"user", "advisor"}

    def test_empty_response_no_persistence(self, tmp_path: Path) -> None:
        """If the agent returned ``""`` (failure path), nothing
        should be persisted — that's correct restraint, not the
        AttributeError-swallowing pre-fix behaviour."""
        project_dir = tmp_path / "proj"
        (project_dir / "projectbook").mkdir(parents=True)
        (project_dir / "experiments").mkdir()

        with patch(
            "urika.repl.cmd_agents._run_single_agent", return_value=""
        ):
            session = ReplSession()
            session.project_path = project_dir
            session.project_name = "proj"

            from urika.repl.cmd_agents import cmd_advisor

            cmd_advisor(session, "anything")

        history_path = project_dir / "projectbook" / "advisor-history.json"
        assert not history_path.exists()
        assert session.pending_suggestions == []


# ── /pause stale flag ─────────────────────────────────────────────


class TestPauseFlagOnlyForRun:
    """``/pause`` writes ``pause_requested`` to disk; the orchestrator's
    ``run_experiment`` polls it per-turn and stops at the next safe
    point. Pre-K the flag was written regardless of what agent was
    active — typing /pause during /finalize meant the NEXT /run
    auto-paused on its first turn.
    """

    def test_pause_during_run_writes_flag(self, tmp_path: Path) -> None:
        from urika.repl.commands import cmd_pause

        project_dir = tmp_path / "proj"
        project_dir.mkdir()

        session = ReplSession()
        session.project_path = project_dir
        session.set_agent_active("run")

        cmd_pause(session, "")

        flag = project_dir / ".urika" / "pause_requested"
        assert flag.exists()
        assert flag.read_text() == "pause"

    def test_pause_during_finalize_does_not_write_flag(
        self, tmp_path: Path
    ) -> None:
        from urika.repl.commands import cmd_pause

        project_dir = tmp_path / "proj"
        project_dir.mkdir()

        session = ReplSession()
        session.project_path = project_dir
        session.set_agent_active("finalize")

        cmd_pause(session, "")

        flag = project_dir / ".urika" / "pause_requested"
        assert not flag.exists(), (
            "Pre-K bug: cmd_pause wrote the flag for any active "
            "agent, leaving stale flags that the next /run picked "
            "up and immediately paused on."
        )

    def test_pause_during_resume_writes_flag(self, tmp_path: Path) -> None:
        """``/resume`` continues a paused /run, so /pause during
        /resume should also work — both share the same orchestrator
        loop that polls the flag."""
        from urika.repl.commands import cmd_pause

        project_dir = tmp_path / "proj"
        project_dir.mkdir()

        session = ReplSession()
        session.project_path = project_dir
        session.set_agent_active("resume")

        cmd_pause(session, "")

        flag = project_dir / ".urika" / "pause_requested"
        assert flag.exists()


# ── B2: REPL processing_ms tracking ──────────────────────────────


class TestSetAgentActiveStartsProcessingClock:
    """REPL paths only call ``set_agent_active``, never
    ``set_agent_running``. Pre-K only the latter started the
    processing clock, so REPL sessions logged ``processing_ms=0``
    forever."""

    def test_set_agent_active_starts_clock(self) -> None:
        session = ReplSession()
        assert session._processing_start == 0.0

        session.set_agent_active("run")
        assert session._processing_start > 0.0

    def test_set_agent_active_does_not_overwrite_running_clock(self) -> None:
        """If ``set_agent_running`` already started the clock (TUI's
        agent worker bookkeeping), ``set_agent_active`` from inside
        the slash handler must NOT reset it. Otherwise every
        TUI-launched run double-starts and loses the head."""
        session = ReplSession()
        session.set_agent_running(agent_name="run")
        first_start = session._processing_start
        assert first_start > 0.0

        time.sleep(0.01)
        session.set_agent_active("run")
        assert session._processing_start == first_start

    def test_processing_ms_accumulates_across_idle(self) -> None:
        """End-to-end: set_agent_active → sleep → set_agent_idle →
        ``total_processing_ms`` should be > 0."""
        session = ReplSession()
        session.set_agent_active("advisor")
        time.sleep(0.05)
        session.set_agent_idle()
        assert session.total_processing_ms >= 50


# ── B3: clear_project mirrors load_project ────────────────────────


class TestClearProjectResetsAllState:
    """Pre-K ``clear_project`` only nulled three fields, leaking
    pending_suggestions, notification_bus thread, usage counters,
    etc. The bus thread in particular kept running and pointing at
    a deleted project's path."""

    def test_pending_suggestions_cleared(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path / "proj", "proj")
        session.pending_suggestions = [{"name": "x"}]

        session.clear_project()

        assert session.pending_suggestions == []

    def test_usage_counters_zeroed(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path / "proj", "proj")
        session.total_tokens_in = 1234
        session.total_tokens_out = 5678
        session.total_cost_usd = 0.99
        session.agent_calls = 7
        session.experiments_run = 3

        session.clear_project()

        assert session.total_tokens_in == 0
        assert session.total_tokens_out == 0
        assert session.total_cost_usd == 0.0
        assert session.agent_calls == 0
        assert session.experiments_run == 0

    def test_notification_bus_stopped(self, tmp_path: Path) -> None:
        """The bus's stop() must be called, and the field nulled."""

        class FakeBus:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

        session = ReplSession()
        session.load_project(tmp_path / "proj", "proj")
        bus = FakeBus()
        session.notification_bus = bus

        session.clear_project()

        assert bus.stopped is True
        assert session.notification_bus is None

    def test_remote_queue_drained(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path / "proj", "proj")
        with session._remote_lock:
            session._remote_queue.append(("run", "", None))
            session._remote_queue.append(("advisor", "test", None))

        session.clear_project()

        assert session._remote_queue == []
