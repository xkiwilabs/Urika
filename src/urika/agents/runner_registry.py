"""Model-prefix → AgentRunner routing.

The orchestrator (and any other caller that already has a model
string in hand) calls :func:`runner_for` to obtain the adapter that
should handle that particular model. Routing is by name prefix —
there's no per-project provider setting, the model string itself is
the source of truth.

This module is intentionally distinct from :mod:`urika.agents.registry`
(which houses ``AgentRegistry`` for agent ROLES like planning_agent /
task_agent). Mixing role-registration with model-routing in one file
would conflate two unrelated concerns.

Adapter modules are imported lazily inside :func:`runner_for` so a
not-yet-shipped adapter (OpenAI in Phase 2, Google in Phase 3) does
not cause an ImportError at collection time. Calling
``runner_for("gpt-4o")`` before Task 2.1 lands will surface a
``ModuleNotFoundError`` from the lazy import — that's the signal to
ship the adapter, not a bug here.
"""

from __future__ import annotations

from urika.agents.runner import AgentRunner


class UnknownModelError(ValueError):
    """Raised when no adapter is registered for a model prefix."""


def runner_for(model: str) -> AgentRunner:
    """Return the adapter that handles ``model``.

    Prefix-matched against the known provider families:

    * ``claude-*`` → :class:`~urika.agents.adapters.claude_sdk.ClaudeSDKRunner`
    * ``gpt-*`` / ``o3*`` / ``o4*`` / ``o5*`` →
      ``OpenAIAgentsRunner`` (ships in v0.7.0 Task 2.1)
    * ``gemini-*`` → ``GoogleADKRunner`` (ships in v0.7.0 Task 3.1)

    Anything else raises :class:`UnknownModelError`.
    """
    if model.startswith("claude-"):
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner

        return ClaudeSDKRunner()
    if model.startswith(("gpt-", "o3", "o4", "o5")):
        from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

        return OpenAIAgentsRunner()
    if model.startswith("gemini-"):
        from urika.agents.adapters.google_adk import GoogleADKRunner

        return GoogleADKRunner()
    raise UnknownModelError(f"no adapter for model {model!r}")
