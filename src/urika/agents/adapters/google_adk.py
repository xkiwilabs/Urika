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

import asyncio
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable

from urika.agents.config import AgentConfig
from urika.agents.error_classify import classify_error
from urika.agents.runner import AgentResult, AgentRunner

# ── 429 retry tunables ──────────────────────────────────────────────
#
# Free-tier Gemini (5 RPM) hits 429 every ~6th request in a sustained
# run. The server-supplied ``retryDelay`` is usually ~15s but we honor
# whatever it gives us up to a hard cap so a buggy hint can't pin the
# agent loop. _MAX_RETRIES=3 was chosen so a flapping endpoint costs
# at most ~45s before surfacing a structured failure; tune cautiously
# (the unit tests pin on this attribute via ``adapter_mod._MAX_RETRIES``).
_MAX_RETRIES = 3
_MAX_RETRY_WAIT_S = 60.0
_DEFAULT_RETRY_WAIT_S = 15.0
_RETRY_DELAY_RE = re.compile(r"['\"]retryDelay['\"]:\s*['\"](\d+(?:\.\d+)?)s['\"]")


def _is_rate_limit_error(exc: BaseException) -> bool:
    """True if the exception looks like a Gemini 429 / RESOURCE_EXHAUSTED.

    Substring match on ``str(exc)`` rather than an isinstance check —
    the google-genai SDK wraps the underlying HTTP error in a chain of
    exception classes that have shifted across releases, and the
    user-facing message reliably carries both markers.
    """
    s = str(exc)
    return "RESOURCE_EXHAUSTED" in s or "429" in s


