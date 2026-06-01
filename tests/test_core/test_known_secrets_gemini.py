"""Gemini vault wiring (v0.7.0 multi-provider Task 3.3).

The Google ADK adapter ships in v0.7.0 and reads ``GEMINI_API_KEY``
from the environment (see :meth:`GoogleADKRunner.required_env`), so
:data:`LLM_PROVIDERS` must (a) carry an entry under the
``GEMINI_API_KEY`` name and (b) mark it ``available=True`` — the
dashboard's ``POST /api/secrets`` handler refuses to store values for
locked rows, which would otherwise block users from saving their key
via the dashboard or vault.

Mirrors the Task 2.3 OpenAI wiring (commit ba7810af) — flipping the
flag is the small piece that unblocks the rest of the stack.
"""

from __future__ import annotations

from urika.core.known_secrets import KNOWN_SECRETS, LLM_PROVIDERS, ProviderInfo


def test_gemini_api_key_registered() -> None:
    """Gemini is present under the env-var name the adapter reads."""
    names = {prov.name for prov in LLM_PROVIDERS}
    assert "GEMINI_API_KEY" in names, (
        "LLM_PROVIDERS must use GEMINI_API_KEY — that's what the "
        "GoogleADKRunner.required_env() returns, so the vault key has "
        "to match or the adapter won't find the credential."
    )

    gemini_entry = next(p for p in LLM_PROVIDERS if p.name == "GEMINI_API_KEY")
    assert isinstance(gemini_entry, ProviderInfo)
    assert gemini_entry.available is True, (
        "GEMINI_API_KEY must be unlocked once the v0.7.0 Google ADK "
        "adapter ships — otherwise the dashboard refuses to store the key."
    )


def test_gemini_api_key_in_known_secrets_dict() -> None:
    """Autocomplete suggestions surface GEMINI_API_KEY too."""
    assert "GEMINI_API_KEY" in KNOWN_SECRETS
    desc = KNOWN_SECRETS["GEMINI_API_KEY"]
    assert isinstance(desc, str) and desc.strip()
    # The blurb should no longer call the adapter "planned".
    assert "planned" not in desc.lower()
