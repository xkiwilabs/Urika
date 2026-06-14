"""Real-SDK structural smoke for :class:`ClaudeSDKRunner`.

These tests execute unconditionally on this project because
``claude-agent-sdk`` is a core (non-optional) dependency. They catch
drift between the adapter and the actual SDK API shape *without*
hitting the network — no ``ANTHROPIC_API_KEY`` is required.

This follows the pattern established by
:file:`test_google_adk_real_imports.py` (the v0.7.0 lesson): ship a
real-imports structural test alongside mock-based unit tests so
signature drift fails CI, not a post-release smoke run.

Specifically pinned here:

* ``query`` is importable and accepts ``prompt=`` / ``options=``
  keyword args.
* ``ClaudeAgentOptions.__init__`` accepts every kwarg the adapter
  passes in ``_build_options``:
  ``system_prompt``, ``allowed_tools``, ``disallowed_tools``,
  ``max_turns``, ``model``, ``cwd``, ``permission_mode``,
  ``can_use_tool``, ``env``, ``stderr``, ``cli_path``.
* ``AssistantMessage`` exposes ``content`` and ``model`` (read in the
  stream loop and in ``_message_to_dict``).
* ``TextBlock`` exposes ``text`` (read as ``block.text``).
* ``ResultMessage`` exposes every field the adapter reads:
  ``session_id``, ``num_turns``, ``duration_ms``, ``total_cost_usd``,
  ``is_error``, ``result``, and ``usage`` (dict).
* ``ProcessError`` exposes ``exit_code`` and ``stderr`` (read via
  ``getattr`` but still expected to be live attributes, not sentinel
  ``None`` on a missing field).
"""

from __future__ import annotations

import inspect

import pytest

# claude-agent-sdk is a core dependency — this importorskip acts as a
# canary: if the SDK is somehow missing the whole module is skipped
# rather than failing with an ImportError cascade.
pytest.importorskip("claude_agent_sdk")


def test_query_signature() -> None:
    """Adapter line 247: ``query(prompt=prompt_arg, options=options)``.

    Both ``prompt`` and ``options`` must be keyword params in the live
    ``query`` function signature.
    """
    from claude_agent_sdk import query

    sig = inspect.signature(query)
    params = sig.parameters
    assert "prompt" in params, "claude_agent_sdk.query missing 'prompt' param"
    assert "options" in params, "claude_agent_sdk.query missing 'options' param"


def test_claude_agent_options_kwargs() -> None:
    """Adapter ``_build_options`` (lines 599–614) builds a kwargs dict
    and passes it to ``ClaudeAgentOptions(**kwargs)``.

    Every key in that dict must appear in the constructor signature or
    the adapter will raise ``TypeError`` at runtime.
    """
    from claude_agent_sdk import ClaudeAgentOptions

    sig = inspect.signature(ClaudeAgentOptions.__init__)
    params = sig.parameters

    required_kwargs = [
        "system_prompt",
        "allowed_tools",
        "disallowed_tools",
        "max_turns",
        "model",
        "cwd",
        "permission_mode",
        "can_use_tool",
        "env",
        "stderr",
        # ``cli_path`` is conditional (only when shutil.which("claude")
        # succeeds) but still must be a valid kwarg.
        "cli_path",
    ]
    for kw in required_kwargs:
        assert kw in params, (
            f"ClaudeAgentOptions.__init__ missing kwarg '{kw}' "
            f"(adapter _build_options passes it)"
        )


def test_claude_agent_options_isolation_kwargs() -> None:
    """v0.10.0 Phase 3 (operator-config isolation).

    ``_build_options`` passes ``setting_sources=[]``, ``hooks={}`` and
    ``strict_mcp_config=True`` to isolate the spawned agent worker from
    the operator's ``~/.claude`` config (settings, hooks, CLAUDE.md,
    skills) and operator MCP servers. If a future SDK drops or renames
    any of these, CI must fail loudly here rather than silently losing
    isolation (which would re-open the observed hook-leak: a
    SessionStart hook injecting skill instructions into a task-agent
    transcript and burning turns).
    """
    from claude_agent_sdk import ClaudeAgentOptions

    sig = inspect.signature(ClaudeAgentOptions.__init__)
    params = sig.parameters

    for kw in ("setting_sources", "hooks", "strict_mcp_config"):
        assert kw in params, (
            f"ClaudeAgentOptions.__init__ missing isolation kwarg '{kw}' "
            f"(adapter _build_options relies on it for operator-config "
            f"isolation — v0.10.0 Phase 3)"
        )


