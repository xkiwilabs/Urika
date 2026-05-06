"""Tests for v0.4.2 Package I + J — REPL/TUI parity fixes.

Each test pins one item from the consolidated audit so a future
regression that drops the fix surfaces as a test failure rather than
silently re-breaking the user-facing flow.
"""

from __future__ import annotations

import inspect


class TestItem1ReplParseSuggestions:
    """REPL ``_handle_free_text`` must call ``parse_suggestions`` and
    populate ``session.pending_suggestions`` so /run picks them up.
    Pre-Package-I the function was DEFINED a few lines below but
    never called from this path — so the REPL had the same advisor
    -> /run silent-fail-to-pending bug the TUI was found to have."""

    def test_handle_free_text_calls_parse_suggestions(self) -> None:
        from urika.repl import main as repl_main

        src = inspect.getsource(repl_main._handle_free_text)
        assert "parse_suggestions" in src, (
            "REPL _handle_free_text must populate session.pending_suggestions "
            "via parse_suggestions(response). Pre-Package-I it didn't."
        )
        assert "pending_suggestions" in src


class TestItem2TuiPauseReachable:
    """TUI ``_ALWAYS_ALLOWED_COMMANDS`` must include "pause" so
    /pause is dispatchable while an agent is running. Pre-Package-I
    the busy-guard rejected /pause (only quit + stop were allowed)
    — making the documented "pause mid-experiment" feature
    structurally unreachable from the TUI."""

    def test_pause_in_always_allowed(self) -> None:
        from urika.tui.app import _ALWAYS_ALLOWED_COMMANDS

        assert "pause" in _ALWAYS_ALLOWED_COMMANDS
        assert "stop" in _ALWAYS_ALLOWED_COMMANDS
        assert "quit" in _ALWAYS_ALLOWED_COMMANDS


class TestItem3TuiPauseFlagDeliverable:
    """Once /pause is reachable (Item 2) the existing ``cmd_pause``
    handler writes the cooperative ``pause_requested`` flag to disk,
    which the orchestrator's PauseController polls between turns.
    Confirms the flag-writing logic is unchanged (a regression that
    silenced the write would re-break the feature)."""

    def test_cmd_pause_writes_pause_flag(self) -> None:
        from urika.repl.commands import cmd_pause

        src = inspect.getsource(cmd_pause)
        assert "pause_requested" in src
        assert 'flag.write_text("pause"' in src or "'pause'" in src


class TestItem4TuiRemoteChatParseSuggestions:
    """``_run_remote_chat`` (Slack/Telegram inbound chat) must also
    parse suggestions — Package H wired this in for the LOCAL
    InputBar free-text path but missed the parallel remote-chat
    path, leaving Slack users with the same advisor -> /run silent
    fail bug."""

    def test_remote_chat_calls_parse_suggestions(self) -> None:
        from urika.tui import app as tui_app

        # _run_remote_chat is defined inline inside
        # _dispatch_remote_free_text; source-level grep is the
        # simplest contract test.
        src = inspect.getsource(tui_app.UrikaApp._dispatch_remote_free_text)
        assert "parse_suggestions" in src
        assert "pending_suggestions" in src


class TestItem5RemoteRunAdvisorFirstOverride:
    """Remote ``/run --no-advisor-first`` must disable advisor-first
    even though the default is True. Pre-Package-I the worker
    hardcoded ``advisor_first=True`` — Slack/Telegram users could
    not opt out."""

    def test_parser_accepts_no_advisor_first_flag(self) -> None:
        from urika.repl.commands_run import _parse_remote_run_args

        result = _parse_remote_run_args("--no-advisor-first")
        assert result["advisor_first"] is False

    def test_parser_accepts_advisor_first_flag(self) -> None:
        from urika.repl.commands_run import _parse_remote_run_args

        result = _parse_remote_run_args("--advisor-first")
        assert result["advisor_first"] is True

    def test_parser_default_is_none(self) -> None:
        """None signals 'use default'; the caller resolves it to True."""
        from urika.repl.commands_run import _parse_remote_run_args

        result = _parse_remote_run_args("3")
        assert result["advisor_first"] is None
        assert result["max_turns"] == 3

    def test_parser_combines_with_other_flags(self) -> None:
        from urika.repl.commands_run import _parse_remote_run_args

        result = _parse_remote_run_args("--multi 5 --no-advisor-first")
        assert result["advisor_first"] is False
        assert result["max_experiments"] == 5

    def test_parser_strips_advisor_flag_from_instructions(self) -> None:
        """The flag must be consumed even when it appears mid-args, so
        it doesn't leak into the instructions string."""
        from urika.repl.commands_run import _parse_remote_run_args

        result = _parse_remote_run_args("try ridge --no-advisor-first")
        assert result["advisor_first"] is False
        # "try ridge" should still survive as instructions OR as a
        # parse failure that yields the literal string. Either way
        # the advisor flag must not appear in the result text.
        instr = result.get("instructions", "")
        assert "--no-advisor-first" not in instr


