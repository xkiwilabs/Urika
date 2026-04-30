"""Claude Agent SDK adapter -- translates Urika interfaces to SDK types.

This is the only module that imports claude_agent_sdk. Swap this adapter
to change the runtime (e.g. custom runtime, Pi SDK).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ProcessError,
    ResultMessage,
    TextBlock,
    query,
)

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.core.compliance import require_api_key, scrub_oauth_env

logger = logging.getLogger(__name__)

# Patterns to detect actionable API errors from stderr / error messages.
_RATE_LIMIT_PATTERNS = [
    re.compile(r"rate.?limit", re.IGNORECASE),
    re.compile(r"429", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"overloaded", re.IGNORECASE),
    re.compile(r"capacity", re.IGNORECASE),
]
_AUTH_PATTERNS = [
    re.compile(r"auth", re.IGNORECASE),
    re.compile(r"401", re.IGNORECASE),
    re.compile(r"api.?key", re.IGNORECASE),
    re.compile(r"not.?logged.?in", re.IGNORECASE),
    re.compile(r"login", re.IGNORECASE),
    re.compile(r"unauthorized", re.IGNORECASE),
    re.compile(r"invalid.*key", re.IGNORECASE),
]
_BILLING_PATTERNS = [
    re.compile(r"billing", re.IGNORECASE),
    re.compile(r"credit", re.IGNORECASE),
    re.compile(r"payment", re.IGNORECASE),
    re.compile(r"subscription", re.IGNORECASE),
    re.compile(r"quota", re.IGNORECASE),
]


def _classify_error(error_text: str) -> str:
    """Classify an SDK error into a user-friendly category.

    Returns one of: "rate_limit", "auth", "billing", "unknown".
    """
    for pat in _RATE_LIMIT_PATTERNS:
        if pat.search(error_text):
            return "rate_limit"
    for pat in _AUTH_PATTERNS:
        if pat.search(error_text):
            return "auth"
    for pat in _BILLING_PATTERNS:
        if pat.search(error_text):
            return "billing"
    return "unknown"


def _friendly_error(category: str, raw: str) -> str:
    """Build a user-friendly error message based on category."""
    if category == "rate_limit":
        return (
            "Rate limit reached — your plan's usage cap has been hit.\n"
            "  The experiment has been paused and can be resumed later.\n"
            "  Run: /resume  (or 'urika run --resume' from CLI)\n"
            f"  Detail: {raw}"
        )
    if category == "auth":
        return (
            "Authentication error — Claude CLI session may have expired.\n"
            "  Run 'claude login' in your terminal to re-authenticate,\n"
            "  then /resume to continue.\n"
            f"  Detail: {raw}"
        )
    if category == "billing":
        return (
            "Billing/quota error — check your Anthropic plan status.\n"
            "  Visit console.anthropic.com to review your account.\n"
            f"  Detail: {raw}"
        )
    return raw


class ClaudeSDKRunner(AgentRunner):
    """Runs agents via Claude Agent SDK."""

    async def run(
        self, config: AgentConfig, prompt: str, *, on_message: Callable[..., Any] | None = None
    ) -> AgentResult:
        """Execute an agent and return structured results."""
        # Layer 2 of the API-key safety net: refuse to spawn a Claude
        # Code subprocess for a cloud-bound agent when no API key is
        # set. This prevents the SDK from silently falling back to the
        # user's Pro/Max subscription OAuth — which violates Anthropic's
        # Consumer Terms §3.7 and the April 2026 Agent SDK clarification.
        # See ``urika.core.compliance`` for the full rationale.
        require_api_key(config.model, config.env)
        options = self._build_options(config)
        messages: list[dict[str, Any]] = []
        text_parts: list[str] = []
        session_id = ""
        num_turns = 0
        duration_ms = 0
        cost_usd: float | None = None
        tokens_in = 0
        tokens_out = 0
        model_name = ""
        is_error = False

        try:
          async for msg in query(prompt=prompt, options=options):
            if on_message is not None:
                try:
                    on_message(msg)
                except Exception:
                    pass  # Don't let callback errors break the agent

            messages.append(_message_to_dict(msg))
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
                # Capture the model name from the latest assistant message
                if getattr(msg, "model", None):
                    model_name = msg.model
            elif isinstance(msg, ResultMessage):
                session_id = msg.session_id
                num_turns = msg.num_turns
                duration_ms = msg.duration_ms
                cost_usd = msg.total_cost_usd
                is_error = msg.is_error
                # Capture the actual error/result text
                result_text = getattr(msg, "result", "") or ""
                # Populate token counts from usage dict
                usage = getattr(msg, "usage", None) or {}
                tokens_in = usage.get("input_tokens", 0) or 0
                tokens_out = usage.get("output_tokens", 0) or 0

        except ProcessError as exc:
            # Extract stderr for better diagnostics — the generic str(exc)
            # just says "Command failed with exit code 1".
            stderr = getattr(exc, "stderr", "") or ""
            raw_detail = stderr.strip() if stderr.strip() else str(exc)
            category = _classify_error(raw_detail)
            error_detail = _friendly_error(category, raw_detail)
            logger.warning("Agent SDK error [%s]: %s", category, raw_detail)
            return AgentResult(
                success=False,
                messages=messages,
                text_output="\n".join(text_parts),
                session_id=session_id,
                error=error_detail,
                error_category=category,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model_name,
            )

        except Exception as exc:
            raw_detail = str(exc)
            category = _classify_error(raw_detail)
            error_detail = _friendly_error(category, raw_detail)
            return AgentResult(
                success=False,
                messages=messages,
                text_output="\n".join(text_parts),
                session_id=session_id,
                error=error_detail,
                error_category=category,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model_name,
            )

        # Build error message with actual details
        error_msg = None
        if is_error:
            error_msg = result_text or "Agent reported error (no details)"

        return AgentResult(
            success=not is_error,
            messages=messages,
            text_output="\n".join(text_parts),
            session_id=session_id,
            num_turns=num_turns,
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            error=error_msg,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model_name,
        )

    def _build_options(self, config: AgentConfig) -> ClaudeAgentOptions:
        """Translate AgentConfig to ClaudeAgentOptions."""
        # Layer 3 of the API-key safety net: scrub OAuth-related env
        # vars from what we pass to the subprocess. Even if the user
        # has CLAUDE_CODE_OAUTH_TOKEN in their shell, Urika must not
        # authenticate via OAuth — only via ANTHROPIC_API_KEY (or a
        # custom endpoint). We pass empty string values (not absence)
        # so the subprocess overrides any parent-inherited values.
        agent_env = scrub_oauth_env(config.env)
        kwargs: dict[str, object] = {
            "system_prompt": config.system_prompt,
            "allowed_tools": config.allowed_tools,
            "disallowed_tools": config.disallowed_tools,
            "max_turns": config.max_turns,
            "model": config.model,
            "cwd": str(config.cwd) if config.cwd else None,
            "permission_mode": "bypassPermissions",
            "env": agent_env,
        }
        # Prefer the system-installed `claude` CLI over the SDK's
        # bundled one whenever it exists. The bundled CLI lags the
        # public release (claude-agent-sdk 0.1.45 ships v2.1.63 while
        # the public CLI is v2.1.123+). The Anthropic API has since
        # tightened the request schema for newer models — e.g.,
        # `claude-opus-4-7` rejects the old ``thinking.type.enabled``
        # shape that v2.1.63 sends and returns 400, surfacing as a
        # cryptic "Fatal error in message reader: Command failed with
        # exit code 1". A newer system CLI knows the current schema
        # (``thinking.type.adaptive`` + ``output_config.effort``).
        # Falling back to the bundled CLI when none is on PATH still
        # works for older models.
        # Also covers claude-agent-sdk-python issue #677 (bundled CLI
        # ignores ``ANTHROPIC_BASE_URL``) — that's now a side-benefit.
        import shutil

        system_cli = shutil.which("claude")
        if system_cli:
            kwargs["cli_path"] = system_cli
        return ClaudeAgentOptions(**kwargs)  # type: ignore[arg-type]


def _message_to_dict(msg: Any) -> dict[str, Any]:
    """Convert an SDK message to a plain dict for storage."""
    if isinstance(msg, ResultMessage):
        return {
            "type": "result",
            "session_id": msg.session_id,
            "num_turns": msg.num_turns,
            "duration_ms": msg.duration_ms,
            "is_error": msg.is_error,
            "cost_usd": msg.total_cost_usd,
        }
    if isinstance(msg, AssistantMessage):
        content = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                content.append({"type": "text", "text": block.text})
            else:
                content.append({"type": "unknown"})
        return {"type": "assistant", "content": content, "model": msg.model}
    return {"type": "other", "raw": str(msg)}
