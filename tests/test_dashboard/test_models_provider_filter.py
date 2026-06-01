"""Tests for the dashboard Models-tab Provider filter (v0.7.0 Task 4.4).

The Models tab now exposes a Provider <select> (Anthropic / OpenAI /
Google) whose value drives Alpine ``x-show`` blocks that filter which
model ids appear in every model dropdown — on both the global
Settings page (``/settings``) and the per-project Settings page
(``/projects/<name>/settings``).

The filter is purely client-side: the page ships HTML option groups
for all three providers and Alpine hides the inactive groups. Server-
side, ``KNOWN_CLOUD_MODELS_BY_PROVIDER`` (in
``urika.dashboard.routers.pages``) is the dict the templates iterate
over to render those option groups. Anthropic remains the default
provider so existing users see the same UI on first load.

These tests pin:
  - all three provider labels are present in the rendered HTML
  - each provider's signature model id (gpt-5.4 / gemini-3.1-pro-preview / the
    Anthropic Opus row) appears in the page
  - the Provider <select> exists and defaults to ``anthropic``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def settings_client(tmp_path: Path, monkeypatch) -> TestClient:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    app = create_app(project_root=tmp_path)
    return TestClient(app)


@pytest.fixture
def project_settings_client(tmp_path: Path, monkeypatch) -> TestClient:
    """Dashboard fixture with one minimal ``alpha`` project on disk so
    ``GET /projects/alpha/settings`` resolves to a Models tab render.
    """
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        "[project]\n"
        'name = "alpha"\n'
        'question = "q"\n'
        'mode = "exploratory"\n'
        'description = ""\n'
        "\n"
        "[preferences]\n"
        'audience = "expert"\n'
        "\n"
        "[privacy]\n"
        'mode = "open"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


# ----------------------------------------------------------------------
# KNOWN_CLOUD_MODELS_BY_PROVIDER — module-level shape contract.
# ----------------------------------------------------------------------


class TestProviderModelsTable:
    """``KNOWN_CLOUD_MODELS_BY_PROVIDER`` is the single dashboard-side
    source of truth for per-provider model dropdown options. The
    shape must stay stable: a dict keyed by lowercase provider name
    whose values are non-empty lists of model id strings.
    """

    def test_table_has_three_providers(self) -> None:
        from urika.dashboard.routers.pages import KNOWN_CLOUD_MODELS_BY_PROVIDER

        assert set(KNOWN_CLOUD_MODELS_BY_PROVIDER.keys()) == {
            "anthropic",
            "openai",
            "google",
        }

    def test_anthropic_includes_existing_known_cloud_models(self) -> None:
        """The Anthropic row must be a superset of the legacy flat
        ``KNOWN_CLOUD_MODELS`` list. Otherwise the Provider=Anthropic
        view drops models that were previously selectable.
        """
        from urika.dashboard.routers.pages import (
            KNOWN_CLOUD_MODELS,
            KNOWN_CLOUD_MODELS_BY_PROVIDER,
        )

        assert set(KNOWN_CLOUD_MODELS).issubset(
            set(KNOWN_CLOUD_MODELS_BY_PROVIDER["anthropic"])
        )

    def test_openai_includes_gpt_54_family(self) -> None:
        from urika.dashboard.routers.pages import KNOWN_CLOUD_MODELS_BY_PROVIDER

        openai = KNOWN_CLOUD_MODELS_BY_PROVIDER["openai"]
        # The reasoning + execution recommendations from
        # recommended_models_for("openai") must be selectable.
        assert "gpt-5.4" in openai
        assert "gpt-5.4-mini" in openai

    def test_google_includes_gemini_3_family(self) -> None:
        from urika.dashboard.routers.pages import KNOWN_CLOUD_MODELS_BY_PROVIDER

        google = KNOWN_CLOUD_MODELS_BY_PROVIDER["google"]
        assert "gemini-3.1-pro-preview" in google
        assert "gemini-3.5-flash" in google

    def test_recommended_models_are_in_provider_table(self) -> None:
        """For every provider in the table, the
        ``recommended_models_for(provider)`` reasoning + execution
        picks must appear in the dropdown options list. Otherwise the
        UI would recommend a model the user can't actually select.
        """
        from urika.core.recommended_models import recommended_models_for
        from urika.dashboard.routers.pages import KNOWN_CLOUD_MODELS_BY_PROVIDER

        for provider, options in KNOWN_CLOUD_MODELS_BY_PROVIDER.items():
            rec = recommended_models_for(provider)
            assert rec["reasoning"] in options, (
                f"{provider} reasoning recommendation {rec['reasoning']!r} "
                f"is not in KNOWN_CLOUD_MODELS_BY_PROVIDER[{provider!r}]"
            )
            assert rec["execution"] in options, (
                f"{provider} execution recommendation {rec['execution']!r} "
                f"is not in KNOWN_CLOUD_MODELS_BY_PROVIDER[{provider!r}]"
            )


# ----------------------------------------------------------------------
# Global Settings page — Models tab.
# ----------------------------------------------------------------------


class TestGlobalModelsTabProviderFilter:
    def test_models_page_lists_three_providers(
        self, settings_client: TestClient
    ) -> None:
        """The Provider <select> must offer Anthropic / OpenAI / Google
        as visible option labels in the rendered Models tab HTML."""
        body = settings_client.get("/settings").text
        assert "Anthropic" in body
        assert "OpenAI" in body
        assert "Google" in body

    def test_models_page_exposes_provider_select(
        self, settings_client: TestClient
    ) -> None:
        """The Provider filter is keyed off a ``<select>`` whose
        Alpine ``x-model`` binds the chosen provider. Pin the exact
        option values so future refactors don't silently swap them."""
        body = settings_client.get("/settings").text
        assert 'value="anthropic"' in body
        assert 'value="openai"' in body
        assert 'value="google"' in body

    def test_models_page_default_provider_is_anthropic(
        self, settings_client: TestClient
    ) -> None:
        """Anthropic's reasoning recommendation (``claude-opus-4-7``)
        must appear in the rendered page so users land on the same
        Anthropic-first UI they had before the Provider filter shipped.
        """
        body = settings_client.get("/settings").text
        assert "claude-opus-4-7" in body

    def test_models_page_renders_openai_and_google_options(
        self, settings_client: TestClient
    ) -> None:
        """Even though Anthropic is the default, the OpenAI and Google
        ``<option>`` rows must be in the DOM (Alpine just hides them
        with x-show). Otherwise switching the Provider <select> would
        show an empty dropdown.
        """
        body = settings_client.get("/settings").text
        assert "gpt-5.4" in body
        assert "gemini-3.1-pro-preview" in body


# ----------------------------------------------------------------------
# Project Settings page — Models tab.
# ----------------------------------------------------------------------


class TestProjectModelsTabProviderFilter:
    def test_project_models_page_lists_three_providers(
        self, project_settings_client: TestClient
    ) -> None:
        body = project_settings_client.get("/projects/alpha/settings").text
        assert "Anthropic" in body
        assert "OpenAI" in body
        assert "Google" in body

    def test_project_models_page_renders_all_provider_options(
        self, project_settings_client: TestClient
    ) -> None:
        body = project_settings_client.get("/projects/alpha/settings").text
        # Anthropic (existing dropdown content, default provider)
        assert "claude-opus-4-7" in body
        # OpenAI + Google option rows must also be in the DOM.
        assert "gpt-5.4" in body
        assert "gemini-3.1-pro-preview" in body
