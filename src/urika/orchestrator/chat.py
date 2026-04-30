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

import logging
from pathlib import Path
from typing import Any, Callable

from urika.agents.config import (
    AgentConfig,
    SecurityPolicy,
    load_runtime_config,
    get_agent_model,
    build_agent_env_for_endpoint,
)
from urika.agents.prompt import load_prompt
from urika.agents.runner import get_runner

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
        on_output: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Send a message and get a response.

        Returns a dict with: response (text), success, tokens_in, tokens_out,
        cost_usd, model.

        on_output: optional callback for streaming verbose output to the terminal.
        notify: optional callback for RPC notifications (TUI path).
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
            """Stream orchestrator messages in real-time — tool use + text."""
            try:
                if not hasattr(msg, "content"):
                    return

                content = msg.content
                if isinstance(content, str):
                    if notify:
                        notify("orchestrator.delta", {"text": content})
                    if on_output:
                        on_output("text", content)
                    return

                if not isinstance(content, list):
                    return

                for block in content:
                    # Tool use — show what the agent is doing
                    tool_name = getattr(block, "name", None)
                    if tool_name:
                        inp = getattr(block, "input", {}) or {}
                        detail = ""
                        if isinstance(inp, dict):
                            detail = (
                                inp.get("command", "")
                                or inp.get("file_path", "")
                                or inp.get("pattern", "")
                                or inp.get("content", "")[:80]
                            )
                        if on_output:
                            on_output("tool", f"{tool_name}: {detail}")
                        if notify:
                            notify("orchestrator.tool", {"tool": tool_name, "detail": detail})

                    # Text content
                    text = getattr(block, "text", None)
                    if text:
                        if on_output:
                            on_output("text", text)
                        if notify:
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

        # When the agent failed, surface the most specific message we
        # have rather than the bare "Agent failed" placeholder. The
        # SDK adapter populates ``error`` and ``error_category``;
        # include the category in the response so the dashboard can
        # render auth/rate-limit/billing errors with their own UI
        # rather than dropping back to a generic exception toast.
        if result.success:
            response = result.text_output
        else:
            response = result.error or "Agent failed"
            if result.error_category:
                response = f"[{result.error_category}] {response}"
            # If the agent produced any partial assistant text before
            # failing, show that too — gives the user a window into
            # what the agent was trying to do.
            if result.text_output:
                response = (
                    f"{response}\n\n--- partial output ---\n"
                    f"{result.text_output}"
                )

        return {
            "response": response,
            "success": result.success,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "cost_usd": result.cost_usd or 0,
            "model": result.model,
            "error_category": result.error_category,
        }

    def _build_config(self) -> AgentConfig:
        """Build the orchestrator's AgentConfig.

        The orchestrator has:
        - Read/Glob/Grep — for reading project state files (progress,
          methods, criteria, labbook). NOT raw data files.
        - Bash — restricted to ``urika`` CLI commands for quick
          subagent queries (advisor, evaluate, plan, inspect).
        """
        variables = {
            "project_name": "",
            "question": "",
            "mode": "exploratory",
            "data_dir": "",
            "experiment_id": "",
            "current_state": (
                "No project loaded. The user can:\n"
                "- `/project <name>` — load an existing project\n"
                "- `/list` — see all available projects\n"
                "- `/new` — create a new project (interactive setup)\n"
                "- `/config` — view or change settings "
                "(privacy mode, model, endpoints)\n"
                "- `/notifications` — set up email, Slack, or "
                "Telegram notifications\n"
                "- `/help` — see all available commands\n"
                "\n"
                "Tell the user about these options. Also mention "
                "they can describe their research question and you "
                "can help set things up.\n"
                "\n"
                "You do NOT have any Bash or agent tools at the "
                "global level. Once a project is loaded, you gain "
                "the ability to call subagents and read project state."
            ),
        }

        if self.project_dir and self.project_dir.exists():
            try:
                from urika.core.workspace import load_project_config

                config = load_project_config(self.project_dir)
                variables["project_name"] = config.name or ""
                variables["question"] = config.question or ""
                variables["mode"] = config.mode or "exploratory"
                variables["data_dir"] = str(self.project_dir / "data")
                variables["current_state"] = (
                    "Project loaded. You can read project state files "
                    "and call subagents for quick queries. For "
                    "long-running or interactive operations, recommend "
                    "the specific slash command to the user."
                )
            except Exception:
                pass

        # Load the orchestrator prompt template
        try:
            system_prompt = load_prompt(
                _PROMPTS_DIR / "orchestrator_system.md",
                variables=variables,
            )
        except Exception:
            system_prompt = (
                "You are the Urika Orchestrator. "
                f"Project: {variables['project_name']}."
            )

        env = None
        model = None
        readable_dirs = []
        allowed_bash = []

        if self.project_dir:
            runtime_config = load_runtime_config(self.project_dir)
            model = get_agent_model("orchestrator", runtime_config)
            env = build_agent_env_for_endpoint(
                self.project_dir, "orchestrator", runtime_config
            )
            # Strip Claude Code session markers AND OAuth tokens via
            # the single source of truth in ``compliance.scrub_oauth_env``.
            # Pre-v0.3.2 this site reimplemented the scrub inline and
            # missed ``CLAUDE_CODE_EXECPATH`` (the fourth nested-session
            # marker) plus ``CLAUDE_CODE_OAUTH_TOKEN`` /
            # ``ANTHROPIC_AUTH_TOKEN`` — drift between two
            # implementations of the same scrub.
            from urika.core.compliance import scrub_oauth_env

            env = scrub_oauth_env(env)

            readable_dirs = [self.project_dir]
            # Allow only ``urika`` CLI commands via Bash — for quick
            # subagent queries (advisor, evaluate, plan, inspect).
            # v0.4: SecurityPolicy enforcement now shlex-parses the
            # command and matches against tokenised prefixes. The
            # pre-v0.4 ``"CLAUDECODE= urika "`` form was a string
            # prefix that matched ``urika ; rm -rf /``; the new
            # check rejects shell metacharacters outright AND
            # requires the head token to be exactly ``urika``.
            allowed_bash = ["urika"]

        return AgentConfig(
            name="orchestrator",
            system_prompt=system_prompt,
            # Bash is only included when a project is loaded —
            # at the global level the orchestrator just chats and
            # recommends slash commands.
            allowed_tools=(
                ["Read", "Glob", "Grep", "Bash"]
                if self.project_dir
                else ["Read", "Glob", "Grep"]
            ),
            disallowed_tools=[],
            security=SecurityPolicy(
                writable_dirs=[],
                readable_dirs=readable_dirs,
                allowed_bash_prefixes=allowed_bash,
                blocked_bash_patterns=[
                    # Block raw data reads via Bash (cat, head, etc.)
                    "cat */data/",
                    "head */data/",
                    "tail */data/",
                    "less */data/",
                ],
            ),
            max_turns=25,
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