class TestItem6ResumePreservesFlags:
    """``/resume`` must preserve ``advisor_first`` and
    ``review_criteria`` from the project's preferences instead of
    silently dropping both to False."""

    def test_load_run_defaults_includes_advisor_first(self, tmp_path) -> None:
        from urika.repl.helpers import _load_run_defaults

        # Stub session with a project_path pointing at a TOML with
        # advisor_first toggled off.
        toml = tmp_path / "urika.toml"
        toml.write_text(
            '[preferences]\n'
            'max_turns_per_experiment = 7\n'
            'auto_mode = "capped"\n'
            'advisor_first = false\n'
            'review_criteria = true\n'
        )

        class _StubSession:
            project_path = tmp_path

        defaults = _load_run_defaults(_StubSession())
        assert defaults["advisor_first"] is False
        assert defaults["review_criteria"] is True

    def test_resume_passes_flags_to_cli_run(self) -> None:
        """``cmd_resume`` must forward ``advisor_first`` and
        ``review_criteria`` to ``ctx.invoke(cli_run, ...)``."""
        from urika.repl.commands_session import cmd_resume

        src = inspect.getsource(cmd_resume)
        assert "advisor_first=" in src
        assert "review_criteria=" in src


class TestItem7AdvisorSlashUsesAdvisorAgent:
    """``/advisor`` must invoke the actual ``advisor_agent`` role —
    not OrchestratorChat. Pre-Package-I it routed to
    ``_handle_free_text`` (orchestrator), bypassing advisor_memory
    and using a different system prompt than the user expected."""

    def test_cmd_advisor_runs_advisor_agent(self) -> None:
        from urika.repl.cmd_agents import cmd_advisor

        src = inspect.getsource(cmd_advisor)
        assert "_run_single_agent" in src
        assert "advisor_agent" in src
        # And it must NOT delegate to free-text anymore.  The
        # docstring mentions the prior behaviour ("pre-fix this
        # delegated to ``_handle_free_text``") so we strip the
        # docstring before asserting on the body.
        body = inspect.getsource(cmd_advisor)
        if cmd_advisor.__doc__:
            body = body.replace(cmd_advisor.__doc__, "")
        assert "_handle_free_text(" not in body, (
            "cmd_advisor must not call _handle_free_text — that "
            "would route to OrchestratorChat instead of the "
            "advisor_agent role."
        )

    def test_cmd_advisor_persists_to_advisor_memory(self) -> None:
        """The advisor exchange must round-trip through
        advisor_memory.append_exchange so subsequent /advisor calls
        and shell ``urika advisor`` runs share continuity."""
        from urika.repl.cmd_agents import cmd_advisor

        src = inspect.getsource(cmd_advisor)
        assert "append_exchange" in src

    def test_cmd_advisor_parses_suggestions(self) -> None:
        from urika.repl.cmd_agents import cmd_advisor

        src = inspect.getsource(cmd_advisor)
        assert "parse_suggestions" in src
        assert "pending_suggestions" in src


class TestItem8TuiBlocksFreeTextWhileBusy:
    """TUI ``_dispatch_free_text`` must reject (not queue) text typed
    while an agent is running. Pre-Package-I the queue-and-replay
    model had subtle stale-context, drain-race, and silent-bury
    issues — and broke parity with the REPL's blocking-prompt
    model."""

    def test_dispatch_free_text_no_longer_queues(self) -> None:
        from urika.tui import app as tui_app

        src = inspect.getsource(tui_app.UrikaApp._dispatch_free_text)
        assert "queue_input" not in src, (
            "Package I deletes the queue path; if a future edit puts "
            "it back, this test surfaces it."
        )

    def test_run_free_text_no_longer_drains(self) -> None:
        from urika.tui import app as tui_app

        src = inspect.getsource(tui_app.UrikaApp._run_free_text)
        # The drain block uses these two attributes; if either is
        # back, queue-and-drain has been re-introduced.
        assert "has_queued_input" not in src
        assert "pop_queued_input" not in src


class TestPackageJ_RemoteRegistry:
    """``_REMOTE_COMMAND_MAP`` was hardcoded; v0.4.2 new slashes
    weren't reachable. Now built from the live registry."""

    def test_summarize_callable_remotely(self) -> None:
        from urika.repl.main import _build_remote_command_map

        cmap = _build_remote_command_map()
        assert "summarize" in cmap

    def test_sessions_callable_remotely(self) -> None:
        from urika.repl.main import _build_remote_command_map

        cmap = _build_remote_command_map()
        assert "sessions" in cmap

    def test_destructive_commands_blocked(self) -> None:
        """Destructive or interactive-editor commands must NOT be
        remote-callable even though they're in the registry."""
        from urika.repl.main import (
            _REMOTE_BLOCKED_COMMANDS,
            _build_remote_command_map,
        )

        cmap = _build_remote_command_map()
        for blocked in ("delete", "memory", "config", "setup", "new"):
            assert blocked not in cmap, (
                f"/{blocked} is in the blocked list but leaked into "
                f"the remote map."
            )
        assert "delete" in _REMOTE_BLOCKED_COMMANDS


class TestPackageJ_ReplSummarizeIsAgentCommand:
    """REPL ``AGENT_COMMANDS`` must include ``summarize`` so the
    REPL doesn't block its main thread for the duration of a
    multi-minute summarize agent call."""

    def test_summarize_in_agent_commands(self) -> None:
        from urika.repl.main import AGENT_COMMANDS

        assert "summarize" in AGENT_COMMANDS
