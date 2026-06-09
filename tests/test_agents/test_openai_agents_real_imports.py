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
* ``agents.RunResult.raw_responses`` — the path the adapter reads for
  per-call usage data (summed across responses).
* ``agents.ModelResponse.usage`` — each raw response carries a
  ``Usage`` object.
* ``agents.Usage`` fields ``input_tokens`` / ``output_tokens`` — the
  names the adapter assumes.

HISTORY (openai-agents 0.17.4, fixed post-v0.7.0): the adapter
originally read ``getattr(result, "usage", None)`` — but ``RunResult``
has NO ``usage`` attribute, so every successful OpenAI run silently
recorded 0 tokens / $0. This module's structural tests caught it. The
adapter now sums ``r.usage.input_tokens`` / ``r.usage.output_tokens``
across ``result.raw_responses``; the tests below pin that read path
against the real SDK.
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


def test_run_result_usage_read_path() -> None:
    """Pins the adapter's usage read path against the real SDK.

    The adapter (``openai_agents.py``, success-path usage extraction)
    sums ``response.usage.input_tokens`` / ``response.usage.output_tokens``
    across ``result.raw_responses``. So:

    * ``RunResult`` must declare ``raw_responses`` as a dataclass field, and
    * ``agents.Usage`` must declare ``input_tokens`` / ``output_tokens``.

    HISTORY: pre-v0.7.1 the adapter read ``getattr(result, "usage", None)``
    — ``RunResult`` has no ``usage`` field, so every successful OpenAI run
    silently recorded 0 tokens / $0. This test originally pinned the bug's
    presence ("RunResult has no usage field"); it now pins the fixed read
    path instead.
    """
    import agents

    rr_fields = set(agents.RunResult.__dataclass_fields__.keys())
    assert "raw_responses" in rr_fields, (
        "agents.RunResult missing 'raw_responses' — the adapter's usage "
        "extraction (summing per-response usage) reads this field"
    )

    usage_fields = set(agents.Usage.__pydantic_fields__.keys())
    assert "input_tokens" in usage_fields and "output_tokens" in usage_fields, (
        "agents.Usage missing input_tokens/output_tokens — the adapter's "
        "usage extraction reads these off each raw_responses[i].usage"
    )


def test_run_result_raw_responses_path() -> None:
    """The usage path the adapter reads: ``result.raw_responses`` is a
    list of ``ModelResponse`` objects, each carrying a ``usage: Usage``
    field.

    Pins both the container field and the per-response usage attribute
    backing the adapter's usage-sum loop.
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
    """The adapter's usage-sum loop reads ``input_tokens`` and
    ``output_tokens`` off each ``raw_responses[i].usage`` object.

    ``agents.Usage`` (a pydantic dataclass) must declare both fields.
    """
    import agents

    usage_fields = set(agents.Usage.__pydantic_fields__.keys())
    assert "input_tokens" in usage_fields, (
        "agents.Usage missing 'input_tokens' field — adapter token-counting will break"
    )
    assert "output_tokens" in usage_fields, (
        "agents.Usage missing 'output_tokens' field — adapter token-counting will break"
    )