def test_assistant_message_content_and_model() -> None:
    """Adapter stream loop (lines 303–309):
    ``for block in msg.content`` and ``msg.model``.

    Both field names must live on ``AssistantMessage`` — they are
    dataclass fields not method results, so ``hasattr`` on the class
    is sufficient.
    """
    from claude_agent_sdk import AssistantMessage

    fields = set(AssistantMessage.__dataclass_fields__.keys())
    assert "content" in fields, "AssistantMessage missing 'content' field"
    assert "model" in fields, "AssistantMessage missing 'model' field"


def test_text_block_text() -> None:
    """Adapter stream loop (line 306): ``block.text``.

    ``TextBlock`` must expose a ``text`` field.
    """
    from claude_agent_sdk import TextBlock

    sig = inspect.signature(TextBlock.__init__)
    assert "text" in sig.parameters, "TextBlock.__init__ missing 'text' param"


def test_result_message_fields() -> None:
    """Adapter stream loop (lines 311–333) reads these fields directly
    off a ``ResultMessage`` instance:
    ``session_id``, ``num_turns``, ``duration_ms``, ``total_cost_usd``,
    ``is_error``, ``result``, and ``usage`` (dict).

    A rename of any of these (e.g. ``total_cost_usd`` → ``cost_usd``)
    would silently produce wrong or zero usage data.
    """
    from claude_agent_sdk import ResultMessage

    fields = set(ResultMessage.__dataclass_fields__.keys())
    for name in (
        "session_id",
        "num_turns",
        "duration_ms",
        "total_cost_usd",
        "is_error",
        "result",
        "usage",
    ):
        assert name in fields, f"ResultMessage missing field '{name}'"


def test_result_message_usage_dict_keys() -> None:
    """Adapter lines 326–333: reads ``usage.get("input_tokens")``,
    ``usage.get("cache_creation_input_tokens")``,
    ``usage.get("cache_read_input_tokens")``,
    ``usage.get("output_tokens")``.

    ``ResultMessage.usage`` is typed ``dict[str, Any] | None`` so there
    is no class-level field to inspect. Instead, confirm the field is
    declared as a dict (not a typed object with different attribute
    names) by checking the type annotation.
    """
    from claude_agent_sdk import ResultMessage

    hint = ResultMessage.__dataclass_fields__["usage"]
    # The annotation string contains "dict" — if the SDK ever changes
    # this to a typed Usage object the adapter's .get() calls will break
    # (AttributeError: 'UsageObject' has no attribute 'get').
    assert hint is not None, "ResultMessage.usage field disappeared"
    # Confirm via repr/str of the field type annotation — dataclass Field
    # objects carry the type as a string for forward-ref resolution.
    hint_str = str(hint.type) if hasattr(hint, "type") else ""
    assert (
        "dict" in hint_str or "Dict" in hint_str or "Any" in hint_str or hint_str == ""
    ), (
        f"ResultMessage.usage type hint changed from dict — adapter's "
        f".get() calls will break. Current hint: {hint_str!r}"
    )


def test_process_error_attributes() -> None:
    """Adapter exception handler (lines 373–402): ``getattr(exc, 'exit_code', None)``
    and ``getattr(exc, 'stderr', '')`` on a ``ProcessError``.

    Both must be real constructor params (not synthesised via
    ``__getattr__``) so the adapter's ``getattr`` calls return the live
    values, not the fallback defaults.
    """
    from claude_agent_sdk import ProcessError

    sig = inspect.signature(ProcessError.__init__)
    params = sig.parameters
    assert "exit_code" in params, "ProcessError.__init__ missing 'exit_code' param"
    assert "stderr" in params, "ProcessError.__init__ missing 'stderr' param"

    # Smoke-construct to confirm the attributes round-trip correctly.
    exc = ProcessError("boom", exit_code=1, stderr="bad output")
    assert exc.exit_code == 1
    assert exc.stderr == "bad output"
