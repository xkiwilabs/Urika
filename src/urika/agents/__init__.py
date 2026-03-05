"""Agent infrastructure for Urika.

Core interfaces (runtime-agnostic):
    AgentConfig, SecurityPolicy, AgentRole — agent configuration
    AgentRunner, AgentResult — agent execution

Adapters (swappable runtimes):
    ClaudeSDKRunner — Claude Agent SDK adapter (import from agents.adapters.claude_sdk)

Registry:
    AgentRegistry — discover and retrieve agent roles
"""

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.prompt import load_prompt
from urika.agents.registry import AgentRegistry
from urika.agents.runner import AgentResult, AgentRunner

__all__ = [
    "AgentConfig",
    "AgentResult",
    "AgentRole",
    "AgentRegistry",
    "AgentRunner",
    "SecurityPolicy",
    "load_prompt",
]
