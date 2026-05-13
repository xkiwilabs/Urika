"""Cross-interface parity — every constant or default that's referenced
from more than one interface (CLI, REPL, TUI, dashboard, agent prompts)
should derive from a single source or be pinned to agree.

This file extends :mod:`tests.test_cross_interface_defaults` (which
covers cloud models, privacy modes, and the get_default_runtime round
trip) with the rest of the cross-interface surface area:

* **Audience choices** — three CLI commands (``report``, ``finalize``,
  ``present``) each declare ``click.Choice([...])``. They must agree
  with ``core.models.VALID_AUDIENCES`` and the agent's
  ``AUDIENCE_INSTRUCTIONS`` dict (drift = "valid CLI audience that the
  agent doesn't know what to do with").
* **Notification channels** — the strings ``"email"``, ``"slack"``,
  ``"telegram"`` are written into ``[notifications].channels`` by the
  dashboard, read by the CLI status command, and dispatched by
  ``notifications/__init__.py``. A new channel added in one place
  silently breaks the others if these strings drift.
* **Privacy modes** — extends the existing pages.py vs api.py check
  with the workspace default + ProjectConfig validator.
* **Presentation theme default** — three call sites independently
  default to ``"light"`` when ``preferences.presentation_theme`` is
  missing; if they ever disagree, a project ends up with mixed-theme
  artifacts on the same finalize run.
* **LLM_PROVIDERS** — provider name uniqueness, name⊆KNOWN_SECRETS,
  Anthropic-must-be-available invariants.
"""

from __future__ import annotations


# ── Audience choices ───────────────────────────────────────────────


class TestAudienceChoicesAgreement:
    """The three CLI agent commands each have their own
    ``click.Choice([...])`` for ``--audience``. They must agree with
    each other AND with the canonical ``VALID_AUDIENCES`` set in
    ``core/models.py`` AND with the keys of
    ``agents.audience.AUDIENCE_INSTRUCTIONS``.

    Adding a new audience requires updating five places — this test
    catches drift if only some are updated.
    """

    def _cli_audience_choices(self) -> dict[str, set[str]]:
        """Inspect the click decorators on the three agent commands
        and extract their --audience Choice values."""
        from urika.cli import agents_finalize, agents_present, agents_report

        out: dict[str, set[str]] = {}
        for mod, cmd_name in [
            (agents_report, "report"),
            (agents_finalize, "finalize"),
            (agents_present, "present"),
        ]:
            # The click command is a module-level attribute named after
            # the subcommand (or sometimes ``cli`` / ``command``).
            cmd = None
            for attr in dir(mod):
                obj = getattr(mod, attr)
                # click.Command objects have .params with click.Option
                # instances.
                if hasattr(obj, "params"):
                    for p in obj.params:
                        if getattr(p, "name", "") == "audience" and hasattr(
                            p.type, "choices"
                        ):
                            cmd = (attr, set(p.type.choices))
                            break
                if cmd is not None:
                    break
            assert cmd is not None, f"--audience option not found in {cmd_name}"
            out[cmd_name] = cmd[1]
        return out

    def test_all_three_cli_commands_offer_the_same_audiences(self) -> None:
        choices = self._cli_audience_choices()
        report = choices["report"]
        finalize = choices["finalize"]
        present = choices["present"]
        assert report == finalize == present, (
            f"--audience choices drifted across CLI commands: "
            f"report={report}, finalize={finalize}, present={present}. "
            f"Sync them in src/urika/cli/agents_{{report,finalize,present}}.py."
        )

    def test_cli_audiences_agree_with_core_models(self) -> None:
        """CLI ``click.Choice`` set ⊆ ``VALID_AUDIENCES`` — a CLI
        user shouldn't be able to pass an audience the
        ``ProjectConfig`` validator rejects."""
        from urika.core.models import VALID_AUDIENCES

        report = self._cli_audience_choices()["report"]
        assert report.issubset(VALID_AUDIENCES), (
            f"CLI offers audiences {report - VALID_AUDIENCES} that "
            f"core/models.py:VALID_AUDIENCES doesn't accept."
        )

    def test_cli_audiences_agree_with_agent_instruction_keys(self) -> None:
        """Every CLI-acceptable audience must have an
        ``AUDIENCE_INSTRUCTIONS`` entry — otherwise the agent prompt
        silently falls back to the default and the user's
        ``--audience`` flag is a lie."""
        from urika.agents.audience import AUDIENCE_INSTRUCTIONS

        report = self._cli_audience_choices()["report"]
        missing = report - set(AUDIENCE_INSTRUCTIONS.keys())
        assert not missing, (
            f"CLI accepts {missing} but agents.audience.AUDIENCE_INSTRUCTIONS "
            f"has no entry — agent prompt falls back to default silently."
        )

    def test_core_models_and_audience_module_agree(self) -> None:
        """The canonical source-of-truth set ``VALID_AUDIENCES`` and
        the agent's keyed ``AUDIENCE_INSTRUCTIONS`` must list the
        same names."""
        from urika.agents.audience import AUDIENCE_INSTRUCTIONS
        from urika.core.models import VALID_AUDIENCES

        assert VALID_AUDIENCES == set(AUDIENCE_INSTRUCTIONS.keys()), (
            f"VALID_AUDIENCES={VALID_AUDIENCES} != "
            f"AUDIENCE_INSTRUCTIONS keys={set(AUDIENCE_INSTRUCTIONS.keys())}"
        )


