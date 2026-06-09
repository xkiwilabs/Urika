"""Real-SDK structural smoke for :class:`OpenAIAgentsRunner`.

Skipped unless the ``openai-agents`` package (``agents`` import root)
is installed. Install via ``pip install 'urika[openai]'`` or
``pip install 'openai-agents>=0.4'``.

This follows the pattern established by
:file:`test_google_adk_real_imports.py` (the v0.7.0 lesson): ship a
real-imports structural test alongside mock-based unit tests so
signature drift fails CI, not a post-release smoke run.

Specifically pinned here:

* ``agents.Agent(name=, instructions=, model=, tools=)`` ctor params.
* ``agents.Runner.run`` is a coroutine accepting positional ``agent``
  + ``input`` and keyword ``max_turns``.
* ``agents.function_tool`` exists and is callable (used as a decorator
  in the adapter).
* ``agents.RunResult.final_output`` — the field the adapter reads for
  ``text_output``.
* ``agents.RunResult.raw_responses`` — the correct path to per-call
  usage data (see BUG note below).
* ``agents.ModelResponse.usage`` — each raw response carries a
  ``Usage`` object.
* ``agents.Usage`` fields ``input_tokens`` / ``output_tokens`` — the
  names the adapter assumes.

LIVE BUG FOUND (openai-agents 0.17.4, v0.8.0 scope):
  ``openai_agents.py`` line 245:
      ``usage_obj = getattr(result, "usage", None)``
  ``RunResult`` has NO ``usage`` attribute (confirmed via
  ``RunResult.__dataclass_fields__``). The ``getattr`` always returns
  ``None``, so ``in_tok`` and ``out_tok`` are always 0 for every
  OpenAI agent run — usage/cost tracking is silently broken.

  The correct path is to sum usage across the raw model responses:
      ``sum(r.usage.input_tokens for r in result.raw_responses)``
  (``result.raw_responses: list[ModelResponse]``, each with a
  ``usage: Usage`` pydantic dataclass.)

  The field names on ``agents.Usage`` ARE correct — the adapter's
  ``"input_tokens"`` / ``"output_tokens"`` assumptions match the real
  SDK. Only the container attribute (``result.usage`` vs.
  ``result.raw_responses[i].usage``) is wrong.

  The tests below pin the REAL field names and structure so any fix
  to the adapter can be validated here.
"""

from __future__ import annotations

import inspect

import pytest

# Skip the whole module when the ``[openai]`` extra is not installed.
# Install: ``pip install 'openai-agents>=0.4'``
pytest.importorskip("agents")


def test_agent_constructor_params() -> None:
    """Adapter ``_run_with_sdk`` (line 183):
    ``agents.Agent(name=config.name, instructions=config.system_prompt,
                   model=config.model, tools=tools)``.

    All four kwargs must appear in the constructor signature.
    """
    import agents

    sig = inspect.signature(agents.Agent.__init__)
    params = sig.parameters
    for kw in ("name", "instructions", "model", "tools"):
        assert kw in params, (
            f"agents.Agent.__init__ missing kwarg '{kw}' "
            f"(adapter _run_with_sdk passes it)"
        )


def test_runner_run_signature() -> None:
    """Adapter line 198:
    ``agents.Runner.run(agent, prompt, max_turns=max_turns)``.

    The first positional param after ``self`` maps to ``starting_agent``
    in the live SDK (not ``agent``), the second to ``input`` (not
    ``prompt``). Because the adapter passes both positionally this is
    fine — but ``max_turns`` must be an accepted keyword arg.
    """
    import agents

    sig = inspect.signature(agents.Runner.run)
    params = sig.parameters
    param_names = list(params.keys())
    # First two positional params (after implicit self — Runner.run is a
    # classmethod/staticmethod so self is absent in inspect output).
    assert len(param_names) >= 2, "Runner.run has fewer params than expected"
    # max_turns must be an accepted keyword
    assert "max_turns" in params, "Runner.run missing 'max_turns' keyword param"


