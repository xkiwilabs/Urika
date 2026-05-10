"""Main Textual application for Urika."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Vertical

from urika.orchestrator.chat import OrchestratorChat
from urika.repl.session import ReplSession
from urika.tui.agent_worker import run_command_in_worker
from urika.tui.capture import OutputCapture
from urika.tui.widgets.activity_bar import ActivityBar
from urika.tui.widgets.input_bar import InputBar
from urika.tui.widgets.output_panel import OutputPanel
from urika.tui.widgets.status_bar import StatusBar

# Commands that invoke a Claude agent and can take minutes. These run
# on a background thread-worker so the TUI stays responsive. Kept as a
# module constant so tests and future dispatch code share one source of
# truth. Order doesn't matter — membership check only.
# Commands that run in a background worker thread. The worker
# installs OutputCapture (stdout → panel) and _TuiStdinReader
# (stdin ← InputBar) so click.prompt / input / asyncio.run all
# work unchanged. User types answers in the InputBar — text feeds
# the worker's stdin queue automatically.
_WORKER_COMMANDS = frozenset(
    {
        "run", "finalize", "evaluate", "plan", "advisor",
        "present", "report", "build-tool", "resume",
        "new", "config", "notifications", "setup",
        # v0.4.2 H8: ``/summarize`` is an agent call (long-running);
        # the rest of the new H8 slashes (/sessions, /memory, /venv,
        # /experiment-create) are fast read/write operations and
        # run inline.
        "summarize",
    }
)

# Escape hatches that remain usable even while an agent is running.
# /quit must always work so the user can get out; /stop is the hard
# cancellation path; /pause writes the cooperative pause flag that
# the orchestrator's PauseController polls between turns. Pre-v0.4.2
# Package I, /pause was missing from this set — so the busy-guard
# rejected it and the documented "pause mid-experiment" feature was
# unreachable from the TUI.
_ALWAYS_ALLOWED_COMMANDS = frozenset({"quit", "stop", "pause"})



class UrikaApp(App):
    """Urika TUI — three-zone interactive interface."""

    # Absolute path so subclasses in tests (e.g. CapturingApp in
    # test_input_bar.py) don't resolve CSS relative to their own
    # __module__ directory and fail. Textual's default behavior is to
    # resolve a string CSS_PATH relative to the subclass's module,
    # which would break the moment anything subclasses UrikaApp.
    CSS_PATH = Path(__file__).parent / "urika.tcss"
    TITLE = "Urika"
    SUB_TITLE = "Multi-agent scientific analysis"

    BINDINGS = [
        # Ctrl+Q is the unambiguous quit binding — surfaced in the
        # Footer so users can see it at a glance. Ctrl+C still works
        # (cancels a running agent, or quits when idle — see
        # action_cancel_agent). Ctrl+D is an extra escape hatch but
        # Textual's terminal driver sometimes swallows it as EOF, so
        # we don't rely on it as the primary quit key.
        ("ctrl+q", "quit_app", "Quit"),
        ("ctrl+c", "cancel_agent", "Cancel / Quit"),
        ("ctrl+d", "quit_app", "Quit"),
        ("ctrl+y", "copy_last_response", "Copy last response"),
    ]

    def __init__(self, session: ReplSession | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.session = session or ReplSession()
        # One capture factory per app; entering `with self._capture:`
        # activates it for a single handler invocation. NOT reentrant —
        # never nest `with self._capture:` blocks.
        self._capture = OutputCapture(self)
        # Lazy orchestrator — created when first free-text lands, reused
        # across turns so conversation history is preserved. Reset if
        # the project changes.
        self._orchestrator: OrchestratorChat | None = None

    def compose(self) -> ComposeResult:
        # Textual's ``dock: bottom`` does NOT stack multiple widgets
        # to the same edge — each claims the absolute bottom region
        # independently and they overlap. Instead, group the bottom
        # strip (InputBar + StatusBar) inside a Vertical container
        # that itself docks to bottom. Children stack naturally
        # inside the container.
        #
        # The built-in Textual Footer (which renders BINDINGS hints)
        # is deliberately omitted — it refused to play nicely with
        # the Vertical/dock combo and kept overlapping StatusBar.
        # The welcome message prints "Press Ctrl+Q to quit." as the
        # visible backstop, and Ctrl+C falls through to quit when
        # no agent is running, so users always have an escape hatch.
        yield OutputPanel()
        with Vertical(id="bottom-stack"):
            yield InputBar(self.session)
            yield ActivityBar(self.session)
            yield StatusBar(self.session)

    def on_mount(self) -> None:
        """Show the welcome header + global stats on startup.

        Renders the same ASCII banner as the REPL/CLI but through the
        OutputPanel. Two subtleties worth commenting on:

        1. ``cli_display._C`` disables all color codes when
           ``sys.stdout.isatty()`` is False — which it always is
           inside Textual. We force-set the codes to truecolor
           escapes (``\\x1b[38;2;r;g;bm``) so Rich's ``Text.from_ansi``
           parses them as exact hex values rather than standard ANSI
           color(4), which Rich renders as a dark navy that looks
           purple on modern palettes.

        2. We route the banner through a local ``StringIO`` via
           ``contextlib.redirect_stdout``, NOT through
           ``OutputCapture``. ``OutputCapture._strip_ansi`` deliberately
           removes VT100 escape codes before writing to the panel
           (so worker output doesn't pollute RichLog with raw
           escapes), which would undo the color fix.
        """
        import contextlib
        import io

        from rich.text import Text

        from urika.cli_display import _C, print_header

        panel = self.query_one(OutputPanel)

        # Force-set the color codes. Use truecolor hex escapes so the
        # rendering matches the REPL visually regardless of terminal
        # palette. The hex values were picked to match the existing
        # "Urika blue" the CLI produces in most modern terminals.
        _URIKA_BLUE = "\x1b[38;2;74;158;255m"  # #4a9eff — bright cyan-blue
        _C.BLUE = _URIKA_BLUE
        _C.DIM = "\x1b[2m"
        _C.BOLD = "\x1b[1m"
        _C.RESET = "\x1b[0m"
        _C.WHITE = "\x1b[97m"

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_header()
        for line in buf.getvalue().splitlines():
            panel.write_line(Text.from_ansi(line))

        panel.write_line("")
        panel.write_line("  Urika — Multi-agent scientific analysis platform")
        panel.write_line("")

        try:
            from urika.repl.commands import get_global_stats

            stats = get_global_stats()
            panel.write_line(
                f"  {stats['projects']} projects · "
                f"{stats['experiments']} experiments · "
                f"{stats['methods']} methods · "
                f"{stats['sdk']}"
            )
        except (OSError, KeyError, ImportError) as exc:
            self.log.warning(f"welcome stats lookup failed: {exc}")

        # ── Recent projects ──────────────────────────────────────
        try:
            from datetime import datetime

            from urika.core.experiment import list_experiments
            from urika.core.registry import ProjectRegistry

            reg = ProjectRegistry()
            projects = reg.list_all()
            if projects:
                recent: list[tuple[str, int, str]] = []
                for name, path in projects.items():
                    try:
                        mtime = path.stat().st_mtime if path.exists() else 0
                        n_exps = len(list_experiments(path))
                        dt = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                        recent.append((name, n_exps, dt))
                    except (OSError, ValueError):
                        recent.append((name, 0, ""))
                recent.sort(key=lambda x: x[2], reverse=True)

                panel.write_line("")
                panel.write_line(
                    Text("  Recent projects:", style="bold")
                )
                for name, n_exps, dt in recent[:5]:
                    line = Text()
                    line.append("    /project ", style="dim")
                    line.append(name, style="#00d7ff")
                    if n_exps:
                        line.append(f"  {n_exps} experiments", style="dim")
                    if dt:
                        line.append(f"  ({dt})", style="dim")
                    panel.write_line(line)
        except (OSError, ImportError) as exc:
            self.log.warning(f"recent projects lookup failed: {exc}")

        # ── Getting started ──────────────────────────────────────
        panel.write_line("")
        panel.write_line(Text("  Getting started:", style="bold"))
        panel.write_line(
            Text.assemble(
                ("    /project ", "dim"),
                ("<name>", "#00d7ff"),
                ("  — load a project", "dim"),
            )
        )
        panel.write_line(
            Text.assemble(
                ("    /new ", "dim"),
                ("<name>", "#00d7ff"),
                ("  — create a new project", "dim"),
            )
        )
        panel.write_line(
            Text.assemble(
                ("    /config", "dim"),
                ("  — view or change settings", "dim"),
            )
        )
        panel.write_line(
            Text.assemble(
                ("    /help", "dim"),
                ("  — all available commands", "dim"),
            )
        )
        panel.write_line("")
        panel.write_line(
            Text(
                "  Or just type your question — the orchestrator will help.",
                style="dim",
            )
        )
        panel.write_line(
            Text(
                "  Ctrl+Q to quit · Shift+drag to copy",
                style="dim #666666",
            )
        )
        panel.write_line("")

        # Start the remote command drain timer so Slack/Telegram
        # commands are processed when a project is loaded.
        self._start_remote_drain()

    def _heal_stale_agent_running(self) -> None:
        """Clear ``session.agent_running`` if no worker is actually alive.

        Defensive self-heal for a class of bugs where the flag gets
        pinned True — worker killed externally, finally block
        skipped by an async cancellation at the wrong moment,
        future refactor that forgets to clear the flag, etc. If
        the flag says an agent is running but NONE of our known
        worker names (free_text, agent:*) is in a non-terminal
        state, the flag is stale and we reset it so user input
        isn't trapped in the queue branch forever.
        """
        if not self.session.agent_running:
            return
        from textual.worker import WorkerState

        live_states = {WorkerState.PENDING, WorkerState.RUNNING}
        for worker in self.workers:
            name = worker.name or ""
            if name == "free_text" or name.startswith("agent:"):
                if worker.state in live_states:
                    return  # A real worker is alive — flag is accurate.
        # Flag lies. Reset it.
        self.session.set_agent_idle()
        self.log.warning(
            "agent_running was stale (no live worker found) — self-healed"
        )

    @staticmethod
    def _is_path_not_command(text: str) -> bool:
        """Distinguish file paths from slash commands.

        ``/run baseline`` → first token is ``run`` (no slash) → command.
        ``/home/user/data`` → first token is ``home/user/data`` → path.
        """
        after_slash = text[1:]
        first_token = after_slash.split()[0] if after_slash.strip() else ""
        return "/" in first_token

    def _cancel_active_worker(self) -> None:
        """Cancel the active agent worker and reset state.

        Unblocks the stdin reader (so the worker thread isn't stuck
        on queue.get), cancels Textual workers, and resets the
        session's agent_running flag. This makes /stop work reliably
        even during interactive prompts like /new.
        """
        from textual.worker import WorkerState

        from urika.tui.agent_worker import get_active_stdin_reader

        if not self.session.agent_running:
            self._run_with_panel_output(
                lambda: print("  No agent is currently running.")
            )
            return

        agent = self.session.agent_name or "command"

        # Unblock the stdin reader first — the worker thread may be
        # stuck on _queue.get() waiting for user input.
        reader = get_active_stdin_reader()
        if reader is not None:
            reader.cancel()

        # Cancel any live agent/free_text workers.
        live_states = {WorkerState.PENDING, WorkerState.RUNNING}
        for worker in self.workers:
            name = worker.name or ""
            if name == "free_text" or name.startswith("agent:"):
                if worker.state in live_states:
                    worker.cancel()

        # Write stop flag for run_experiment's PauseController
        if self.session.project_path:
            flag = self.session.project_path / ".urika" / "pause_requested"
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text("stop", encoding="utf-8")

        # Reset session state (the worker's finally clause will also
        # try this, but we do it eagerly so the UI unblocks now).
        self.session.set_agent_idle()

        self._run_with_panel_output(
            lambda: print(f"  Stopped /{agent}.")
        )

        # Refresh the input bar prompt
        from urika.tui.widgets.input_bar import InputBar as IB

        try:
            self.query_one(IB).refresh_prompt()
        except Exception:
            pass

    @on(InputBar.CommandSubmitted)
    def _on_command(self, event: InputBar.CommandSubmitted) -> None:
        """Dispatch user input to command handlers, queue, or free-text path."""
        text = event.value

        # Self-heal any stale agent_running flag before we check it,
        # so the user isn't trapped in the queue branch if a previous
        # worker exited without running its finally clause.
        self._heal_stale_agent_running()

        if text.startswith("/") and not self._is_path_not_command(text):
            self._dispatch_command(text)
        elif self.session.agent_running:
            # A worker is running. Three paths, in priority:
            #
            #   (a) A stdin reader is active — a click.prompt /
            #       input() inside the worker is blocked waiting for
            #       a line. Feed the text to it so the call unblocks.
            #
            #   (b) An /run is in progress — queue the text so
            #       commands_run.py's _get_user_input callback can
            #       inject it on the orchestrator's next turn (this is
            #       how mid-run user steering works).
            #
            #   (c) Any other agent (/advisor, /finalize, /report,
            #       /summarize, etc.) — reject. Pre-v0.4.2 Package K
            #       this branch silently queued the text and the
            #       queue was never drained, so user input vanished.
            #       Now we surface the same panel hint as
            #       _dispatch_free_text uses (Package I-8).
            from urika.tui.agent_worker import get_active_stdin_reader
            from rich.text import Text

            reader = get_active_stdin_reader()
            if reader is not None:
                reader.feed(text)
                panel = self.query_one(OutputPanel)
                panel.write_line(Text(f"  > {text}", style="dim"))
            elif self.session.active_command == "run":
                self.session.queue_input(text)
                panel = self.query_one(OutputPanel)
                panel.write_line(f"  [queued for next turn] {text}")
            else:
                try:
                    panel = self.query_one(OutputPanel)
                    panel.write_line("")
                    panel.write_line(
                        Text(
                            f"  ⏳ Agent /{self.session.active_command or 'unknown'} "
                            f"busy. /stop to halt, /pause is for /run "
                            f"only — or open another terminal for a "
                            f"parallel orchestrator chat.",
                            style="yellow",
                        )
                    )
                except Exception:
                    pass
        else:
            self._dispatch_free_text(text)

    def _run_with_panel_output(self, func) -> None:
        """Run ``func`` so its stdout lands in the OutputPanel.

        Handles both capture-active and capture-inactive contexts. If
        the process ``sys.stdout`` is already a ``_TuiWriter`` (i.e.
        a worker thread installed one), call ``func`` directly — the
        existing writer is thread-safe and routes output to the panel
        via ``call_from_thread``. Otherwise, enter ``self._capture``
        briefly so the function's prints are captured.

        This replaces the older pattern of blindly doing
        ``with self._capture: ...`` which crashed when a worker was
        active (nested captures raise RuntimeError by design).
        """
        import sys

        from urika.tui.capture import _TuiWriter

        if isinstance(sys.stdout, _TuiWriter):
            func()
        else:
            with self._capture:
                func()

    def _dispatch_command(self, text: str) -> None:
        """Parse and execute a slash command.

        Three routes:

        * ``/quit`` — handled inline (no entry in the commands registry),
          always available.
        * Anything else while an agent worker is running — rejected with
          a busy hint, except ``/stop`` which writes a cooperative stop
          flag that the experiment runner polls.
        * Blocking commands (agent-invoking) — dispatched to a
          thread-based worker via :func:`run_command_in_worker`.
        * Everything else — executed inline via
          :meth:`_run_with_panel_output` which picks the right
          capture strategy based on runtime state.
        """
        from rich.text import Text

        parts = text[1:].split(" ", 1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Echo the slash command into the panel so the user can see
        # what they typed, with a blank line above for visual
        # separation from the previous output block.
        panel = self.query_one(OutputPanel)
        panel.write_line("")
        panel.write_line(Text(f"> {text}", style="bold #4a9eff"))

        # /quit is handled inline — there is no "quit" in repl.commands
        # (the old REPL handled it in its main loop). Always available.
        if cmd_name == "quit":
            self.session.save_usage()
            self.exit()
            return

        # /stop — cancel the active worker, unblock its stdin reader,
        # and reset agent state. Handled here (not via the command
        # registry) because it needs direct access to workers and the
        # stdin reader, and must work even without a project loaded.
        if cmd_name == "stop":
            self._cancel_active_worker()
            return

        from urika.cli_display import print_error
        from urika.repl.commands import PROJECT_COMMANDS, get_all_commands

        busy_hint = (
            f"Agent busy running /{self.session.agent_name or 'command'}"
            " — wait or use /stop"
        )

        # Busy guard: while an agent worker is running, reject any
        # slash command that isn't an escape hatch. The hint is
        # printed via ``_run_with_panel_output`` which picks the
        # right capture strategy based on the actual ``sys.stdout``
        # state (worker's _TuiWriter if one is installed; fresh
        # self._capture otherwise).
        if self.session.agent_running:
            if cmd_name not in _ALWAYS_ALLOWED_COMMANDS:
                self._run_with_panel_output(lambda: print_error(busy_hint))
                return
            # Escape hatch path: fall through to normal dispatch.

        all_cmds = get_all_commands(self.session)
        if cmd_name not in all_cmds:

            def _print_unknown() -> None:
                if cmd_name in PROJECT_COMMANDS and not self.session.has_project:
                    print_error("Load a project first: /project <name>")
                else:
                    print_error(
                        f"Unknown command: /{cmd_name}. Type /help for commands."
                    )

            self._run_with_panel_output(_print_unknown)
            return

        handler = all_cmds[cmd_name]["func"]

        # Worker commands run in a background thread with OutputCapture
        # (stdout → panel) and _TuiStdinReader (stdin ← InputBar).
        # This handles both long-running agents AND interactive prompts
        # (click.prompt / input) — user types answers in the InputBar
        # and they flow to the worker's stdin queue.
        if cmd_name in _WORKER_COMMANDS:
            if self.session.agent_running:
                self._run_with_panel_output(lambda: print_error(busy_hint))
                return
            run_command_in_worker(self, handler, args, cmd_name)
            return

        # Non-worker inline path — instant commands like /help, /list,
        # /tools, /status, /project, etc.
        def _run_handler_inline() -> None:
            try:
                handler(self.session, args)
            except SystemExit:
                self.session.save_usage()
                self.exit()
            except Exception as exc:
                print_error(f"Error: {exc}")

        self._run_with_panel_output(_run_handler_inline)

        input_bar = self.query_one(InputBar)
        input_bar.refresh_prompt()

    def _dispatch_free_text(self, text: str) -> None:
        """Send free text to the orchestrator on a Textual Worker.

        Works both with and without a project loaded. Without a
        project, the orchestrator's system prompt provides guidance
        about available commands and helps the user get started.
        With a project, it answers questions about the data, plans
        experiments, and coordinates agents.
        """
        # v0.4.2 Package I: block free-text injection while an agent
        # is running. Pre-fix the TUI queued the text and replayed it
        # after the worker exited — but that has subtle problems:
        #
        #   * stale-context: the message was typed at moment A and
        #     executed at moment B with different orchestrator state
        #     (and possibly different project state if the user did
        #     anything between)
        #   * queue-vs-drain race (audit BUG#4) — drain ran inside the
        #     finally AFTER set_agent_idle cleared agent_running, so
        #     fast typing could spawn parallel workers
        #   * REPL parity — the classic prompt_toolkit REPL is
        #     blocking by design; a user gets a different mental
        #     model in the TUI for no good reason
        #   * silently buries input — long /run could swallow several
        #     "what should I try?" messages and fire them all at
        #     once when it ended
        #
        # Right escape hatch is "open another terminal" which gives a
        # fresh OrchestratorChat with clean state. The remote drain
        # path (Slack/Telegram) keeps its own queue because remote
        # callers don't have an interactive prompt to block.
        if self.session.agent_running:
            try:
                panel = self.query_one(OutputPanel)
                from rich.text import Text

                panel.write_line("")
                panel.write_line(
                    Text(
                        "  ⏳ Agent busy. Press Ctrl+C to cancel, "
                        "/stop to halt, /pause to pause after the "
                        "current turn — or open another terminal "
                        "for a parallel orchestrator chat.",
                        style="yellow",
                    )
                )
            except Exception:
                pass
            return
        self.run_worker(self._run_free_text(text), name="free_text")

    async def _run_free_text(self, text: str) -> None:
        """Worker coroutine: run the orchestrator and display its reply.

        Runs inside Textual's event loop, so `orchestrator.chat` is
        awaited naturally. Session bookkeeping (tokens, cost, model,
        conversation history) mirrors the REPL's `_handle_free_text`
        so the two paths stay observably equivalent.

        ``set_agent_running`` is called INSIDE the try block so the
        finally is guaranteed to clear it even if orchestrator
        construction, query_one, or any other early-path call
        raises. A previous version set the flag before the try,
        which left it pinned True forever if a query_one raised
        NoMatches during app teardown — subsequent messages then
        got trapped in the ``agent_running`` queue branch in
        ``_on_command``.
        """
        from urika.cli_display import format_agent_output

        try:
            # set_agent_running INSIDE the try (not before it) so the
            # finally clause is guaranteed to clear the flag even if
            # orchestrator construction, query_one, or any other
            # early-path call raises. The previous iteration had it
            # before the try and the finally never ran if early
            # setup exploded, leaving agent_running pinned True and
            # trapping every subsequent message in the queue branch.
            self.session.set_agent_running(agent_name="orchestrator")
            panel = self.query_one(OutputPanel)

            # Echo the user's message with a blank line above for
            # visual separation from the previous output block.
            from rich.text import Text

            panel.write_line("")
            panel.write_line(Text(f"> {text}", style="bold #4a9eff"))

            # Create-or-reuse orchestrator. Reset when the project
            # changes so we don't bleed context between projects.
            if (
                self._orchestrator is None
                or self._orchestrator.project_dir != self.session.project_path
            ):
                self._orchestrator = OrchestratorChat(
                    project_dir=self.session.project_path
                )
            orch = self._orchestrator

            # Stream both tool use AND text output to the panel so
            # the user can see what the orchestrator is doing in
            # real-time — reading files, calling subagents, thinking.
            #
            # NOTE: _run_free_text is an async coroutine on the event
            # loop thread, NOT a worker thread. So _on_output is also
            # called on the event loop thread. call_from_thread would
            # FAIL (raises RuntimeError from the same thread, silently
            # caught). Write to the panel directly instead.
            def _on_output(kind: str, content: str) -> None:
                try:
                    if kind == "tool":
                        parts = content.split(": ", 1)
                        tool_name = parts[0]
                        detail = parts[1] if len(parts) > 1 else ""
                        short = (
                            detail[:120] + "…"
                            if len(detail) > 120
                            else detail
                        )
                        panel.write_line(
                            Text(
                                f"  ▸ {tool_name} {short}",
                                style="dim #4a9eff",
                            )
                        )
                    elif kind == "text" and content.strip():
                        panel.write_line(content)
                except Exception:
                    pass

            result = await orch.chat(text, on_output=_on_output)
            response = result.get("response", "") or ""

            # Update session stats for the status bar.
            self.session.total_tokens_in += result.get("tokens_in", 0) or 0
            self.session.total_tokens_out += result.get("tokens_out", 0) or 0
            self.session.total_cost_usd += result.get("cost_usd", 0) or 0
            self.session.agent_calls += 1
            if result.get("model"):
                self.session.model = result["model"]

            panel.write_line("")
            panel.write_line(format_agent_output(response))
            panel.write_line("")

            self.session.last_assistant_response = response
            self.session.add_message("user", text)
            self.session.add_message("assistant", response[:500])

            # v0.4.2: parse advisor/orchestrator suggestions out of the
            # response so /run picks them up via session.pending_suggestions
            # instead of falling through to "resume the most recent
            # pending experiment" — which silently re-ran an old
            # failed/stuck experiment from a prior crash. The classic
            # prompt_toolkit REPL has always done this (see
            # urika.repl.main._offer_to_run_suggestions); this is the
            # TUI-side parity fix.
            try:
                from urika.orchestrator.parsing import parse_suggestions

                parsed = parse_suggestions(response)
                if parsed and parsed.get("suggestions"):
                    self.session.pending_suggestions = parsed["suggestions"]
                    n = len(self.session.pending_suggestions)
                    panel.write_line(
                        Text(
                            f"  ✦ {n} experiment suggestion(s) "
                            f"captured. Type /run to start.",
                            style="bold #4a9eff",
                        )
                    )
                    panel.write_line("")
            except Exception:
                # Suggestion parsing is best-effort — never let it
                # break chat. A malformed JSON block in the response
                # is the expected failure mode here.
                pass
        except Exception as exc:
            # Not a silent swallow — the error lands in the panel
            # (via query_one if still available) or the Textual log
            # if the panel itself is the thing that raised.
            try:
                self.query_one(OutputPanel).write_line(
                    f"  \u2717 Error: {exc}"
                )
            except Exception:
                self.log.error(f"chat error (panel unavailable): {exc}")
        finally:
            self.session.set_agent_idle()
            # v0.4.2 Package I: queue-and-drain is gone. Free-text
            # while busy is now blocked at submission time
            # (_dispatch_free_text rejects with a panel hint), so
            # there's nothing to drain on idle. The remote drain
            # path uses its own queue + 2s timer (_drain_remote_queue)
            # for Slack/Telegram callers who don't have an
            # interactive prompt to gate against.

    def action_cancel_agent(self) -> None:
        """Ctrl+C handler.

        When an agent is running: cancel the worker immediately —
        unblocks the stdin reader, cancels Textual workers, resets
        agent state. Works for both interactive commands (/new stuck
        on a prompt) and long-running agents (/run between subagents).

        When no agent is running: treat Ctrl+C as a quit request.
        Otherwise users with no visible keybindings get trapped in
        the TUI with Ctrl+C as a silent no-op.
        """
        if not self.session.agent_running:
            self.action_quit_app()
            return

        self._cancel_active_worker()

    def action_copy_last_response(self) -> None:
        """Ctrl+Y: copy the most recent assistant response to the clipboard."""
        response = self.session.last_assistant_response
        if not response:
            self.notify("No response to copy yet.", severity="warning", timeout=3)
            return
        try:
            import pyperclip

            pyperclip.copy(response)
            preview = response[:60].replace("\n", " ")
            if len(response) > 60:
                preview += "…"
            self.notify(
                f'Copied {len(response)} chars: “{preview}”',
                title="Copied to clipboard",
                timeout=3,
            )
        except Exception as exc:
            self.notify(f"Clipboard copy failed: {exc}", severity="error", timeout=5)

    # ── Remote command drain (Slack / Telegram) ────────────

    def _start_remote_drain(self) -> None:
        """Start a 2-second timer to drain remote commands from
        Slack/Telegram. The notification bus queues commands into
        ``session._remote_queue``; this timer dispatches them through
        the same handlers as terminal slash commands.
        """
        self.set_interval(2.0, self._drain_remote_queue)

    def _drain_remote_queue(self) -> None:
        """Process one queued remote command per tick.

        Skipped when an agent is already running — commands stay
        queued until idle. Free-text commands (no slash prefix) go
        to the orchestrator.
        """
        if self.session.agent_running:
            return
        if not self.session.has_remote_command:
            return

        item = self.session.pop_remote_command()
        if item is None:
            return

        cmd, args, respond = item
        from rich.text import Text

        panel = self.query_one(OutputPanel)

        # "ask" is free text from Slack/Telegram — route to orchestrator.
        # Set agent_running synchronously BEFORE spawning the worker
        # to prevent the next drain tick from spawning a second one.
        if cmd == "ask":
            short = args[:60] + "…" if len(args) > 60 else args
            panel.write_line("")
            panel.write_line(
                Text(f"  [Remote] {short}", style="bold #ffcc66")
            )
            self.session.set_agent_running(agent_name="orchestrator")
            self._dispatch_remote_free_text(args, respond)
            return

        cmd_text = f"/{cmd} {args}".strip()
        panel.write_line("")
        panel.write_line(
            Text(f"  [Remote] {cmd_text}", style="bold #ffcc66")
        )

        # Route through the normal TUI dispatch path. Worker commands
        # run in a background thread; read-only ones run inline.
        from urika.repl.commands import get_all_commands

        all_cmds = get_all_commands(self.session)
        if cmd not in all_cmds:
            msg = f"Unknown remote command: /{cmd}"
            panel.write_line(f"  {msg}")
            if respond:
                respond(msg)
            return

        handler = all_cmds[cmd]["func"]

        # Set remote flags so handlers skip interactive prompts
        self.session._is_remote_command = True
        self.session._remote_respond = respond

        if cmd in _WORKER_COMMANDS:
            # Set agent_running BEFORE spawning the worker to prevent
            # the drain timer from spawning a second one in the gap.
            self.session.set_agent_running(agent_name=cmd)

            def _remote_worker_done() -> None:
                self.session._is_remote_command = False
                self.session._remote_respond = None
                if respond:
                    respond(f"/{cmd} completed.")

            def _remote_handler(session, a):
                try:
                    handler(session, a)
                finally:
                    try:
                        self.call_from_thread(_remote_worker_done)
                    except RuntimeError:
                        self.session._is_remote_command = False
                        self.session._remote_respond = None

            run_command_in_worker(self, _remote_handler, args, cmd)
        else:
            # Inline (read-only commands like /status, /results)
            try:
                self._run_with_panel_output(
                    lambda: handler(self.session, args)
                )
                if respond:
                    respond(f"/{cmd} completed.")
            except Exception as exc:
                if respond:
                    respond(f"/{cmd} error: {exc}")
            finally:
                self.session._is_remote_command = False
                self.session._remote_respond = None

    def _dispatch_remote_free_text(self, text: str, respond) -> None:
        """Send remote free text to the orchestrator, reply via channel.

        Runs as an async worker (like local free text) but sends the
        orchestrator's response back to Slack/Telegram.
        """

        async def _run_remote_chat() -> None:
            # agent_running is set by the caller (_drain_remote_queue)
            # BEFORE this worker is spawned, to prevent the drain timer
            # from spawning a second worker in the gap.
            try:
                if (
                    self._orchestrator is None
                    or self._orchestrator.project_dir != self.session.project_path
                ):
                    self._orchestrator = OrchestratorChat(
                        project_dir=self.session.project_path
                    )
                orch = self._orchestrator
                panel = self.query_one(OutputPanel)

                def _on_output(kind: str, content: str) -> None:
                    try:
                        if kind == "text" and content.strip():
                            panel.write_line(content)
                    except Exception:
                        pass

                result = await orch.chat(text, on_output=_on_output)
                response = result.get("response", "") or ""

                self.session.total_tokens_in += result.get("tokens_in", 0) or 0
                self.session.total_tokens_out += result.get("tokens_out", 0) or 0
                self.session.total_cost_usd += result.get("cost_usd", 0) or 0
                self.session.agent_calls += 1

                # Save conversation history so follow-up questions
                # from the same remote user have context.
                self.session.last_assistant_response = response
                self.session.add_message("user", text)
                self.session.add_message("assistant", response[:500])

                # v0.4.2 (Package I): parse advisor/orchestrator suggestions
                # so a remote-issued /run picks them up via
                # session.pending_suggestions. Package H wired this in for
                # local free-text but missed the parallel remote-chat path
                # — Slack/Telegram users hit the same advisor->run silent
                # fail-to-pending bug. Same silent-store form as the local
                # path; the user gets a confirmation chat-line too.
                try:
                    from urika.orchestrator.parsing import parse_suggestions

                    parsed = parse_suggestions(response)
                    if parsed and parsed.get("suggestions"):
                        self.session.pending_suggestions = parsed["suggestions"]
                except Exception:
                    pass

                from urika.cli_display import format_agent_output

                panel.write_line("")
                panel.write_line(format_agent_output(response))

                # Send response back to Slack/Telegram
                if respond and response:
                    reply = response[:4000]
                    if self.session.pending_suggestions:
                        n = len(self.session.pending_suggestions)
                        reply += (
                            f"\n\n[{n} experiment suggestion(s) captured. "
                            f"Send /run to start.]"
                        )
                    respond(reply)
            except Exception as exc:
                try:
                    self.query_one(OutputPanel).write_line(
                        f"  \u2717 Remote chat error: {exc}"
                    )
                except Exception:
                    pass
                if respond:
                    respond(f"Error: {exc}")
            finally:
                self.session.set_agent_idle()

        self.run_worker(_run_remote_chat(), name="free_text")

    def action_quit_app(self) -> None:
        """Quit cleanly — stop notification bus, save usage."""
        if self.session.notification_bus is not None:
            try:
                self.session.notification_bus.stop()
            except Exception:
                pass
        self.session.save_usage()
        self.exit()
