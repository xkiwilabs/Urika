"""Orchestrator chat — conversational agent for the TUI.

Maintains conversation state across turns. Uses the Claude Agent SDK
to make LLM calls with the user's subscription. All intelligence runs
through the Python backend — the TUI is purely display and input.

The orchestrator has access to:
- State tools (list_experiments, load_progress, etc.) via function calls
- Agent tools (run any agent via agent.run) via function calls
- run_experiment for full deterministic pipeline
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable

from urika.agents.config import (
    AgentConfig,
    AgentRole,
    SecurityPolicy,
    load_runtime_config,
    get_agent_model,
    build_agent_env_for_endpoint,
)
from urika.agents.prompt import load_prompt
from urika.agents.runner import AgentResult, get_runner

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "agents" / "roles" / "prompts"


class OrchestratorChat:
    """Conversational orchestrator that maintains state across turns.

    Unlike other agents which are stateless (one prompt → one response),
    the orchestrator remembers the conversation. Each call to `chat()`
    appends the user message, gets an LLM response, and updates history.
    """

    def __init__(self, project_dir: Path | None = None) -> None:
        self.project_dir = project_dir
        self.messages: list[dict[str, Any]] = []
        self._runner = None

    def set_project(self, project_dir: Path) -> None:
        """Switch to a new project. Clears conversation history."""
        self.project_dir = project_dir
        self.messages = []

    def get_messages(self) -> list[dict[str, Any]]:
        """Get the current conversation history."""
        return list(self.messages)

    def set_messages(self, messages: list[dict[str, Any]]) -> None:
        """Replace conversation history (for resume)."""
        self.messages = list(messages)

    def clear(self) -> None:
        """Clear conversation history."""
        self.messages = []

    async def chat(
        self,
        user_message: str,
        *,
        notify: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Send a message and get a response.

        Returns a dict with: response (text), success, tokens_in, tokens_out,
        cost_usd, model. The response is also streamed via `notify` callbacks.
        """
        if self._runner is None:
            self._runner = get_runner()

        # Build the orchestrator config
        config = self._build_config()

        # Build the full prompt with conversation history
        prompt = self._build_prompt(user_message)

        # Notify start
        if notify:
            try:
                notify("orchestrator.thinking", {"status": "Processing..."})
            except Exception:
                pass

        def on_message(msg: Any) -> None:
            """Stream orchestrator messages back."""
            if not notify:
                return
            try:
                text = ""
                if hasattr(msg, "content"):
                    content = msg.content
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        for block in content:
                            if hasattr(block, "text"):
                                text += block.text
                if text:
                    notify("orchestrator.delta", {"text": text})
            except Exception:
                pass

        # Run the orchestrator agent
        result = await self._runner.run(config, prompt, on_message=on_message)

        # Update conversation history
        self.messages.append({"role": "user", "content": user_message})
        if result.success:
            self.messages.append({"role": "assistant", "content": result.text_output})
        else:
            self.messages.append({"role": "assistant", "content": f"Error: {result.error}"})

        if notify:
            try:
                notify("orchestrator.done", {
                    "success": result.success,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "cost_usd": result.cost_usd or 0,
                    "model": result.model,
                })
            except Exception:
                pass

        return {
            "response": result.text_output if result.success else (result.error or "Agent failed"),
            "success": result.success,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "cost_usd": result.cost_usd or 0,
            "model": result.model,
        }

    def _build_config(self) -> AgentConfig:
        """Build the orchestrator's AgentConfig."""
        # Load project-specific variables
        variables = {
            "project_name": "",
            "question": "",
            "mode": "exploratory",
            "data_dir": "",
            "experiment_id": "",
            "current_state": "No project loaded.",
        }

        if self.project_dir and self.project_dir.exists():
            try:
                from urika.core.workspace import load_project_config
                config = load_project_config(self.project_dir)
                variables["project_name"] = config.name or ""
                variables["question"] = config.question or ""
                variables["mode"] = config.mode or "exploratory"
                variables["data_dir"] = str(self.project_dir / "data")
                variables["current_state"] = "Project loaded. Awaiting instructions."
            except Exception:
                pass

        # Load the orchestrator prompt
        try:
            system_prompt = load_prompt(
                _PROMPTS_DIR / "orchestrator_system.md",
                variables=variables,
            )
        except Exception:
            system_prompt = f"You are the Urika Orchestrator. Project: {variables['project_name']}."

        # Orchestrator gets Read, Glob, Grep for reading project state
        # (it doesn't write or execute — that's what subagents are for)
        env = None
        model = None
        if self.project_dir:
            runtime_config = load_runtime_config(self.project_dir)
            model = get_agent_model("orchestrator", runtime_config)
            env = build_agent_env_for_endpoint(
                self.project_dir, "orchestrator", runtime_config
            )

        return AgentConfig(
            name="orchestrator",
            system_prompt=system_prompt,
            allowed_tools=["Read", "Glob", "Grep"],
            disallowed_tools=[],
            security=SecurityPolicy(
                writable_dirs=[],
                readable_dirs=[self.project_dir] if self.project_dir else [],
                allowed_bash_prefixes=[],
                blocked_bash_patterns=[],
            ),
            max_turns=10,
            cwd=self.project_dir,
            model=model,
            env=env,
        )

    def _build_prompt(self, user_message: str) -> str:
        """Build the prompt including conversation history."""
        parts = []

        # Include recent conversation history (last 20 turns)
        if self.messages:
            parts.append("## Recent Conversation\n")
            for msg in self.messages[-40:]:  # last 20 turns = 40 messages
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if role == "user":
                    parts.append(f"User: {content}\n")
                elif role == "assistant":
                    # Truncate long assistant responses in history
                    if len(content) > 500:
                        content = content[:500] + "..."
                    parts.append(f"Assistant: {content}\n")
            parts.append("\n---\n\n")

        parts.append(f"User: {user_message}")
        return "\n".join(parts)


# Module-level singleton for the RPC handler
_orchestrator: OrchestratorChat | None = None


def get_orchestrator() -> OrchestratorChat:
    """Get or create the module-level orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OrchestratorChat()
    return _orchestrator
