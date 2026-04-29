"""Tests for the known-secrets registry + the LLM providers list."""

from __future__ import annotations

from urika.core.known_secrets import KNOWN_SECRETS, LLM_PROVIDERS, ProviderInfo


def test_known_secrets_has_expected_entries() -> None:
    # Anchor a handful of names so we notice if the registry is gutted.
    for name in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "HUGGINGFACE_HUB_TOKEN",
        "GITHUB_TOKEN",
    ):
        assert name in KNOWN_SECRETS
        # Descriptions must be non-empty for the dashboard's autocomplete.
        assert isinstance(KNOWN_SECRETS[name], str)
        assert KNOWN_SECRETS[name].strip()


def test_llm_providers_registry_shape() -> None:
    """Every provider entry is a frozen dataclass with the required fields."""
    assert len(LLM_PROVIDERS) >= 3
    for prov in LLM_PROVIDERS:
        assert isinstance(prov, ProviderInfo)
        assert isinstance(prov.name, str) and prov.name
        assert isinstance(prov.display, str) and prov.display
        assert isinstance(prov.description, str) and prov.description
        assert isinstance(prov.available, bool)


def test_anthropic_provider_is_available() -> None:
    """Claude is the only adapter Urika ships in v0.3+."""
    prov = next(p for p in LLM_PROVIDERS if p.name == "ANTHROPIC_API_KEY")
    assert prov.available is True


def test_openai_and_google_providers_are_locked() -> None:
    """Pre-roadmap providers render as locked rows."""
    for env_name in ("OPENAI_API_KEY", "GOOGLE_API_KEY"):
        prov = next(p for p in LLM_PROVIDERS if p.name == env_name)
        assert prov.available is False, f"{env_name} should be locked"


def test_provider_info_is_frozen() -> None:
    """ProviderInfo is immutable so callers can't mutate the registry."""
    import dataclasses
    import pytest

    prov = LLM_PROVIDERS[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        prov.available = not prov.available  # type: ignore[misc]
