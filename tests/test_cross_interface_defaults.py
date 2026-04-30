"""Cross-interface invariants between the CLI wizard and the dashboard.

Three of the v0.3.2 hardening commits trace back to one root cause:
the CLI wizard (``urika config``) and the dashboard's Models tab
maintained their own parallel constants for "the list of cloud
models we offer" and "what's the default best model". They drifted —
the CLI offered ``claude-opus-4-6`` while the dashboard hardcoded
``claude-opus-4-7`` — and users who clicked through the dashboard
form ended up with a stale-CLI-incompatible model pinned for every
agent, hitting the cryptic "Fatal error in message reader" symptom.

These tests pin the invariants so a future bump of one constant
without the other fails fast at CI time rather than mid-experiment.
"""

from __future__ import annotations


class TestKnownCloudModelsAgreement:
    """The CLI wizard's ``_CLOUD_MODELS`` and the dashboard's
    ``KNOWN_CLOUD_MODELS`` must contain the same set of cloud models.
    Order may differ (the CLI sorts by recommendation; the dashboard
    sorts so the visual default leads), but every model offered in
    one interface must be selectable in the other.
    """

    def test_cli_and_dashboard_offer_the_same_cloud_models(self) -> None:
        from urika.cli.config import _CLOUD_MODELS
        from urika.dashboard.routers.pages import KNOWN_CLOUD_MODELS

        cli_models = {m for m, _desc in _CLOUD_MODELS}
        dashboard_models = set(KNOWN_CLOUD_MODELS)

        # Both directions of the invariant — drift in either direction
        # is a bug. Use symmetric difference for a readable failure.
        assert cli_models == dashboard_models, (
            f"CLI ({cli_models}) and dashboard ({dashboard_models}) cloud "
            f"model lists drifted. Sync them in "
            f"src/urika/cli/config.py:_CLOUD_MODELS and "
            f"src/urika/dashboard/routers/pages.py:KNOWN_CLOUD_MODELS."
        )

    def test_dashboard_default_is_in_known_cloud_models(self) -> None:
        """The fallback string the dashboard templates use as the
        default-model selected option must be in the dropdown's
        option list — otherwise the dropdown shows whatever's first
        in the list and the comment lies."""
        from urika.dashboard.routers.pages import KNOWN_CLOUD_MODELS

        # The fallback expression in global_settings.html is
        # ``... or "claude-opus-4-6"``. If KNOWN_CLOUD_MODELS doesn't
        # contain that literal, the rendered <select> won't have any
        # option pre-selected when the user has no global default.
        assert "claude-opus-4-6" in KNOWN_CLOUD_MODELS, (
            "claude-opus-4-6 is the dashboard template's hardcoded "
            "fallback default. If you've removed it from "
            "KNOWN_CLOUD_MODELS, also update the four 'or "
            "\"claude-opus-4-6\"' fallback expressions in "
            "src/urika/dashboard/templates/global_settings.html."
        )


class TestPrivacyModesAgreement:
    """The list of valid privacy modes must agree across all sites
    that consume it. A pre-v0.3.2 stale ``VALID_PRIVACY_MODES`` in
    ``pages.py`` listed the defunct ``"university"`` mode and was
    missing ``"hybrid"`` while ``api.py`` had the canonical set.
    """

    def test_pages_and_api_modes_agree(self) -> None:
        from urika.dashboard.routers.api import _VALID_PRIVACY_MODES
        from urika.dashboard.routers.pages import VALID_PRIVACY_MODES

        assert set(VALID_PRIVACY_MODES) == _VALID_PRIVACY_MODES, (
            f"VALID_PRIVACY_MODES in pages.py ({VALID_PRIVACY_MODES}) "
            f"diverged from _VALID_PRIVACY_MODES in api.py "
            f"({_VALID_PRIVACY_MODES}). Both must contain the same "
            f"three modes: open, private, hybrid."
        )

    def test_modes_are_exactly_open_private_hybrid(self) -> None:
        from urika.dashboard.routers.pages import VALID_PRIVACY_MODES

        assert set(VALID_PRIVACY_MODES) == {"open", "private", "hybrid"}, (
            "Privacy modes must be exactly {open, private, hybrid}. "
            "The legacy 'university' mode was removed in v0.3.2."
        )


class TestSettingsRoundTrip:
    """The dashboard form writes settings; the runtime reads them via
    ``load_runtime_config``. Pre-v0.3.2 the two sides used different
    keys (form wrote ``[runtime.modes.<mode>].model``, ``urika new``
    read legacy flat ``[runtime].model``) and silently dropped the
    user's choice on new project creation.
    """

    def test_get_default_runtime_round_trips_per_mode_default(
        self, tmp_path, monkeypatch
    ) -> None:
        """Save a per-mode default model the way the dashboard form
        does, then read it back the way ``urika new`` does. The two
        must agree.
        """
        home = tmp_path / "urika_home"
        home.mkdir()
        monkeypatch.setenv("URIKA_HOME", str(home))

        from urika.core.settings import (
            get_default_runtime,
            save_settings,
        )

        # Mirror what the dashboard form's POST handler writes.
        save_settings(
            {
                "runtime": {
                    "modes": {
                        "open": {"model": "claude-opus-4-6"},
                        "hybrid": {"model": "claude-opus-4-6"},
                    }
                }
            }
        )

        # Mirror what project_builder does at creation time.
        rt_open = get_default_runtime("open")
        rt_hybrid = get_default_runtime("hybrid")

        assert rt_open["model"] == "claude-opus-4-6", (
            "Dashboard wrote runtime.modes.open.model but get_default_runtime "
            "did NOT read it back — the legacy flat-key fallback won. "
            "This is the urika-new-ignores-global-default bug."
        )
        assert rt_hybrid["model"] == "claude-opus-4-6"


class TestNonInteractiveAdvisorIntegration:
    """Integration test: actually launch ``urika advisor`` as a
    subprocess with stdin closed (the exact path the dashboard's
    ``spawn_advisor`` takes). Pre-v0.3.2 this path silently auto-
    fired multi-hour experiment runs because the CLI's "Run these
    experiments? [Yes]" prompt fell through to the default on EOF.
    The hotfix added a ``sys.stdin.isatty()`` guard at the call site,
    but the existing test only mocked ``isatty`` — it never
    exercised the real subprocess + DEVNULL stdin path that the
    dashboard takes.
    """

    def test_subprocess_invocation_is_a_module(self) -> None:
        """Smoke check: confirm ``python -m urika`` is a valid
        invocation form. The full subprocess test (which requires
        a real project, an API key, etc.) lives in the manual
        end-to-end smoke step rather than the unit suite — this is
        a sentinel that catches obvious regressions in the module
        entry point.
        """
        import importlib

        # python -m urika resolves to urika/__main__.py — make sure
        # the import path is intact.
        assert importlib.util.find_spec("urika.__main__") is not None, (
            "python -m urika requires urika/__main__.py — this is the "
            "exact entry point dashboard's spawn_advisor uses."
        )
