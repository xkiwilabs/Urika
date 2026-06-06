"""Real-SDK structural smoke for :class:`GoogleADKRunner`.

Skipped unless ``google-adk`` is installed. Catches drift between
the adapter and the actual ADK API shape *without* hitting the
network — no ``GEMINI_API_KEY`` is required for these assertions
to pass.

This is the canonical "did our adapter assumptions match the
installed ADK version?" check. If any assertion here fails, the
adapter must be updated **before** the release ships — the mock-SDK
tests in :file:`test_google_adk.py` and :file:`test_google_e2e_mock.py`
are derived from the same API contract and will silently lie if the
real SDK has drifted (which is the v0.7.0 release-blocker class that
prompted this test).

Specifically pinned here:

* ``Runner.__init__`` accepts the keyword args our adapter passes
  (``app_name``, ``agent``, ``session_service``, ``auto_create_session``).
* ``Runner.run_async`` accepts ``user_id`` / ``session_id`` /
  ``new_message`` — the three keyword-only params our adapter uses.
* The ``Event`` payload exposes ``content`` and ``usage_metadata``,
  the two attributes our adapter reads off each event.
"""

from __future__ import annotations

import inspect

import pytest

# Skip the whole module on dev boxes / CI rows that haven't installed
# the ``[google]`` extra. The module-level skip keeps the import-time
# cost (loading google-genai et al.) off the unit-suite hot path.
pytest.importorskip("google.adk.runners")


def test_runner_constructor_accepts_our_args() -> None:
    """``Runner(app_name=, agent=, session_service=, auto_create_session=)``
    must construct without TypeError.

    Mirrors the call our adapter makes in ``_run_with_sdk``. If a
    future ADK release renames any of these kwargs (or makes one
    positional), this test fails before the smoke run does.
    """
    from google.adk.agents import Agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    agent = Agent(
        name="t",
        instruction="hi",
        model="gemini-3.5-flash",
        tools=[],
    )
    session_service = InMemorySessionService()
    runner = Runner(
        app_name="urika",
        agent=agent,
        session_service=session_service,
        auto_create_session=True,
    )
    assert runner is not None


def test_run_async_signature() -> None:
    """Our adapter calls ``run_async(user_id=, session_id=, new_message=)``.

    Each of those keyword names must appear in the live signature.
    If ADK ever renames them, this test fails before the smoke run.
    """
    from google.adk.runners import Runner

    sig = inspect.signature(Runner.run_async)
    params = sig.parameters
    for required in ("user_id", "session_id", "new_message"):
        assert required in params, f"ADK Runner.run_async missing {required}"


def test_event_content_shape() -> None:
    """Our adapter reads ``event.content`` and ``event.usage_metadata``.

    Confirm both names live on the ``Event`` pydantic model — the
    adapter uses ``getattr`` so it's resilient to ``None`` values,
    but a missing field name (e.g. a rename to ``content_parts``)
    would silently produce empty output.
    """
    from google.adk.events import Event

    fields = set(Event.model_fields.keys())
    assert "content" in fields, "ADK Event missing 'content' field"
    assert "usage_metadata" in fields, "ADK Event missing 'usage_metadata' field"


def test_usage_metadata_token_field_names() -> None:
    """Token counts ride on ``usage_metadata.prompt_token_count`` /
    ``candidates_token_count`` — Google's standard naming.

    Our adapter falls back gracefully via ``getattr`` defaults, but
    if either rename happens we want to know at test time, not when
    the usage tab reports zeros for every Gemini call.
    """
    from google.genai.types import GenerateContentResponseUsageMetadata

    fields = set(GenerateContentResponseUsageMetadata.model_fields.keys())
    assert "prompt_token_count" in fields
    assert "candidates_token_count" in fields


def test_content_part_shape() -> None:
    """``types.Content(role=, parts=[types.Part(text=...)])`` is the
    shape our adapter passes as ``new_message``, and the shape it
    expects to see on response events. Pin both fields here.
    """
    from google.genai import types

    content_fields = set(types.Content.model_fields.keys())
    assert "role" in content_fields
    assert "parts" in content_fields
    part_fields = set(types.Part.model_fields.keys())
    assert "text" in part_fields


def test_session_id_attribute() -> None:
    """``Session.id`` is what our adapter reads for the result's
    ``session_id`` field — pin it so a rename to ``.session_id``
    or ``._id`` would be loud at test time, not at runtime.
    """
    from google.adk.sessions import Session

    fields = set(Session.model_fields.keys())
    assert "id" in fields, "ADK Session missing 'id' field"
