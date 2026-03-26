"""Input bar with command completion."""

from __future__ import annotations

from textual import on
from textual.message import Message
from textual.suggester import SuggestFromList
from textual.widgets import Input

from urika.repl_session import ReplSession


class InputBar(Input):
    """Always-on input bar for commands and free text.

    Emits CommandSubmitted when the user presses Enter.
    """

    DEFAULT_CSS = ""

    class CommandSubmitted(Message):
        """Fired when user submits input."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, session: ReplSession, **kwargs: object) -> None:
        self.session = session
        prompt = self._build_prompt()
        super().__init__(placeholder=prompt, **kwargs)

    def _build_prompt(self) -> str:
        if self.session.has_project:
            return f"urika:{self.session.project_name}> "
        return "urika> "

    def _build_suggester(self) -> SuggestFromList:
        """Build command suggester from available commands."""
        from urika.repl_commands import get_command_names

        names = get_command_names(self.session)
        return SuggestFromList(["/" + n for n in names])

    def on_mount(self) -> None:
        """Focus input and set up suggester."""
        self.focus()
        self.suggester = self._build_suggester()

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        """Handle Enter key — emit command and clear input."""
        text = event.value.strip()
        if text:
            self.post_message(self.CommandSubmitted(text))
        self.value = ""
        event.stop()

    def refresh_prompt(self) -> None:
        """Update the prompt text after project change."""
        self.placeholder = self._build_prompt()
        self.suggester = self._build_suggester()
