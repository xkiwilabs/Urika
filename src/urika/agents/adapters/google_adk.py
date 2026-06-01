"""Adapter for the ``google-adk`` SDK (Google Agent Development Kit).

Task 3.1 ships the skeleton: the class exists, declares the
``AgentRunner`` protocol, and surfaces a clear "extra not installed"
error when the ADK modules are absent. Task 3.2 will fill in
:meth:`_run_with_sdk` — translating an ``AgentConfig`` into a
``google.adk.agents.Agent``, registering the six shared function
tools, driving the ADK's async event stream via
``google.adk.runners.Runner``, and mapping events back to
:class:`AgentResult`.

This adapter is reached via :func:`urika.agents.runner_registry.runner_for`
when the model name starts with ``gemini-``. ``runner_registry``
imports this module lazily so callers that never route to Gemini
don't pay the import cost, and so the registry test suite stays
green on dev boxes that haven't installed the extra.

Implementation note for Task 3.2: the ADK exposes both
``google.adk.agents`` (the ``Agent`` class) and
``google.adk.runners`` (the ``Runner`` driver). Both imports must
succeed for the SDK path to be usable, so the skeleton checks both
in its ``try`` block and treats either ``ImportError`` as
"extra not installed".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner


class GoogleADKRunner(AgentRunner):
    """``AgentRunner`` backed by the ``google-adk`` SDK."""

    @classmethod
    def required_env(cls) -> tuple[str, ...]:
        """Google ADK reads ``GEMINI_API_KEY`` from the env."""
        return ("GEMINI_API_KEY",)

    async def run(
        self,
        config: AgentConfig,
        prompt: str,
        *,
        on_message: Callable[..., Any] | None = None,
    ) -> AgentResult:
        """Run an agent via the google-adk SDK.

        When the optional ``[google]`` extra is not installed, returns
        an :class:`AgentResult` with ``success=False`` and an
        actionable error string. This is preferable to raising
        ``ImportError`` at module-import time — the registry can still
        route to this adapter and the caller gets a structured failure
        they can surface to the user with install instructions.

        Both ``google.adk.agents`` and ``google.adk.runners`` must
        import for the SDK path to be reachable; either ImportError
        triggers the "extra not installed" branch.
        """
        try:
            from google.adk.agents import Agent  # noqa: F401
            from google.adk.runners import Runner  # noqa: F401
        except ImportError:
            return AgentResult(
                success=False,
                messages=[],
                text_output="",
                session_id="",
                error=(
                    "google-adk extra not installed — run "
                    "`pip install urika[google]` to enable "
                    "gemini-* model routing."
                ),
                error_category="config",
                model=config.model or "",
            )
        return await self._run_with_sdk(config, prompt, on_message=on_message)

    async def _run_with_sdk(
        self,
        config: AgentConfig,
        prompt: str,
        *,
        on_message: Callable[..., Any] | None = None,
    ) -> AgentResult:
        """Real SDK call path — builds an Agent + drives Runner.run_async.

        The ADK's execution model is different from the OpenAI Agents
        SDK: instead of an awaited ``Runner.run`` that returns a
        single ``RunResult``, the ADK exposes an async event stream
        (``Runner.run_async``) that yields ``LlmResponse`` /
        ``ToolCall`` / ``ToolResult`` events. This adapter folds the
        stream into a single :class:`AgentResult` by accumulating
        ``event.text`` and pulling token counts off whichever event
        carries the final usage payload.

        ``on_message`` fires per text-bearing event — the stream
        model makes this natural here, unlike the OpenAI adapter's
        synchronous-result API where it had to be a no-op.

        Notable ADK quirks vs. the OpenAI adapter:

        * ``Agent(instruction=...)`` is singular (OpenAI uses
          ``instructions=``). A regression on the keyword would
          surface as a TypeError at agent construction.
        * Token fields on Gemini are conventionally
          ``prompt_token_count`` / ``candidates_token_count``, but
          the ADK normalises these on the event object to flat
          ``input_tokens`` / ``output_tokens`` — we read those and
          map onto :class:`AgentResult` 's flat fields, same shape
          as the Claude + OpenAI adapters.
        * ADK auto-discovers tool signatures via reflection — plain
          Python functions can be passed in ``tools=[...]`` without
          a decorator. If a future ADK release requires
          ``google.adk.tools.FunctionTool`` wrapping, that's the
          single spot to update.
        """
        from google.adk.agents import Agent
        from google.adk.runners import Runner

        from urika.agents.pricing import cost_for
        from urika.agents.tools import ToolRegistry
        from urika.agents.tools.bash import bash as bash_tool
        from urika.agents.tools.edit import edit as edit_tool
        from urika.agents.tools.glob import glob as glob_tool
        from urika.agents.tools.grep import grep as grep_tool
        from urika.agents.tools.read import read as read_tool
        from urika.agents.tools.write import write as write_tool

        security = config.security
        # Tools that need a project root (bash, glob) fall back to
        # ``Path.cwd()`` only when no cwd is configured — should be
        # vanishingly rare in agent runs but keeps the wrapper
        # defensive. Mirrors the OpenAI adapter's convention.
        project_dir: Path = config.cwd or Path.cwd()

        def _wrap(tool_result: Any) -> str:
            return (
                tool_result.output if tool_result.ok else f"ERROR: {tool_result.error}"
            )

        # ADK auto-discovers function signatures via reflection, so
        # the six tool wrappers are plain functions. If a future ADK
        # release ships ``google.adk.tools.FunctionTool`` as a
        # required wrapper, decorate these in one swoop.
        def bash(cmd: str) -> str:
            return _wrap(bash_tool(cmd, security=security, project_dir=project_dir))

        def read(path: str) -> str:
            return _wrap(read_tool(path, security=security))

        def write(path: str, content: str) -> str:
            return _wrap(write_tool(path, content, security=security))

        def grep(pattern: str, path: str) -> str:
            return _wrap(grep_tool(pattern, path, security=security))

        def glob(pattern: str) -> str:
            return _wrap(glob_tool(pattern, security=security, project_dir=project_dir))

        def edit(path: str, old_string: str, new_string: str) -> str:
            return _wrap(edit_tool(path, old_string, new_string, security=security))

        tools_by_name = {
            "bash": bash,
            "read": read,
            "write": write,
            "grep": grep,
            "glob": glob,
            "edit": edit,
        }
        tools = [tools_by_name[n] for n in ToolRegistry.for_role(config.name)]

        agent = Agent(
            name=config.name,
            instruction=config.system_prompt,
            model=config.model,
            tools=tools,
        )
        runner = Runner(agent)

        model_name = config.model or ""
        accumulated_text = ""
        in_tok = 0
        out_tok = 0

        try:
            async for event in runner.run_async(prompt):
                event_text = getattr(event, "text", None)
                if event_text:
                    accumulated_text += event_text
                    if on_message is not None:
                        # Fire per text-bearing event — the stream
                        # model lets us offer parity with the Claude
                        # adapter's per-message callback that the
                        # OpenAI adapter can't currently provide.
                        try:
                            on_message(event_text)
                        except Exception:  # noqa: BLE001 — user callback
                            # A misbehaving callback must not break
                            # the agent loop. Swallow + continue.
                            pass
                # Usage tokens may ride the final event or appear
                # incrementally — keep updating so the trailing
                # event's totals win. The ``or in_tok`` guard avoids
                # clobbering an earlier non-zero value with a 0 on
                # an event that doesn't carry usage.
                in_tok = getattr(event, "input_tokens", in_tok) or in_tok
                out_tok = getattr(event, "output_tokens", out_tok) or out_tok
        except Exception as exc:  # noqa: BLE001 — SDK boundary
            return AgentResult(
                success=False,
                messages=[],
                text_output=accumulated_text,
                session_id="",
                error=str(exc),
                model=model_name,
            )

        cost = cost_for(model_name, in_tok, out_tok)
        return AgentResult(
            success=True,
            messages=[],
            text_output=accumulated_text,
            session_id="",
            tokens_in=in_tok,
            tokens_out=out_tok,
            cost_usd=cost,
            model=model_name,
        )
