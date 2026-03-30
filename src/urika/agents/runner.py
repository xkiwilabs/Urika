"""Agent runner interface and result types — runtime-agnostic."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from urika.agents.config import AgentConfig


@dataclass
class AgentResult:
    """What an agent run produced."""

    success: bool
    messages: list[dict[str, Any]]
    text_output: str
    session_id: str
    num_turns: int = -1
    duration_ms: int = -1
    cost_usd: float | None = None
    error: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


class AgentRunner(ABC):
    """Run an agent and get results — implemented by adapters."""

    @abstractmethod
    async def run(
        self, config: AgentConfig, prompt: str, *, on_message: Callable[..., Any] | None = None
    ) -> AgentResult:
        """Execute an agent with the given config and prompt.

        on_message: optional callback called with each SDK message as it arrives.
        """
        ...


def get_runner(backend: str = "claude", **kwargs: object) -> AgentRunner:
    """Get an AgentRunner for the specified backend.

    Defaults to 'claude'. Other backends raise ValueError with
    install instructions until their adapters are implemented.
    """
    if backend == "claude":
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner

        return ClaudeSDKRunner()
    else:
        raise ValueError(
            f"Backend '{backend}' is not yet supported. "
            f"Available backends: claude"
        )