def test_runner_run_is_coroutine() -> None:
    """Adapter line 197: ``await asyncio.wait_for(Runner.run(...), ...)``.

    ``Runner.run`` must be a coroutine function for ``wait_for`` to work.
    If it is a plain sync function ``wait_for`` raises ``TypeError``
    immediately.
    """
    import agents

    assert inspect.iscoroutinefunction(agents.Runner.run), (
        "agents.Runner.run is not a coroutine — adapter's asyncio.wait_for "
        "call will raise TypeError at runtime"
    )


def test_function_tool_callable() -> None:
    """Adapter lines 141–171: ``@openai_agents_sdk.function_tool``
    decorates six helper functions.

    The symbol must be callable (used as a decorator).
    """
    import agents

    assert callable(agents.function_tool), (
        "agents.function_tool is not callable — adapter's @function_tool "
        "decorator will raise TypeError at runtime"
    )


def test_run_result_final_output() -> None:
    """Adapter line 253: ``getattr(result, 'final_output', '') or ''``.

    ``RunResult.final_output`` must be a declared dataclass field — if
    the SDK renames it (e.g. ``output``) the adapter silently returns
    an empty string for every run.
    """
    import agents

    fields = set(agents.RunResult.__dataclass_fields__.keys())
    assert "final_output" in fields, (
        "agents.RunResult missing 'final_output' field — "
        "adapter will always return empty text_output"
    )


def test_run_result_has_no_usage_field() -> None:
    """Documents the LIVE BUG: adapter line 245 calls
    ``getattr(result, 'usage', None)`` on a ``RunResult``, but
    ``RunResult`` has NO ``usage`` field.

    This test asserts the BUG IS STILL PRESENT so it becomes a
    regression gate: when the adapter is fixed to read
    ``result.raw_responses[i].usage`` this test should be UPDATED to
    reflect the corrected access pattern.

    The correct fix: sum ``r.usage.input_tokens`` and
    ``r.usage.output_tokens`` across ``result.raw_responses``.
    See :file:`src/urika/agents/adapters/openai_agents.py` line 245.
    """
    import agents

    fields = set(agents.RunResult.__dataclass_fields__.keys())
    # BUG: this assertion confirms the adapter's getattr always returns None.
    assert "usage" not in fields, (
        "agents.RunResult now HAS a 'usage' field — the adapter bug may be "
        "fixed upstream. Remove this test and add a test for the real "
        "usage-sum path via result.raw_responses instead."
    )


def test_run_result_raw_responses_path() -> None:
    """The CORRECT usage path: ``result.raw_responses`` is a list of
    ``ModelResponse`` objects, each carrying a ``usage: Usage`` field.

    Pins both the container field and the per-response usage attribute
    so the adapter fix (summing usage across raw_responses) can be
    validated here.
    """
    import agents

    # RunResult must have raw_responses
    rr_fields = set(agents.RunResult.__dataclass_fields__.keys())
    assert "raw_responses" in rr_fields, (
        "agents.RunResult missing 'raw_responses' — correct usage path broken"
    )

    # ModelResponse must have a usage field
    mr_fields = set(agents.ModelResponse.__dataclass_fields__.keys())
    assert "usage" in mr_fields, (
        "agents.ModelResponse missing 'usage' — correct usage path broken"
    )


def test_usage_field_names_on_usage_class() -> None:
    """Adapter lines 246–247: reads ``input_tokens`` and ``output_tokens``
    off the usage object.

    ``agents.Usage`` (a pydantic dataclass) must declare both fields.
    These ARE correct in the installed SDK — the only bug is reaching
    the Usage object via ``result.usage`` (which doesn't exist) instead
    of ``result.raw_responses[i].usage``.
    """
    import agents

    usage_fields = set(agents.Usage.__pydantic_fields__.keys())
    assert "input_tokens" in usage_fields, (
        "agents.Usage missing 'input_tokens' field — "
        "adapter token-counting will break even after the raw_responses fix"
    )
    assert "output_tokens" in usage_fields, (
        "agents.Usage missing 'output_tokens' field — "
        "adapter token-counting will break even after the raw_responses fix"
    )
