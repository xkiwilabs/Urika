"""Adapter for the ``openai-agents`` SDK (OpenAI Agents framework).

Task 2.1 shipped the skeleton: the class exists, declares the
``AgentRunner`` protocol, and surfaces a clear "extra not installed"
error when the ``agents`` SDK module is absent. Task 2.2 fills in
:meth:`_run_with_sdk` — translating an ``AgentConfig`` into an
``agents.Agent``, registering the six shared function tools, calling
``agents.Runner.run``, and mapping the SDK's result back to
:class:`AgentResult`.

This adapter is reached via :func:`urika.agents.runner_registry.runner_for`
when the model name starts with ``gpt-``, ``o3``, ``o4`` or ``o5``.
``runner_registry`` imports this module lazily so callers that never
route to OpenAI don't pay the import cost, and so the registry test
suite stays green on dev boxes that haven't installed the extra.

Design notes:

* Token + cost data is populated into the existing
  ``AgentResult.tokens_in`` / ``tokens_out`` / ``cost_usd`` fields,
  matching what ``ClaudeSDKRunner`` already produces. We do NOT add
  a public ``usage`` dict field — that would be a v0.7.0 API
  expansion adapter consumers don't need (the dashboard's usage tab
  already reads the three top-level fields).
* The six function-tool wrappers close over the agent's
  ``SecurityPolicy`` and ``project_dir`` so every tool dispatch
  re-enters the same allow-list checks the Claude adapter enforces
  via ``can_use_tool``. The ``ToolRegistry.for_role`` filter is
  applied even though it currently returns all six — keeps the
  per-role tightening path open without another diff later.
* Any exception from ``Runner.run`` is converted to an
  ``AgentResult(success=False, error=...)`` — the AgentRunner
  contract forbids propagating exceptions, so the orchestrator's
  existing pause/resume logic stays in charge.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from urika.agents.adapters._common import agent_stream_timeout, bash_timeout_seconds
from urika.agents.config import AgentConfig
from urika.agents.error_classify import classify_error
from urika.agents.runner import AgentResult, AgentRunner


class OpenAIAgentsRunner(AgentRunner):
    """``AgentRunner`` backed by the ``openai-agents`` SDK."""

    @classmethod
    def required_env(cls) -> tuple[str, ...]:
        """OpenAI Agents SDK reads ``OPENAI_API_KEY`` from the env."""
        return ("OPENAI_API_KEY",)

    async def run(
        self,
        config: AgentConfig,
        prompt: str,
        *,
        on_message: Callable[..., Any] | None = None,
    ) -> AgentResult:
        """Run an agent via the openai-agents SDK.

        When the optional ``[openai]`` extra is not installed, returns
        an :class:`AgentResult` with ``success=False`` and an
        actionable error string. This is preferable to raising
        ``ImportError`` at module-import time — the registry can still
        route to this adapter and the caller gets a structured failure
        they can surface to the user with install instructions.
        """
        try:
            import agents  # noqa: F401  — the openai-agents SDK
        except ImportError:
            return AgentResult(
                success=False,
                messages=[],
                text_output="",
                session_id="",
                error=(
                    "openai-agents extra not installed — run "
                    "`pip install urika[openai]` to enable "
                    "gpt-*/o3-o5 model routing."
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
        """Real SDK call path — builds an Agent + Runner.run().

        ``on_message`` is accepted for protocol parity with
        :class:`~urika.agents.adapters.claude_sdk.ClaudeSDKRunner` but
        not invoked here: the openai-agents SDK doesn't expose a
        per-message stream callback in its synchronous-result API.
        When the SDK ships streaming-result support we can wire this
        in — until then, the dashboard's SSE log path will still see
        per-tool-call output via the function-tool wrappers if the
        caller chooses to instrument them.
        """
        import agents as openai_agents_sdk

        from urika.agents.pricing import cost_for
        from urika.agents.tools import ToolRegistry
        from urika.agents.tools.bash import bash as bash_tool
        from urika.agents.tools.edit import edit as edit_tool
        from urika.agents.tools.glob import glob as glob_tool
        from urika.agents.tools.grep import grep as grep_tool
        from urika.agents.tools.read import read as read_tool
        from urika.agents.tools.write import write as write_tool
        from urika.core.compliance import scrub_oauth_env_for_subprocess

        security = config.security
        # ``AgentConfig`` has no ``project_dir`` field — the SDK
        # adapter mirrors the Claude adapter's convention and reads
        # ``cwd``. Tools that need a project root (bash, glob) fall
        # back to ``Path.cwd()`` only when no cwd is configured,
        # which should be vanishingly rare in agent runs but keeps
        # the wrapper defensive.
        project_dir: Path = config.cwd or Path.cwd()

        agent_env = scrub_oauth_env_for_subprocess(config.env)
        # Per-Bash-call wall-clock cap — the Claude adapter injects
        # ``max_method_seconds`` via ``can_use_tool``; here we thread
        # it straight into the shared bash tool.
        bash_timeout = bash_timeout_seconds(config.max_method_seconds)

        def _wrap(tool_result: Any) -> str:
            return (
                tool_result.output if tool_result.ok else f"ERROR: {tool_result.error}"
            )

        @openai_agents_sdk.function_tool
        def bash(cmd: str) -> str:
            return _wrap(
                bash_tool(
                    cmd,
                    security=security,
                    project_dir=project_dir,
                    env=agent_env,
                    timeout_seconds=bash_timeout,
                )
            )

        @openai_agents_sdk.function_tool
        def read(path: str) -> str:
            return _wrap(read_tool(path, security=security))

        @openai_agents_sdk.function_tool
        def write(path: str, content: str) -> str:
            return _wrap(write_tool(path, content, security=security))

        @openai_agents_sdk.function_tool
        def grep(pattern: str, path: str) -> str:
            return _wrap(grep_tool(pattern, path, security=security))

        @openai_agents_sdk.function_tool
        def glob(pattern: str) -> str:
            return _wrap(glob_tool(pattern, security=security, project_dir=project_dir))

        @openai_agents_sdk.function_tool
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

        agent = openai_agents_sdk.Agent(
            name=config.name,
            instructions=config.system_prompt,
            model=config.model,
            tools=tools,
        )
        max_turns = config.max_turns
        model_name = config.model or ""
        # Same wall-clock knob as the Claude adapter — a hung HTTP
        # stream inside ``Runner.run`` previously hung the whole
        # orchestrator turn forever (no per-call timeout in the SDK).
        _stream_timeout = agent_stream_timeout()

        try:
            result = await asyncio.wait_for(
                openai_agents_sdk.Runner.run(agent, prompt, max_turns=max_turns),
                timeout=_stream_timeout,
            )
        except asyncio.TimeoutError:
            return AgentResult(
                success=False,
                messages=[],
                text_output="",
                session_id="",
                error=(
                    f"OpenAI agent call timed out after {_stream_timeout:.0f}s "
                    "(set URIKA_AGENT_STREAM_TIMEOUT to adjust)"
                ),
                error_category="transient",
                model=model_name,
                tokens_in=0,
                tokens_out=0,
                cost_usd=cost_for(model_name, 0, 0),
            )
        except Exception as exc:  # noqa: BLE001 — SDK boundary
            # The openai-agents SDK exposes ``RunResult.usage`` only on
            # the success path — ``Runner.run`` is an all-or-nothing
            # awaitable that doesn't surface partial usage when it
            # throws. So tokens/cost are 0 / 0.0 here, but record them
            # explicitly (matching the Claude + Google adapters' shape)
            # so downstream consumers don't have to special-case
            # AgentResult defaults vs. real measurements on the failure
            # path. v0.7.0 release-blocker parity fix.
            return AgentResult(
                success=False,
                messages=[],
                text_output="",
                session_id="",
                error=str(exc),
                error_category=classify_error(str(exc)),
                model=model_name,
                tokens_in=0,
                tokens_out=0,
                cost_usd=cost_for(model_name, 0, 0),
            )

        # Usage attribute naming: the openai-agents SDK mirrors the
        # Anthropic "input_tokens / output_tokens" convention in its
        # ``RunResult.usage`` object (per the SDK's public examples).
        # If the real SDK ships with ``prompt_tokens`` / ``completion_tokens``
        # instead, this is the one spot to update — the rest of Urika
        # only sees the flattened ``tokens_in`` / ``tokens_out``.
        usage_obj = getattr(result, "usage", None)
        in_tok = int(getattr(usage_obj, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage_obj, "output_tokens", 0) or 0)
        cost = cost_for(model_name, in_tok, out_tok)

        return AgentResult(
            success=True,
            messages=[],
            text_output=getattr(result, "final_output", "") or "",
            session_id="",
            tokens_in=in_tok,
            tokens_out=out_tok,
            cost_usd=cost,
            model=model_name,
        )
