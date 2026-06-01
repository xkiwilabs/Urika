"""Adapter for the ``openai-agents`` SDK (OpenAI Agents framework).

Task 2.1 ships only the skeleton: the class exists, declares the
``AgentRunner`` protocol, and surfaces a clear "extra not installed"
error when the ``agents`` SDK module is absent. The real translation
logic — building an ``Agent`` from an ``AgentConfig``, running it via
``Runner.run``, mapping tool callbacks, and extracting usage/cost —
ships in Task 2.2 inside :meth:`_run_with_sdk`.

This adapter is reached via :func:`urika.agents.runner_registry.runner_for`
when the model name starts with ``gpt-``, ``o3``, ``o4`` or ``o5``.
``runner_registry`` imports this module lazily so callers that never
route to OpenAI don't pay the import cost, and so the registry test
suite stays green on dev boxes that haven't installed the extra.
"""

from __future__ import annotations

from typing import Any, Callable

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner


class OpenAIAgentsRunner(AgentRunner):
    """``AgentRunner`` backed by the ``openai-agents`` SDK.

    See module docstring for scope (skeleton-only in Task 2.1).
    """

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
        """Real SDK call path — filled in by Task 2.2."""
        raise NotImplementedError(
            "OpenAIAgentsRunner._run_with_sdk is implemented in v0.7.0 Task 2.2"
        )