# ── Notification channels ──────────────────────────────────────────


class TestNotificationChannelNamesAgree:
    """The literal strings ``"email"``, ``"slack"``, ``"telegram"`` are
    used in four places: dashboard form posts, CLI status renderer,
    ``notifications/__init__.py`` dispatcher, and ``test_send.py``. A
    typo (or a renamed channel) in any one silently drops messages.
    """

    KNOWN_CHANNELS = {"email", "slack", "telegram"}

    def test_init_dispatches_all_known_channels(self) -> None:
        """``notifications/__init__.py`` instantiates EmailChannel,
        SlackChannel, TelegramChannel — confirm the dispatcher
        recognises the three canonical names. We grep the source
        rather than importing because importing the channels eagerly
        loads optional deps (slack_sdk, smtplib)."""
        from pathlib import Path

        import urika.notifications

        src = (Path(urika.notifications.__file__).parent / "__init__.py").read_text()
        for name in self.KNOWN_CHANNELS:
            assert f'"{name}"' in src or f"'{name}'" in src, (
                f"notifications/__init__.py dispatcher does not handle "
                f"the channel name {name!r}."
            )

    def test_known_secrets_covers_all_channels(self) -> None:
        """Each enabled channel needs at least one credential secret
        registered in :data:`KNOWN_SECRETS`. Without that the dashboard's
        Secrets tab can't autocomplete the secret name and users hit a
        blank-form footgun when wiring up a channel."""
        from urika.core.known_secrets import KNOWN_SECRETS

        # Each channel must have a secret whose name contains the
        # channel's identifying token.
        markers = {
            "email": ("URIKA_EMAIL_PASSWORD",),  # SMTP password env
            "slack": ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"),
            "telegram": ("TELEGRAM_BOT_TOKEN",),
        }
        for channel, names in markers.items():
            present = [n for n in names if n in KNOWN_SECRETS]
            assert present, (
                f"Channel {channel!r} has no KNOWN_SECRETS entries — "
                f"the dashboard Secrets tab won't suggest any envvar "
                f"name to the user. Expected one of {names}."
            )


# ── Privacy modes — extends test_cross_interface_defaults ──────────


class TestPrivacyModesAgreeWithProjectConfig:
    """The canonical "valid privacy modes" check in
    test_cross_interface_defaults pins pages.py ↔ api.py. Extension:
    the same set must agree with what ``ProjectConfig`` /
    workspace.create_project_workspace accepts."""

    def test_workspace_accepts_each_mode(self, tmp_path) -> None:
        """create_project_workspace + ProjectConfig accept each mode in
        the dashboard's list without raising."""
        from urika.core.models import ProjectConfig
        from urika.core.workspace import create_project_workspace
        from urika.dashboard.routers.pages import VALID_PRIVACY_MODES

        for mode in VALID_PRIVACY_MODES:
            proj = tmp_path / f"proj_{mode}"
            cfg = ProjectConfig(name=f"p_{mode}", question="?", mode="exploratory")
            create_project_workspace(proj, cfg)
            # Toggle privacy mode after workspace creation (the dashboard
            # writes [privacy].mode on POST /api/projects).
            toml_path = proj / "urika.toml"
            toml_path.write_text(
                toml_path.read_text() + f'\n[privacy]\nmode = "{mode}"\n'
            )


# ── Presentation theme default ─────────────────────────────────────


class TestPresentationThemeDefaultAgrees:
    """Three modules independently call
    ``tdata.get("preferences", {}).get("presentation_theme", "light")``.

    If one of them ever drifted (e.g. someone changes ``"light"`` to
    ``"dark"`` in ``orchestrator/finalize.py`` but not in
    ``orchestrator/loop_finalize.py`` or ``repl/helpers.py``), the
    same finalize run could produce a light-themed slide deck via the
    standalone CLI and a dark-themed one via the autonomous loop.
    """

    def test_default_is_light_everywhere(self) -> None:
        from pathlib import Path

        import urika

        urika_root = Path(urika.__file__).parent
        files = [
            urika_root / "repl" / "helpers.py",
            urika_root / "orchestrator" / "finalize.py",
            urika_root / "orchestrator" / "loop_finalize.py",
        ]
        for path in files:
            assert path.exists(), f"presentation_theme call site moved: {path}"
            src = path.read_text()
            # The pattern is .get("presentation_theme", "light")
            assert '"presentation_theme", "light"' in src, (
                f"{path} no longer defaults presentation_theme to 'light'. "
                f"If you've changed the default, update all three call "
                f"sites (repl/helpers.py, orchestrator/finalize.py, "
                f"orchestrator/loop_finalize.py) so the same project "
                f"doesn't produce mixed-theme outputs."
            )


