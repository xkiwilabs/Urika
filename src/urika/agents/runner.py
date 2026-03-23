"""Agent runner interface and result types — runtime-agnostic."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from urika.agents.config import AgentConfig


@dataclass
class AgentResult:
    """What an agent run produced."""

    success: bool
    messages: list[dict[str, Any]]
    text_output: str
    session_id: str
    num_turns: int
    duration_ms: int
    cost_usd: float | None = None
    error: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0


class AgentRunner(ABC):
    """Run an agent and get results — implemented by adapters."""

    @abstractmethod
    async def run(
        self, config: AgentConfig, prompt: str, *, on_message: object = None
    ) -> AgentResult:
        """Execute an agent with the given config and prompt.

        on_message: optional callback called with each SDK message as it arrives.
        """
        ...
