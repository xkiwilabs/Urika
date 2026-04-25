"""Slash-command registry shared across all repl/commands_*.py modules.

The decorator and the two dicts live here so any module that defines a
slash command can import them without a circular dependency on
``repl/commands.py``. ``repl/commands.py`` itself imports the registry,
defines its own commands, and pulls in the sibling modules so their
@command decorators register too.
"""

from __future__ import annotations

from typing import Callable

# Two registries — a project must be loaded for PROJECT_COMMANDS handlers.
# Module-level dicts are populated as @command-decorated functions are
# defined across all repl.commands_* modules.
GLOBAL_COMMANDS: dict[str, dict] = {}
PROJECT_COMMANDS: dict[str, dict] = {}


def command(
    name: str,
    requires_project: bool = False,
    description: str = "",
) -> Callable:
    """Register a slash command in the appropriate registry."""

    def decorator(func: Callable) -> Callable:
        entry = {"func": func, "description": description}
        if requires_project:
            PROJECT_COMMANDS[name] = entry
        else:
            GLOBAL_COMMANDS[name] = entry
        return func

    return decorator
