"""Claude Agent SDK adapter -- translates Urika interfaces to SDK types.

This is the only module that imports claude_agent_sdk. Swap this adapter
to change the runtime (e.g. custom runtime, Pi SDK).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
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


def _trace_prompt_event(record: dict[str, Any]) -> None:
    """Append a JSONL prompt-size record when ``URIKA_PROMPT_TRACE_FILE`` is set.

    Diagnostic-only (v0.4.1). Used to collect real prompt-size and
    cache-hit distributions during an experiment so trim decisions
    can be evidence-based instead of guesswork. Off by default —
    zero overhead beyond the env-var lookup. The trace file is
    append-only JSONL (one record per agent call); the run itself
    is unaffected by I/O failures.

    Record shape:
        ts, agent, model, system_bytes, prompt_bytes,
        tokens_in_total, input_tokens, cache_creation_in,
        cache_read_in, tokens_out, duration_ms, success
    """
    path = os.environ.get("URIKA_PROMPT_TRACE_FILE", "").strip()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
    except Exception:
        pass


# Suppress the noisy "Fatal error in message reader" log line emitted
# by ``claude_agent_sdk._internal.query._read_messages`` when the
# system claude CLI v2.1.124+ exits 1 in streaming mode after a
# successful run. The error is benign — our adapter already tolerates
# it via the ``trailing_exit_after_success`` branch — but the SDK's
# unconditional ``logger.error`` call still pollutes our agent output
# and trips automated smoke harnesses that grep for the string.
class _SuppressTrailingCliExit(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if "Fatal error in message reader" in msg and "exit code" in msg:
            return False
        return True


logging.getLogger("claude_agent_sdk._internal.query").addFilter(
    _SuppressTrailingCliExit()
)

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
# Transient network/server errors that should pause-and-resume rather
# than fail the experiment outright. Pre-v0.3.2 a 5xx or a connection
# blip mid-loop killed a multi-hour autonomous run.
_TRANSIENT_PATTERNS = [
    re.compile(r"\b5\d\d\b"),
    re.compile(r"connection.{0,3}reset", re.IGNORECASE),
    re.compile(r"connection.{0,3}refused", re.IGNORECASE),
    re.compile(r"connection.{0,3}aborted", re.IGNORECASE),
    re.compile(r"timeout", re.IGNORECASE),
    re.compile(r"timed.?out", re.IGNORECASE),
    re.compile(r"temporarily.{0,3}unavailable", re.IGNORECASE),
    re.compile(r"service.{0,3}unavailable", re.IGNORECASE),
    re.compile(r"bad.?gateway", re.IGNORECASE),
    re.compile(r"gateway.{0,3}timeout", re.IGNORECASE),
]
# Configuration errors that need user action to fix but shouldn't
# look like generic failures in the dashboard. Treated as a separate
# category so the UI can render an actionable hint.
_CONFIG_PATTERNS = [
    re.compile(r"MissingPrivateEndpointError", re.IGNORECASE),
    re.compile(r"APIKeyRequiredError", re.IGNORECASE),
    re.compile(r"private.{0,3}endpoint.{0,30}configured", re.IGNORECASE),
]


def _classify_error(error_text: str) -> str:
    """Classify an SDK error into a user-friendly category.

    Returns one of: ``"rate_limit"``, ``"auth"``, ``"billing"``,
    ``"transient"``, ``"config"``, ``"unknown"``.

    The ``"transient"`` and ``"config"`` categories were added in
    v0.3.2 — pre-v0.3.2 a 5xx mid-loop or a missing-endpoint config
    error fell into ``"unknown"`` and silently failed the experiment.
    The orchestrator loop's pause path treats both as pausable.
    """
    for pat in _CONFIG_PATTERNS:
        if pat.search(error_text):
            return "config"
    for pat in _RATE_LIMIT_PATTERNS:
        if pat.search(error_text):
            return "rate_limit"
    for pat in _AUTH_PATTERNS:
        if pat.search(error_text):
            return "auth"
    for pat in _BILLING_PATTERNS:
        if pat.search(error_text):
            return "billing"
    for pat in _TRANSIENT_PATTERNS:
        if pat.search(error_text):
            return "transient"
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
    if category == "transient":
        return (
            "Transient network/server error — the API request failed but "
            "is likely to succeed on retry.\n"
            "  The experiment has been paused and can be resumed.\n"
            "  Run: /resume  (or 'urika run --resume' from CLI)\n"
            f"  Detail: {raw}"
        )
    if category == "config":
        return (
            "Configuration error — the agent's runtime config is missing "
            "or invalid.\n"
            "  Check ``urika config`` (CLI) or the dashboard's Privacy / "
            "Models tab.\n"
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
        # Broken-out input-token components for the prompt-size trace.
        # ``tokens_in`` keeps its existing total-input semantic (used by
        # the dashboard usage tab); these are extras for the trace only.
        input_tokens_only = 0
        cache_creation_in = 0
        cache_read_in = 0
        model_name = ""
        is_error = False
        # Wall-clock timing + raw prompt bytes for the trace. Cheap;
        # always computed so the success-path return can emit a record
        # without an extra branch on the trace env var.
        _trace_t0 = time.monotonic()
        _trace_sys_bytes = len(config.system_prompt or "")
        _trace_prompt_bytes = len(prompt) if isinstance(prompt, str) else 0

        def _emit_trace(success: bool) -> None:
            _trace_prompt_event(
                {
                    "ts": time.time(),
                    "agent": config.name,
                    "model": model_name,
                    "system_bytes": _trace_sys_bytes,
                    "prompt_bytes": _trace_prompt_bytes,
                    "tokens_in_total": tokens_in,
                    "input_tokens": input_tokens_only,
                    "cache_creation_in": cache_creation_in,
                    "cache_read_in": cache_read_in,
                    "tokens_out": tokens_out,
                    "duration_ms": int((time.monotonic() - _trace_t0) * 1000),
                    "success": success,
                }
            )

        # v0.4: when ``can_use_tool`` is set (every agent run, post-
        # SecurityPolicy enforcement), the SDK requires the prompt to
        # be an ``AsyncIterable[dict]`` rather than a plain ``str``
        # — otherwise it raises
        # ``ValueError: can_use_tool callback requires streaming mode``.
        # Wrap the str into a one-shot async generator that yields the
        # SDK's user-message envelope.
        prompt_arg: Any
        if options.can_use_tool is not None and isinstance(prompt, str):
            prompt_text = prompt

            async def _one_shot_prompt():
                yield {
                    "type": "user",
                    "session_id": "",
                    "message": {"role": "user", "content": prompt_text},
                    "parent_tool_use_id": None,
                }

            prompt_arg = _one_shot_prompt()
        else:
            prompt_arg = prompt

        try:
          async for msg in query(prompt=prompt_arg, options=options):
            if on_message is not None:
                try:
                    on_message(msg)
                except Exception as cb_exc:
                    # Don't let callback errors break the agent, but
                    # do log them — pre-v0.3.2 a UI-render bug in the
                    # callback would silently kill progress feedback
                    # and the user just saw "agent stalled".
                    logger.warning(
                        "on_message callback raised %s: %s",
                        type(cb_exc).__name__,
                        cb_exc,
                        exc_info=True,
                    )

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
                # Accumulate cost/tokens across multi-ResultMessage
                # streams (subagent + final). Pre-v0.3.2 these were
                # set (not summed), so a subagent's usage was clobbered
                # by the final ResultMessage's usage.
                if msg.total_cost_usd is not None:
                    cost_usd = (cost_usd or 0.0) + msg.total_cost_usd
                is_error = msg.is_error
                # Capture the actual error/result text
                result_text = getattr(msg, "result", "") or ""
                # Populate token counts from usage dict, including the
                # cache fields newer SDKs emit separately.
                usage = getattr(msg, "usage", None) or {}
                _input = usage.get("input_tokens") or 0
                _cache_create = usage.get("cache_creation_input_tokens") or 0
                _cache_read = usage.get("cache_read_input_tokens") or 0
                tokens_in += _input + _cache_create + _cache_read
                input_tokens_only += _input
                cache_creation_in += _cache_create
                cache_read_in += _cache_read
                tokens_out += usage.get("output_tokens") or 0

        except ProcessError as exc:
            # Tolerate the system claude CLI v2.1.124+ streaming-mode
            # trailing exit-1 shutdown regression — see the matching
            # branch in the generic ``Exception`` handler below for
            # rationale. Same triple-trigger logic: any of
            # ResultMessage / streamed content / is_error-from-max-turns
            # counts as "agent did work; trailing exit-1 is benign".
            got_content = bool(text_parts) or bool(messages)
            if num_turns > 0 or got_content:
                logger.debug(
                    "Tolerating trailing CLI ProcessError after successful "
                    "stream (turns=%d, model=%s): %s",
                    num_turns,
                    model_name,
                    exc,
                )
                _emit_trace(True)
                return AgentResult(
                    success=True,
                    messages=messages,
                    text_output="\n".join(text_parts),
                    session_id=session_id,
                    num_turns=num_turns,
                    duration_ms=duration_ms,
                    cost_usd=cost_usd,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    model=model_name,
                )
            # Extract stderr for better diagnostics — the SDK's generic
            # ``str(exc)`` is "Command failed with exit code 1" and
            # the SDK transport hardcodes ``stderr="Check stderr
            # output for details"`` even when no stderr was captured,
            # which used to mask real failures (e.g. the API rejecting
            # ``thinking.type.enabled`` for opus-4-7).
            stderr = getattr(exc, "stderr", "") or ""
            stderr_clean = stderr.strip()
            # The "Check stderr output for details" sentinel from the
            # SDK is not actual diagnostic info — fall back to other
            # exception attributes when we see it.
            if stderr_clean and stderr_clean.startswith("Check stderr"):
                stderr_clean = ""
            exit_code = getattr(exc, "exit_code", None)
            if stderr_clean:
                raw_detail = stderr_clean
            elif exit_code is not None:
                raw_detail = (
                    f"{type(exc).__name__}: exit code {exit_code} "
                    f"(no stderr captured by SDK transport)"
                )
            else:
                raw_detail = f"{type(exc).__name__}: {exc}"
            category = _classify_error(raw_detail)
            error_detail = _friendly_error(category, raw_detail)
            logger.exception("Agent SDK ProcessError [%s]", category)
            _emit_trace(False)
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
            # System claude CLI v2.1.124+ has a streaming-mode shutdown
            # regression: it exits 1 *after* successfully streaming the
            # final ResultMessage. The SDK surfaces this as a generic
            # ``Exception("Command failed with exit code 1")`` via the
            # error-message stream-relay path. Pre-fix, urika treated
            # this as a hard failure even though the agent's actual
            # work completed fine. If we already received a clean
            # ResultMessage (``is_error=False``) before the trailing
            # error, treat the run as successful and log the shutdown
            # artifact at debug level.
            # The system claude CLI v2.1.124+ trailing-exit-1 fires at
            # several points in the message stream:
            #   1. After the final ResultMessage (num_turns > 0,
            #      is_error=False).
            #   2. After the last AssistantMessage but BEFORE the
            #      ResultMessage (text_parts populated, num_turns == 0).
            #   3. After a ResultMessage with ``is_error=True`` from
            #      ``max_turns`` exhaustion — the agent's tool calls
            #      already wrote real files (methods, narratives,
            #      figures) before the limit was hit. The trailing
            #      exit-1 in this case still represents a CLI shutdown
            #      bug, NOT the cause of the run failure.
            # All three share the same signature — the SDK wraps the
            # subprocess's non-zero exit as ``Exception("Command failed
            # with exit code N")`` AFTER content has streamed. Treat
            # all three as success-with-content. Genuine API/config
            # errors raise different exception strings (auth, billing,
            # rate-limit) that don't match this signature, so they
            # still propagate as failures via the path below.
            got_content = bool(text_parts) or bool(messages)
            trailing_exit_after_success = (
                (num_turns > 0 or got_content)
                and "Command failed with exit code" in str(exc)
            )
            if trailing_exit_after_success:
                logger.debug(
                    "Tolerating trailing CLI exit after successful stream "
                    "(turns=%d, model=%s): %s",
                    num_turns,
                    model_name,
                    exc,
                )
                _emit_trace(True)
                return AgentResult(
                    success=True,
                    messages=messages,
                    text_output="\n".join(text_parts),
                    session_id=session_id,
                    num_turns=num_turns,
                    duration_ms=duration_ms,
                    cost_usd=cost_usd,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    model=model_name,
                )

            # Preserve type, traceback, and chained __cause__ — the
            # generic str(exc) drops everything except the message,
            # which is what made the bundled-CLI schema-mismatch bug
            # invisible in v0.3.0/0.3.1.
            raw_detail = f"{type(exc).__name__}: {exc}"
            category = _classify_error(raw_detail)
            error_detail = _friendly_error(category, raw_detail)
            logger.exception("Agent SDK error [%s]", category)
            _emit_trace(False)
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
            # Enrich the error string with what we know about the run
            # so the user has something to act on — pre-v0.3.2 this
            # was just ``result_text or "Agent reported error (no
            # details)"`` and an empty result_text yielded a useless
            # placeholder.
            if result_text:
                error_msg = result_text
            else:
                _last_assistant = (
                    text_parts[-1][:200] if text_parts else ""
                )
                error_msg = (
                    f"Agent reported error after {num_turns} turn(s) "
                    f"in {duration_ms}ms"
                    + (f": {_last_assistant!r}" if _last_assistant else "")
                )

        _emit_trace(not is_error)
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
        # SecurityPolicy enforcement (v0.4): wire the agent's
        # writable_dirs / readable_dirs / allowed_bash_prefixes /
        # blocked_bash_patterns into a real ``can_use_tool``
        # callback that the SDK invokes before each tool dispatch.
        # Pre-v0.4 these fields were advisory only; ``permission_mode``
        # was ``"bypassPermissions"`` so the SDK never asked us. The
        # mode change is required — ``can_use_tool`` does NOT fire
        # under bypass.
        from urika.agents.permission import make_can_use_tool

        # Capture stderr from the `claude` CLI so its diagnostic output
        # lands in our logs when the SDK raises the generic "Command
        # failed with exit code 1" — the SDK transport hardcodes
        # ``stderr="Check stderr output for details"`` which used to
        # mask the real cause.
        def _stderr_cb(line: str) -> None:
            try:
                logger.warning("claude-cli stderr: %s", line.rstrip())
            except Exception:
                pass

        kwargs: dict[str, object] = {
            "system_prompt": config.system_prompt,
            "allowed_tools": config.allowed_tools,
            "disallowed_tools": config.disallowed_tools,
            "max_turns": config.max_turns,
            "model": config.model,
            "cwd": str(config.cwd) if config.cwd else None,
            "permission_mode": "default",
            "can_use_tool": make_can_use_tool(
                config.security, config.cwd
            ),
            "env": agent_env,
            "stderr": _stderr_cb,
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

        # CLI selection: the system-installed `claude` CLI on PATH
        # has a newer request schema (e.g. opus-4-7 needs
        # ``thinking.type.adaptive`` + ``output_config.effort`` which
        # bundled v2.1.63 doesn't send). BUT the system CLI v2.1.124+
        # has a streaming-mode regression where it exits 1 after a
        # successful run, which we tolerate via the
        # ``trailing_exit_after_success`` branch in ``run`` below.
        # Prefer the system CLI unconditionally — its newer schema is
        # required for newer models, and the trailing-exit-1 is now
        # treated as a benign shutdown artifact.
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
