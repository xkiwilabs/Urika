"""Input bar with contextual command/argument completion."""

from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.binding import Binding
from textual.message import Message
from textual.suggester import Suggester
from textual.widgets import Input

from urika.repl.session import ReplSession


class _UrikaSuggester(Suggester):
    """Context-aware completion for the Urika TUI input bar.

    * No leading ``/`` — no suggestion (free text).
    * ``/<partial>`` (no space) — suggest available slash commands.
    * ``/cmd <partial>`` — suggest command arguments (project names,
      experiment IDs).
    """

    _PROJECT_ARG_COMMANDS = frozenset({"project", "resume", "resume-session"})
    _EXPERIMENT_ARG_COMMANDS = frozenset(
        {"present", "logs", "evaluate", "report", "plan", "results"}
    )

    def __init__(self, session: ReplSession) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self.session = session

    async def get_suggestion(self, value: str) -> str | None:
        if not value.startswith("/"):
            return None
        rest = value[1:]
        if " " not in rest:
            return self._suggest_command(rest)
        cmd, _, arg_prefix = rest.partition(" ")
        cmd_lc = cmd.lower()
        if cmd_lc in self._PROJECT_ARG_COMMANDS:
            return self._suggest_project(cmd, arg_prefix)
        if cmd_lc in self._EXPERIMENT_ARG_COMMANDS:
            return self._suggest_experiment(cmd, arg_prefix)
        return None

    def _suggest_command(self, prefix: str) -> str | None:
        from urika.repl.commands import get_command_names

        for name in get_command_names(self.session):
            if name.startswith(prefix):
                return "/" + name
        return None

    def _suggest_project(self, cmd: str, arg_prefix: str) -> str | None:
        from urika.repl.commands import get_project_names

        for name in get_project_names():
            if name.startswith(arg_prefix):
                return f"/{cmd} {name}"
        return None

    def _suggest_experiment(self, cmd: str, arg_prefix: str) -> str | None:
        from urika.repl.commands import get_experiment_ids

        for eid in get_experiment_ids(self.session):
            if eid.startswith(arg_prefix):
                return f"/{cmd} {eid}"
        return None


class InputBar(Input):
    """Command input bar with tab completion and the Textual 8.1.1
    space-key workaround.

    No placeholder text — the project/urika info is already visible
    in the StatusBar directly below.
    """

    BINDINGS = [
        Binding(
            "tab",
            "accept_suggestion",
            "Complete",
            show=False,
            priority=True,
        ),
    ]

    # Textual 8.1.1 extended-key parser bug workaround. See the
    # _on_key docstring for the full explanation.
    _MISSING_CHARACTER_BY_KEY: ClassVar[dict[str, str]] = {
        "space": " ",
    }

    class CommandSubmitted(Message):
        """Fired when the user submits input with Enter."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, session: ReplSession, **kwargs: object) -> None:
        self.session = session
        super().__init__(
            placeholder="",
            select_on_focus=False,
            **kwargs,
        )

    def _build_suggester(self) -> _UrikaSuggester:
        return _UrikaSuggester(self.session)

    def on_mount(self) -> None:
        """Focus input and set up suggester."""
        self.focus()
        self.suggester = self._build_suggester()

    def action_accept_suggestion(self) -> None:
        """Accept the current suggestion on Tab."""
        suggestion = getattr(self, "_suggestion", "") or ""
        if not suggestion or suggestion == self.value:
            return
        if " " not in suggestion[1:]:
            self.value = suggestion + " "
        else:
            self.value = suggestion
        self.cursor_position = len(self.value)

    async def _on_key(self, event: object) -> None:
        """Textual 8.1.1 extended-key workaround.

        Modern terminals using modifyOtherKeys / CSI-u send space as
        a multi-char escape sequence (e.g. ``\\x1b[27;1;32~``). The
        xterm parser correctly derives ``key="space"`` but sets
        ``character=None`` because the raw sequence is >1 char.
        Input._on_key's ``if event.is_printable:`` then drops it.

        We intercept space-with-None-character and manually insert
        the space before Input sees it.
        """
        key = getattr(event, "key", None)
        character = getattr(event, "character", None)

        if character is None and key in self._MISSING_CHARACTER_BY_KEY:
            self.insert_text_at_cursor(self._MISSING_CHARACTER_BY_KEY[key])
            try:
                event.stop()  # type: ignore[attr-defined]
                event.prevent_default()  # type: ignore[attr-defined]
            except AttributeError:
                pass
            return

        await super()._on_key(event)  # type: ignore[misc]

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        """Handle Enter — emit CommandSubmitted, clear, stop the event.

        When a worker is waiting for interactive input (click.prompt
        asking for a default value), empty Enter must be submitted
        so the worker's stdin reader unblocks with "\\n" and
        click.prompt accepts the default. Without this, empty input
        is silently swallowed and the user can never accept defaults
        or leave fields empty.
        """
        from urika.tui.agent_worker import get_active_stdin_reader

        text = event.value.strip()
        reader = get_active_stdin_reader()
        if text:
            self.post_message(self.CommandSubmitted(text))
        elif reader is not None:
            # Empty submit while a worker waits for input — feed
            # empty line so click.prompt accepts the default.
            reader.feed("")
        self.value = ""
        event.stop()

    def refresh_prompt(self) -> None:
        """Rebuild the suggester after a project change."""
        self.suggester = self._build_suggester()
