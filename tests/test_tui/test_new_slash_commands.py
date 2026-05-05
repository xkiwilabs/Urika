"""Tests for v0.4.2 C7 + H8 slash command registrations.

C7 — pre-v0.4.2 ``"setup"`` was listed in the TUI's
``_WORKER_COMMANDS`` set but had no registered slash handler;
``/setup`` printed "Unknown command" and a new TUI user could not
run setup without dropping to a shell.

H8 — five CLI features had no TUI parity:
``/summarize``, ``/sessions``, ``/memory``, ``/venv``,
``/experiment-create``. Each is now a thin slash that forwards
to the corresponding Click command via ``ctx.invoke``.
"""

from __future__ import annotations

import urika.repl.commands  # noqa: F401 — triggers registration
from urika.repl.commands_registry import GLOBAL_COMMANDS, PROJECT_COMMANDS


class TestC7SetupSlashRegistered:
    def test_setup_is_a_global_command(self) -> None:
        assert "setup" in GLOBAL_COMMANDS, (
            "Pre-v0.4.2 ``/setup`` was in the worker set but had no "
            "handler — typing it printed 'Unknown command'. C7 fix "
            "registers a handler in commands.py."
        )

    def test_setup_handler_is_callable(self) -> None:
        entry = GLOBAL_COMMANDS["setup"]
        assert callable(entry["func"])
        assert entry["description"]


class TestH8MissingSlashesRegistered:
    def test_summarize_registered(self) -> None:
        assert "summarize" in GLOBAL_COMMANDS

    def test_sessions_registered(self) -> None:
        assert "sessions" in GLOBAL_COMMANDS

    def test_memory_registered(self) -> None:
        assert "memory" in GLOBAL_COMMANDS

    def test_venv_registered(self) -> None:
        assert "venv" in GLOBAL_COMMANDS

    def test_experiment_create_is_project_scoped(self) -> None:
        # Creating an experiment requires a loaded project, so this
        # one is registered in PROJECT_COMMANDS not GLOBAL_COMMANDS.
        assert "experiment-create" in PROJECT_COMMANDS


class TestSummarizeIsAWorkerCommand:
    def test_summarize_in_worker_set(self) -> None:
        """``/summarize`` is an agent call (long-running) so it must
        run in a Textual Worker, not inline."""
        from urika.tui.app import _WORKER_COMMANDS

        assert "summarize" in _WORKER_COMMANDS


class TestPriorityListIncludesNewCommands:
    def test_new_commands_in_completion_priority(self) -> None:
        """Tab-completion priority list must mention each new command
        so they are suggested ahead of alphabetical fallback."""
        from urika.tui.widgets.input_bar import _UrikaSuggester

        priority = _UrikaSuggester._COMMAND_PRIORITY
        for name in (
            "setup",
            "summarize",
            "sessions",
            "memory",
            "venv",
            "experiment-create",
        ):
            assert name in priority, f"/{name} missing from completion priority"