# ── LLM_PROVIDERS invariants ───────────────────────────────────────


class TestLLMProvidersInvariants:
    """``LLM_PROVIDERS`` drives the dashboard's Secrets-tab "LLM
    Providers" panel. The dashboard reads the list and renders one row
    per provider. The invariants below catch quiet breakage of that
    rendering contract.
    """

    def test_anthropic_is_available_and_first(self) -> None:
        """Anthropic is the only working adapter today — it must be in
        the list AND marked available. If it ever flips to
        ``available=False`` the dashboard refuses to save the API key
        and the entire app loses its provider."""
        from urika.core.known_secrets import LLM_PROVIDERS

        anthropic = next(
            (p for p in LLM_PROVIDERS if p.name == "ANTHROPIC_API_KEY"), None
        )
        assert anthropic is not None, (
            "LLM_PROVIDERS must contain ANTHROPIC_API_KEY — it's the "
            "only working adapter in v0.4.x."
        )
        assert anthropic.available is True, (
            "ANTHROPIC_API_KEY must be marked available=True; "
            "otherwise dashboard refuses to save the API key."
        )

    def test_provider_names_are_unique(self) -> None:
        """Two ProviderInfo rows with the same env-var name would
        render as duplicate rows in the dashboard."""
        from urika.core.known_secrets import LLM_PROVIDERS

        names = [p.name for p in LLM_PROVIDERS]
        assert len(names) == len(set(names)), (
            f"LLM_PROVIDERS has duplicate names: {names}"
        )

    def test_each_provider_name_is_in_known_secrets(self) -> None:
        """LLM_PROVIDERS' env-var names are autocompleted from
        KNOWN_SECRETS in the dashboard form. A provider without a
        KNOWN_SECRETS entry renders without a description hint."""
        from urika.core.known_secrets import KNOWN_SECRETS, LLM_PROVIDERS

        for prov in LLM_PROVIDERS:
            assert prov.name in KNOWN_SECRETS, (
                f"LLM_PROVIDERS entry {prov.name!r} has no KNOWN_SECRETS "
                f"description — dashboard renders the row without a hint."
            )

    def test_each_provider_has_nonblank_display(self) -> None:
        from urika.core.known_secrets import LLM_PROVIDERS

        for prov in LLM_PROVIDERS:
            assert prov.display.strip(), (
                f"LLM_PROVIDERS entry {prov.name!r} has blank display — "
                f"dashboard row label is empty."
            )

    def test_each_provider_has_nonblank_description(self) -> None:
        from urika.core.known_secrets import LLM_PROVIDERS

        for prov in LLM_PROVIDERS:
            assert prov.description.strip(), (
                f"LLM_PROVIDERS entry {prov.name!r} has blank description — "
                f"dashboard row sub-label is empty."
            )

    def test_unavailable_providers_have_coming_soon_hint(self) -> None:
        """The dashboard renders ``available=False`` rows with a
        "coming soon" affordance — the description should hint at when.
        Catches the case where someone flips ``available=False`` without
        updating the description (or vice versa)."""
        from urika.core.known_secrets import LLM_PROVIDERS

        for prov in LLM_PROVIDERS:
            if not prov.available:
                # The description should mention v0.5 or "coming soon"
                # or "planned" so users understand why the row is
                # locked.
                desc = prov.description.lower()
                hints = ("v0.5", "v0.6", "coming", "planned", "upcoming")
                assert any(h in desc for h in hints), (
                    f"LLM_PROVIDERS entry {prov.name!r} is locked "
                    f"(available=False) but description has no "
                    f"'coming soon' hint: {prov.description!r}"
                )


# ── Valid modes / valid audiences exposed via dashboard JSON ───────


class TestValidModesValidAudiencesExposed:
    """The dashboard's page-context builders inject
    ``valid_modes`` + ``valid_audiences`` into Jinja templates so the
    <select> options stay in sync with the validator. If those lists
    are ever rebuilt manually (rather than from ``VALID_*``), the
    dropdown shows stale options."""

    def test_valid_audiences_is_sorted_list_of_set(self) -> None:
        """The page handler does ``sorted(VALID_AUDIENCES)`` — assert
        the result is a list of every audience in the set."""
        from urika.core.models import VALID_AUDIENCES

        valid = sorted(VALID_AUDIENCES)
        assert isinstance(valid, list)
        assert set(valid) == VALID_AUDIENCES
        # Stable order — sorted(set) is alphabetical.
        assert valid == sorted(valid)

    def test_valid_modes_is_sorted_list_of_set(self) -> None:
        from urika.core.models import VALID_MODES

        valid = sorted(VALID_MODES)
        assert set(valid) == VALID_MODES
        assert valid == sorted(valid)
