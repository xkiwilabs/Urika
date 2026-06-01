"""Per-provider recommended-models split (v0.7.0).

The v0.7.0 multi-provider track introduces three first-class
providers — Anthropic, OpenAI, Google — and the dashboard's Models
tab needs to suggest a reasoning + execution model pair for whichever
provider the user has selected. ``recommended_models_for(provider)``
is the public API both the dashboard and the CLI wizard consume.

These tests pin the per-provider recommendations so a future bump
to one provider's default (e.g. when ``gpt-5.5`` ships) is a
deliberate, test-visible change rather than a silent drift.
"""

from __future__ import annotations

import pytest

from urika.core.recommended_models import recommended_models_for


def test_anthropic_defaults_unchanged() -> None:
    """Anthropic recommendations are the v0.4+ reasoning/execution
    split: Opus 4.7 for the four reasoning agents, Sonnet 4.5 for the
    eight execution agents. Bumping these without bumping the per-
    agent default split would silently desync the Models tab from the
    ``urika config`` wizard's recommended choice.
    """
    rec = recommended_models_for("anthropic")
    assert rec["reasoning"] == "claude-opus-4-7"
    assert rec["execution"] == "claude-sonnet-4-5"


def test_openai_defaults() -> None:
    rec = recommended_models_for("openai")
    assert rec["reasoning"] == "gpt-5.4"
    assert rec["execution"] == "gpt-5.4-mini"


def test_google_defaults() -> None:
    rec = recommended_models_for("google")
    assert rec["reasoning"] == "gemini-3.1-pro-preview"
    assert rec["execution"] == "gemini-3.5-flash"


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        recommended_models_for("nonexistent")
