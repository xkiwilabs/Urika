"""Input bar with contextual command/argument completion."""

from __future__ import annotations

from textual import on
from textual.binding import Binding
from textual.message import Message
from textual.suggester import Suggester
from textual.widgets import Input

from urika.repl.session import ReplSession


class _UrikaSuggester(Suggester):
    """Context-aware completion for the Urika TUI input bar.

    Three completion modes based on the current input value:

    * No leading ``/`` — no suggestion (free text).
    * ``/<partial>`` (no space) — suggest available slash commands.
    * ``/cmd <partial>`` (space after the command) — suggest
      command arguments. For commands that take a project
      (``/project``, ``/resume``) the argument list is project
      names; for commands that take an experiment the argument
      list is experiment IDs; other commands get no suggestions.

    The session is carried by reference so refreshed state (project
    loaded, new experiments) is picked up without rebuilding the
    suggester. The built-in Suggester cache is disabled because the
    suggestion pool is dynamic (project/experiment lists change).
    """

    _PROJECT_ARG_COMMANDS = frozenset({"project", "resume", "resume-session"})
    _EXPERIMENT_ARG_COMMANDS = frozenset(
        {"present", "logs", "evaluate", "report", "plan", "results"}
    )

    def __init__(self, session: ReplSession) -> None:
        # case_sensitive=True because slash commands and project
        # names are case-sensitive in the rest of the CLI.
        # use_cache=False because the suggestion pool depends on
        # live session state (projects added, experiments created).
        super().__init__(use_cache=False, case_sensitive=True)
        self.session = session

    async def get_suggestion(self, value: str) -> str | None:
        if not value.startswith("/"):
            return None

        # Split command and argument — command is the first word.
        rest = value[1:]
        if " " not in rest:
            # Still typing the command name itself.
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
    """Always-on input bar for commands and free text.

    Emits CommandSubmitted when the user presses Enter.
    All visual styling (dock, margin, border) lives in
    ``src/urika/tui/urika.tcss`` — do NOT add a DEFAULT_CSS block
    here. Layering our own border-top on top of Textual's default
    Input border collapsed the widget's content area and caused
    the caret to disappear on the first user test.

    Tab binding is declared via BINDINGS with ``priority=True`` so
    it intercepts the App-level Tab (focus-change) when this widget
    has focus. A previous version overrode ``_on_key`` directly and
    broke space-key handling in real terminals (the pilot test
    passed but the real-terminal dispatch went through a different
    path that swallowed non-Tab keys). The BINDINGS path is the
    supported way to add key handling to an Input subclass.
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

    def _build_suggester(self) -> _UrikaSuggester:
        """Build the contextual suggester for this session."""
        return _UrikaSuggester(self.session)

    def on_mount(self) -> None:
        """Focus input and set up suggester."""
        self.focus()
        self.suggester = self._build_suggester()

    def action_accept_suggestion(self) -> None:
        """Accept the current Input suggestion on Tab.

        Mirrors Textual's native Right-arrow accept-suggestion
        behavior but bound to Tab for bash/zsh muscle memory. If
        we just completed a bare command (no argument separator
        yet), append a trailing space so the next character fires
        argument-level completion from _UrikaSuggester.
        """
        suggestion = getattr(self, "_suggestion", "") or ""
        if not suggestion or suggestion == self.value:
            return
        # Bare command completion → append space so argument-mode
        # suggester can fire immediately. Otherwise keep the exact
        # completion the suggester produced.
        if " " not in suggestion[1:]:
            self.value = suggestion + " "
        else:
            self.value = suggestion
        self.cursor_position = len(self.value)

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