def _extract_retry_delay_s(exc: BaseException) -> float:
    """Parse ``retryDelay`` from the 429 message; fall back + cap.

    The 429 body Gemini returns includes a ``retryDelay`` field
    (formatted as e.g. ``'15s'``) inside a JSON-y RetryInfo blob. The
    SDK stringifies that into the exception message — we regex it out
    rather than reaching for typed RetryInfo fields the SDK doesn't
    surface. A missing/malformed value defaults to
    ``_DEFAULT_RETRY_WAIT_S``; an obviously-broken value gets clipped
    to ``_MAX_RETRY_WAIT_S`` so we never hang.
    """
    m = _RETRY_DELAY_RE.search(str(exc))
    if m:
        try:
            return min(float(m.group(1)), _MAX_RETRY_WAIT_S)
        except ValueError:
            pass
    return _DEFAULT_RETRY_WAIT_S


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
            from google.adk.sessions import (  # noqa: F401
                InMemorySessionService,
            )
            from google.genai import types  # noqa: F401
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
        """Real SDK call path — builds an Agent + drives Runner.run_async.

        The ADK's execution model is different from the OpenAI Agents
        SDK: instead of an awaited ``Runner.run`` that returns a
        single ``RunResult``, the ADK exposes an async event stream
        (``Runner.run_async``) that yields ``Event`` objects (which
        subclass ``LlmResponse``). This adapter folds the stream into
        a single :class:`AgentResult` by walking
        ``event.content.parts[].text`` for the textual output and
        pulling token counts off ``event.usage_metadata``
        (``prompt_token_count`` / ``candidates_token_count``).

        ``on_message`` fires per text-bearing part — the stream model
        makes this natural here, unlike the OpenAI adapter's
        synchronous-result API where it had to be a no-op.

        Notable ADK quirks vs. the OpenAI adapter:

        * ``Agent(instruction=...)`` is singular (OpenAI uses
          ``instructions=``). A regression on the keyword would
          surface as a TypeError at agent construction.
        * ``Runner.__init__`` is keyword-only and ``session_service``
          is required — passing the agent positionally raises
          ``TypeError`` immediately. We use
          ``auto_create_session=True`` so the Runner manages the
          session lifecycle from a generated ``session_id`` rather
          than us pre-calling ``SessionService.create_session``;
          fewer moving parts and the resulting ``AgentResult``
          ``session_id`` matches what the Runner actually used.
        * ``Runner.run_async`` is also keyword-only and expects a
          ``types.Content`` for ``new_message`` rather than a plain
          string. We wrap the prompt as ``Content(role="user",
          parts=[Part(text=prompt)])`` — the canonical Gemini shape.
        * Token counts ride on ``event.usage_metadata`` using
          Google's standard naming (``prompt_token_count`` /
          ``candidates_token_count``) — we map those onto
          :class:`AgentResult` 's flat ``tokens_in`` / ``tokens_out``
          fields, same shape as the Claude + OpenAI adapters, so the
          usage tab and advisor cost printout stay provider-agnostic.
        * ADK auto-discovers tool signatures via reflection — plain
          Python functions can be passed in ``tools=[...]`` without
          a decorator. If a future ADK release requires
          ``google.adk.tools.FunctionTool`` wrapping, that's the
          single spot to update.

        **429 / RESOURCE_EXHAUSTED retry handling.** Free-tier Gemini
        accounts hit a 5-RPM cap; rather than fail the experiment
        after the first 429, the loop retries up to ``_MAX_RETRIES``
        times honoring the server-supplied ``retryDelay`` field
        (parsed from the exception message). Retry is *only* safe when
        no events have yielded yet — once we have ``accumulated_text``
        we surface the partial result rather than re-doing work the
        model already did. In practice ADK pauses streaming on error
        so the mid-stream case is rare, but the guard keeps the
        behaviour correct without needing to reason about ADK
        internals. When retries are exhausted, the failure surfaces
        with ``error_category="rate_limit"`` so the orchestrator can
        distinguish "free-tier saturated" from "config / transport"
        problems.
        """
        from google.adk.agents import Agent
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        from urika.agents.pricing import cost_for
        from urika.agents.tools import ToolRegistry
        from urika.agents.tools.bash import bash as bash_tool
        from urika.agents.tools.edit import edit as edit_tool
        from urika.agents.tools.glob import glob as glob_tool
        from urika.agents.tools.grep import grep as grep_tool
        from urika.agents.tools.read import read as read_tool
        from urika.agents.tools.write import write as write_tool
        from urika.core.compliance import scrub_oauth_env_for_subprocess

        security = config.security
        # Tools that need a project root (bash, glob) fall back to
        # ``Path.cwd()`` only when no cwd is configured — should be
        # vanishingly rare in agent runs but keeps the wrapper
        # defensive. Mirrors the OpenAI adapter's convention.
        project_dir: Path = config.cwd or Path.cwd()

        agent_env = scrub_oauth_env_for_subprocess(config.env)
        # Per-Bash-call wall-clock cap — the Claude adapter injects
        # ``max_method_seconds`` via ``can_use_tool``; here we thread
        # it straight into the shared bash tool. 600s mirrors the bash
        # tool's own default, passed explicitly for uniformity.
        bash_timeout = config.max_method_seconds or 600

        def _wrap(tool_result: Any) -> str:
            return (
                tool_result.output if tool_result.ok else f"ERROR: {tool_result.error}"
            )

        # ADK auto-discovers function signatures via reflection, so
        # the six tool wrappers are plain functions. If a future ADK
        # release ships ``google.adk.tools.FunctionTool`` as a
        # required wrapper, decorate these in one swoop.
        def bash(cmd: str) -> str:
            return _wrap(
                bash_tool(
                    cmd,
                    security=security,
                    project_dir=project_dir,
                    env=agent_env,
                    timeout_seconds=bash_timeout,
                )
            )

        def read(path: str) -> str:
            return _wrap(read_tool(path, security=security))

        def write(path: str, content: str) -> str:
            return _wrap(write_tool(path, content, security=security))

        def grep(pattern: str, path: str) -> str:
            return _wrap(grep_tool(pattern, path, security=security))

        def glob(pattern: str) -> str:
            return _wrap(glob_tool(pattern, security=security, project_dir=project_dir))

        def edit(path: str, old_string: str, new_string: str) -> str:
            return _wrap(edit_tool(path, old_string, new_string, security=security))

        tools_by_name = {
            "bash": bash,
            "read": read,
            "write": write,
            "grep": grep,
            "glob": glob,
            "edit": edit,
        }
        tools = [tools_by_name[n] for n in ToolRegistry.for_role(config.name)]

        # ADK's ``instruction`` field runs ``inject_session_state`` over
        # the prompt and treats every literal ``{var}`` as a context
        # variable to look up. Urika prompts routinely embed literal
        # braces (code examples, JSON snippets, ``{method}`` references)
        # which would raise ``KeyError: 'Context variable not found: ...'``.
        # ``static_instruction`` bypasses the template substitution and
        # passes the prompt through verbatim — the right channel for our
        # static system prompts.
        agent = Agent(
            name=config.name,
            static_instruction=config.system_prompt,
            model=config.model,
            tools=tools,
        )

        # Per-run isolated session — ``auto_create_session=True`` lets
        # the Runner materialise it on the first ``run_async`` call so
        # we don't have to dance with an explicit
        # ``session_service.create_session`` (which is async and would
        # require us to plumb through the resulting Session.id). The
        # generated ``session_id`` is what we report back on the
        # ``AgentResult`` so the orchestrator can correlate retries.
        session_service = InMemorySessionService()
        session_id = f"urika-{config.name}-{uuid.uuid4().hex[:8]}"
        runner = Runner(
            app_name="urika",
            agent=agent,
            session_service=session_service,
            auto_create_session=True,
        )

        user_message = types.Content(
            role="user",
            parts=[types.Part(text=prompt)],
        )

        model_name = config.model or ""
        accumulated_text = ""
        in_tok = 0
        out_tok = 0
        attempts = 0
        # Same wall-clock knob as the Claude + OpenAI adapters. Applied
        # per ``__anext__`` call so a stalled HTTP stream raises
        # ``asyncio.TimeoutError`` instead of hanging the orchestrator
        # turn forever — a healthy long run that keeps yielding events
        # never trips it.
        _stream_timeout = float(os.environ.get("URIKA_AGENT_STREAM_TIMEOUT", "600"))

        # The retry loop wraps the event stream so that a 429 fired
        # *before* any events yield can be transparently retried with
        # the server-suggested ``retryDelay``. ``accumulated_text``
        # acts as the safety interlock — once we have partial output,
        # we surface what we got rather than re-doing work.
        while True:
            attempts += 1
            try:
                # Explicit ``__aiter__``/``__anext__`` iteration (rather
                # than ``async for``) so each event fetch can be bounded
                # by ``asyncio.wait_for`` — a stalled stream raises into
                # the outer handler instead of hanging.
                stream = runner.run_async(
                    user_id="urika-user",
                    session_id=session_id,
                    new_message=user_message,
                ).__aiter__()
                while True:
                    try:
                        event = await asyncio.wait_for(
                            stream.__anext__(), timeout=_stream_timeout
                        )
                    except StopAsyncIteration:
                        break
                    # Real ADK events carry text on
                    # ``event.content.parts[].text`` (a ``types.Content``
                    # with a list of ``types.Part``) rather than a flat
                    # ``event.text`` attr. Walk parts defensively —
                    # some events (tool calls, usage-only finals) have
                    # no text.
                    content = getattr(event, "content", None)
                    if content is not None:
                        for part in getattr(content, "parts", None) or []:
                            text = getattr(part, "text", None)
                            if text:
                                accumulated_text += text
                                if on_message is not None:
                                    # Fire per text-bearing part — the
                                    # stream model lets us offer parity
                                    # with the Claude adapter's
                                    # per-message callback that the
                                    # OpenAI adapter can't currently
                                    # provide.
                                    try:
                                        on_message(text)
                                    except Exception:  # noqa: BLE001 — user callback
                                        # A misbehaving callback must
                                        # not break the agent loop.
                                        pass

                    # Usage tokens ride on ``event.usage_metadata``
                    # with Google's standard ``prompt_token_count`` /
                    # ``candidates_token_count`` names. May appear on
                    # the trailing event only, or incrementally — keep
                    # updating so the latest non-zero value wins. The
                    # ``or in_tok`` guard avoids clobbering an earlier
                    # non-zero with a 0 on a tool-call event.
                    usage = getattr(event, "usage_metadata", None)
                    if usage is not None:
                        in_tok = getattr(usage, "prompt_token_count", in_tok) or in_tok
                        out_tok = (
                            getattr(usage, "candidates_token_count", out_tok) or out_tok
                        )
                break  # stream completed cleanly — exit retry loop
            except Exception as exc:  # noqa: BLE001 — SDK boundary
                # Only retry when (a) it's a 429-shaped error,
                # (b) we haven't hit the cap, and (c) no text has
                # yielded yet (mid-stream retry is unsafe).
                if (
                    _is_rate_limit_error(exc)
                    and attempts < _MAX_RETRIES
                    and not accumulated_text
                ):
                    await asyncio.sleep(_extract_retry_delay_s(exc))
                    continue
                if isinstance(exc, asyncio.TimeoutError):
                    error_text = (
                        f"Google agent stream stalled for {_stream_timeout:.0f}s "
                        "(set URIKA_AGENT_STREAM_TIMEOUT to adjust)"
                    )
                    category = "transient"
                else:
                    error_text = str(exc)
                    category = (
                        "rate_limit"
                        if _is_rate_limit_error(exc)
                        else classify_error(error_text)
                    )
                # Preserve any tokens accumulated from events before the
                # failure (and the retries-exhausted branch's run-loop
                # accumulator). Dropping these on the failure path turned
                # real cost into 0 in the session log — v0.7.0 release
                # blocker. ``cost_for`` handles unknown models (returns
                # None) and 0/0 tokens (returns 0.0) cleanly, so the
                # explicit call is safe in both the "fired before any
                # events" and "fired mid-stream" cases.
                return AgentResult(
                    success=False,
                    messages=[],
                    text_output=accumulated_text,
                    session_id=session_id,
                    error=error_text,
                    error_category=category,
                    model=model_name,
                    tokens_in=in_tok,
                    tokens_out=out_tok,
                    cost_usd=cost_for(model_name, in_tok, out_tok),
                )

        cost = cost_for(model_name, in_tok, out_tok)
        return AgentResult(
            success=True,
            messages=[],
            text_output=accumulated_text,
            session_id=session_id,
            tokens_in=in_tok,
            tokens_out=out_tok,
            cost_usd=cost,
            model=model_name,
        )
