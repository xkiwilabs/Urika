"""OpenAI vault wiring (v0.7.0 multi-provider Task 2.3).

The OpenAI adapter ships in v0.7.0, so ``OPENAI_API_KEY`` must be a
first-class (non-locked) entry in :data:`LLM_PROVIDERS`. The dashboard
auto-load consults this list — flipping ``available`` to ``True`` is
what unblocks users storing the key via the dashboard / vault.
"""

from __future__ import annotations

from urika.core.known_secrets import LLM_PROVIDERS, ProviderInfo


def test_openai_api_key_registered() -> None:
    """OpenAI is present and no longer marked as a locked placeholder."""
    names = {prov.name for prov in LLM_PROVIDERS}
    assert "OPENAI_API_KEY" in names

    openai_entry = next(p for p in LLM_PROVIDERS if p.name == "OPENAI_API_KEY")
    assert isinstance(openai_entry, ProviderInfo)
    # available=True is the real shape's equivalent of "not locked" —
    # the dashboard's ``POST /api/secrets`` handler refuses values for
    # rows whose ``available`` is False (see api.py LLM_PROVIDERS loop).
    assert openai_entry.available is True, (
        "OPENAI_API_KEY must be unlocked once the v0.7.0 OpenAI Agents "
        "adapter ships — otherwise the dashboard refuses to store the key."
    )
