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
        """Real SDK call path — built in Task 3.2.

        The ADK's execution model is different from the OpenAI Agents
        SDK: instead of an awaited ``Runner.run`` that returns a
        single ``RunResult``, the ADK exposes an async event stream
        (``Runner.run_async``) that yields ``LlmResponse`` /
        ``ToolCall`` / ``ToolResult`` events the adapter must
        accumulate into a final ``AgentResult``. That stream-folding
        is the substance of Task 3.2.
        """
        raise NotImplementedError(
            "GoogleADKRunner._run_with_sdk is implemented in v0.7.0 Task 3.2"
        )
