"""Consistent ``experiment-<verb>`` command aliases across surfaces.

The CLI uses ``experiment create`` / ``experiment delete`` /
``experiment list``. The REPL/TUI historically used three different
conventions: ``/experiment-create`` (verb 2nd), ``/delete-experiment``
(verb 1st), and ``/experiments`` (plural noun).

We add consistent ``experiment-<verb>`` aliases WITHOUT removing the
old names (back-compat). The TUI inherits ``PROJECT_COMMANDS`` from the
REPL, so the aliases surface there automatically.
"""

from __future__ import annotations


def test_experiment_command_aliases_exist() -> None:
    # PROJECT_COMMANDS is the dict the TUI and get_all_commands read.
    from urika.repl.commands_registry import PROJECT_COMMANDS

    cmds = set(PROJECT_COMMANDS)

    # Consistent experiment-<verb> form:
    assert "experiment-create" in cmds
    assert "experiment-delete" in cmds
    assert "experiment-list" in cmds

    # Back-compat preserved:
    assert "delete-experiment" in cmds
    assert "experiments" in cmds


def test_aliases_dispatch_to_same_handler() -> None:
    """Each alias must resolve to the SAME handler function as its
    canonical name."""
    from urika.repl.commands_registry import PROJECT_COMMANDS

    assert (
        PROJECT_COMMANDS["experiment-delete"]["func"]
        is PROJECT_COMMANDS["delete-experiment"]["func"]
    )
    assert (
        PROJECT_COMMANDS["experiment-list"]["func"]
        is PROJECT_COMMANDS["experiments"]["func"]
    )


def test_aliases_visible_via_get_all_commands() -> None:
    """The aliases must surface through get_all_commands (what tab
    completion / the TUI command list read) when a project is loaded."""
    from urika.repl.commands import get_all_commands

    class _StubSession:
        has_project = True

    cmds = set(get_all_commands(_StubSession()))
    assert "experiment-delete" in cmds
    assert "experiment-list" in cmds
