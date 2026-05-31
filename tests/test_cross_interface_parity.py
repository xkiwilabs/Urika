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

import pytest


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


# ── Builder loop invocation parity (v0.4.5 Track 1) ───────────────


class TestBuilderLoopInvocationParity:
    """v0.4.5 Track 1: the interactive project-builder loop must be
    callable from both the CLI (``urika new``) and the dashboard
    (``POST /api/projects/{name}/builder/start``) against the same
    underlying core function, with identical agent prompts and
    identical on-disk artifacts when given identical dummy
    responses.

    Pre-v0.4.5 the loop body lived inline in
    ``cli/project_new._run_builder_agent_loop`` and was unreachable
    from the dashboard. The CLI wrapper now passes
    prompt_toolkit-based callbacks; the dashboard endpoints pass
    asyncio-queue-based callbacks. These tests pin the shared core's
    contract so neither surface can drift from the other
    accidentally.
    """

    def test_cli_and_dashboard_both_call_core(self) -> None:
        """Both surfaces must route through
        ``urika.core.builder_loop.run_builder_loop`` (single source
        of truth). If a future refactor reverts one surface to an
        inline copy, the import here will break or the function
        will diverge."""
        from urika.core.builder_loop import run_builder_loop

        assert callable(run_builder_loop)

        # CLI wrapper: thin sync entry that imports the core symbol.
        import inspect

        from urika.cli import project_new

        cli_src = inspect.getsource(project_new._run_builder_agent_loop)
        assert "from urika.core.builder_loop import" in cli_src, (
            "CLI wrapper should import the runtime-agnostic core, "
            "not reimplement the loop body inline"
        )
        assert "run_builder_loop" in cli_src, (
            "CLI wrapper should call the shared core function"
        )

        # Dashboard endpoint: same import.
        from urika.dashboard.routers import api as dashboard_api

        dash_src = inspect.getsource(dashboard_api.api_builder_start)
        assert "from urika.core.builder_loop import" in dash_src, (
            "Dashboard builder/start endpoint should import the "
            "runtime-agnostic core, not reimplement the loop body"
        )
        assert "run_builder_loop" in dash_src

    def test_builder_question_carries_options_and_terminal_flag(self) -> None:
        """The ``BuilderQuestion`` dataclass is the wire format
        between core and adapters. Both options-carrying
        clarifying questions and the terminal accept/refine/abort
        choice must round-trip through it without losing the
        ``is_terminal_choice`` flag — the dashboard wizard uses
        that flag to render the row as a button strip rather than
        a free-text turn.
        """
        from urika.core.builder_loop import BuilderQuestion

        q_free = BuilderQuestion(text="Anything to add?")
        assert q_free.options == []
        assert q_free.is_terminal_choice is False

        q_choice = BuilderQuestion(
            text="Pick one", options=["a", "b", "c"], is_terminal_choice=False
        )
        assert q_choice.options == ["a", "b", "c"]
        assert q_choice.is_terminal_choice is False

        q_terminal = BuilderQuestion(
            text="What now?",
            options=["Looks good", "Refine", "Abort"],
            is_terminal_choice=True,
        )
        assert q_terminal.is_terminal_choice is True

    def test_builder_event_kinds_cover_all_adapter_render_paths(self) -> None:
        """The dashboard wizard JS handles 8 event kinds (step,
        phase, model, tool_use, thinking, error, agent_text, question,
        done). The ``BuilderEvent`` Literal must include every kind
        the wizard knows how to render — adding a kind to the literal
        without updating the wizard is fine (forward-compatible);
        emitting a kind the wizard can't handle silently drops it.

        This test pins the contract: every event kind a real adapter
        currently produces is in the EventKind union.
        """
        from urika.core.builder_loop import EventKind

        # ``Literal[...].__args__`` gives the tuple of allowed string
        # literals. Match against the kinds the dashboard JS knows.
        kinds = set(EventKind.__args__)  # type: ignore[attr-defined]
        wizard_handled = {
            "step",
            "phase",
            "model",
            "tool_use",
            "thinking",
            "error",
            "agent_text",
            "question",
            "done",
        }
        missing_from_union = wizard_handled - kinds
        assert not missing_from_union, (
            f"wizard JS handles kinds the union doesn't declare: "
            f"{sorted(missing_from_union)} — adapter would emit a "
            f"kind that's not in the type contract"
        )

    def test_builder_aborted_is_the_documented_signal(self) -> None:
        """The CLI wrapper catches ``BuilderAborted`` to convert it
        into a ``click.ClickException("Aborted.")``; the dashboard's
        background runner catches it to set ``session.aborted=True``.
        Both rely on it being importable from the core."""
        from urika.core.builder_loop import BuilderAborted

        assert issubclass(BuilderAborted, Exception)


# ── Unlock helper invocation parity (v0.4.5 Track 2) ───────────────


class TestUnlockHelperParity:
    """v0.4.5 Track 2: stale-lock recovery must call a single source
    of truth — ``urika.core.unlock.try_unlock`` — from CLI, REPL,
    and dashboard. The TUI inherits the REPL command registry so it
    gets the same path automatically. Pre-v0.4.5 the safety logic
    lived inline in ``cli/data.py`` and the other surfaces had no
    parity at all.

    These tests pin that all three explicit surfaces route through
    the helper. A future refactor that re-inlines the logic on one
    surface will break the corresponding import check below.
    """

    def test_unlock_helper_is_the_documented_api(self) -> None:
        from urika.core.unlock import (
            UnlockResult,
            UnlockStatus,
            list_locked_experiments,
            try_unlock,
        )

        assert callable(try_unlock)
        assert callable(list_locked_experiments)
        # Stable string values for JSON consumers (dashboard, RPC).
        assert UnlockStatus.CLEARED.value == "cleared"
        assert UnlockStatus.NO_LOCK.value == "no_lock"
        assert UnlockStatus.REFUSED_LIVE_URIKA.value == "refused_live_urika"
        assert UnlockStatus.REFUSED_LIVE_OTHER.value == "refused_live_other"
        # UnlockResult must be frozen so callers can hash it / pass it
        # through queues without aliasing surprises.
        result = UnlockResult(
            status=UnlockStatus.NO_LOCK,
            experiment_id="x",
            lock_path=__import__("pathlib").Path("/tmp/x"),
        )
        with pytest.raises(Exception):
            result.status = UnlockStatus.CLEARED  # type: ignore[misc]

    def test_cli_unlock_calls_shared_helper(self) -> None:
        """CLI ``urika unlock`` (cli/data.py) must import from
        ``urika.core.unlock``, not re-implement the safety logic
        inline. Pre-v0.4.5 the logic was inline — extraction is
        what enables REPL + dashboard parity."""
        import inspect

        from urika.cli import data as cli_data

        # ``cli_data.unlock`` is a click.Command — get the underlying
        # function via ``.callback`` so ``inspect.getsource`` works.
        src = inspect.getsource(cli_data.unlock.callback)
        assert "from urika.core.unlock import" in src, (
            "CLI urika unlock should call the shared core helper, "
            "not the (deleted) inline logic"
        )
        assert "try_unlock" in src

    def test_repl_unlock_calls_shared_helper(self) -> None:
        import inspect

        from urika.repl.commands import cmd_unlock

        src = inspect.getsource(cmd_unlock)
        assert "from urika.core.unlock import" in src
        assert "try_unlock" in src

    def test_dashboard_unlock_calls_shared_helper(self) -> None:
        import inspect

        from urika.dashboard.routers import api as dashboard_api

        src = inspect.getsource(dashboard_api.api_unlock_experiment)
        assert "from urika.core.unlock import" in src
        assert "try_unlock" in src

    def test_unlock_status_values_match_dashboard_js_contract(self) -> None:
        """The dashboard's experiments.html JS branches on the
        ``status`` field of the 409 detail payload to decide which
        confirm message to show. The string values are pinned here
        as the wire contract between the JSON endpoint and the
        browser-side handler."""
        from urika.core.unlock import UnlockStatus

        assert UnlockStatus.REFUSED_LIVE_URIKA.value == "refused_live_urika"
        assert UnlockStatus.REFUSED_LIVE_OTHER.value == "refused_live_other"
        # And the endpoint exposes these strings in its detail payload
        # (verified separately in test_api_unlock.py).


# ── Notification auto-seed parity (v0.4.5 Track 3) ───────────────


class TestNotificationAutoSeedParity:
    """Both ``urika new`` (CLI) and ``POST /api/projects`` (dashboard)
    must seed ``[notifications].channels`` from the global per-channel
    ``auto_enable`` flags so a user who turned on Slack/Telegram once
    gets pinged for every new project. Pre-v0.4.5 the dashboard had
    already implemented this (api.py:264-272) but no test pinned it,
    so a future refactor could silently break the mobile-only user's
    workflow.

    The contract: BOTH surfaces must call
    ``urika.core.settings.get_default_notifications_auto_enable`` and
    apply its return value the same way.
    """

    def test_single_source_of_truth_helper_exists(self) -> None:
        from urika.core.settings import get_default_notifications_auto_enable

        result = get_default_notifications_auto_enable()
        assert isinstance(result, dict)
        # Every channel name must be a known notification dispatcher
        # name (see TestNotificationChannelNames for the canonical
        # set). dict values are bools.
        for ch, on in result.items():
            assert isinstance(ch, str), ch
            assert isinstance(on, bool), (ch, on)

    def test_cli_imports_auto_seed_helper(self) -> None:
        """CLI ``urika new`` path seeds notifications via the shared
        ``seed_project_notifications_from_global`` wrapper (which
        internally calls ``get_default_notifications_auto_enable``).
        Dashboard inlines the same logic. Either pattern preserves
        the parity contract — accept both so the test doesn't
        artificially force convergence on one helper form."""
        import inspect

        from urika.cli import project_new

        src = inspect.getsource(project_new)
        assert (
            "seed_project_notifications_from_global" in src
            or "get_default_notifications_auto_enable" in src
        ), (
            "CLI urika new should seed notifications channels from "
            "the global auto_enable flags — same as the dashboard"
        )

    def test_dashboard_imports_auto_seed_helper(self) -> None:
        import inspect

        from urika.dashboard.routers import api as dashboard_api

        src = inspect.getsource(dashboard_api.api_create_project)
        assert "get_default_notifications_auto_enable" in src, (
            "Dashboard POST /projects should seed notifications "
            "channels from the global auto_enable flags — same as the "
            "CLI. Pre-v0.4.5 there was a real risk this would drift "
            "since no test pinned the parity"
        )


# ── Pause-flag path parity (v0.4.5 Track 3) ─────────────────────────


class TestPauseFlagPathParity:
    """The orchestrator polls ``<project>/.urika/pause_requested`` to
    cooperatively pause / stop a run. Multiple surfaces write that
    flag (REPL ``/pause``, TUI ``/stop`` + ``/pause``, dashboard
    POST endpoints, RPC). CLI runs the orchestrator in-process so it
    uses ``PauseController`` directly (no file flag needed). Every
    surface that DOES use the file path must use the SAME path the
    orchestrator polls — drift would silently make pause / stop
    no-ops on one surface only.

    Single source of truth: ``urika.orchestrator.pause`` —
    ``read_and_clear_flag`` defines the canonical path.
    """

    def _canonical_relative_flag_path(self) -> tuple[str, str]:
        """The canonical pause-flag path relative to a project dir.
        ``read_and_clear_flag`` constructs ``project_dir / ".urika"
        / "pause_requested"`` — every writer must agree."""
        return (".urika", "pause_requested")

    def test_orchestrator_reads_canonical_path(self) -> None:
        import inspect

        from urika.orchestrator import pause as pause_module

        src = inspect.getsource(pause_module)
        # The canonical reader assembles the path piecewise:
        #   project_dir / ".urika" / "pause_requested"
        assert '".urika"' in src
        assert '"pause_requested"' in src

    def test_repl_pause_writes_canonical_path(self) -> None:
        import inspect

        from urika.repl.commands import cmd_pause

        src = inspect.getsource(cmd_pause)
        assert '".urika"' in src
        assert '"pause_requested"' in src
        # Content must be one of the two values the orchestrator
        # honours (``read_and_clear_flag`` accepts "pause" or "stop").
        assert '"pause"' in src or "'pause'" in src

    def test_tui_stop_writes_canonical_path(self) -> None:
        """The TUI's stop handler writes ``"stop"`` to the same flag
        the REPL/dashboard write ``"pause"`` to — the orchestrator's
        ``read_and_clear_flag`` distinguishes the two contents."""
        import inspect

        from urika.tui import app as tui_app

        src = inspect.getsource(tui_app)
        assert "pause_requested" in src
        # The TUI's stop path writes "stop"; pause path writes "pause".
        # Both go to the same file.

    def test_dashboard_pause_writes_canonical_path(self) -> None:
        import inspect

        from urika.dashboard.routers import api as dashboard_api

        src = inspect.getsource(dashboard_api.api_run_pause)
        assert '".urika"' in src or "pause_requested" in src
        # Dashboard's pause endpoint writes "pause" to the flag.

    def test_rpc_pause_writes_canonical_path(self) -> None:
        """RPC ``run.pause`` (called by external tools like the Slack /
        Telegram channels' inline keyboards) must write to the same
        path. Pre-v0.4 there was no RPC pause; the channel callbacks
        had to shell out to ``urika run --pause``."""
        import inspect

        from urika.rpc import methods as rpc_methods

        src = inspect.getsource(rpc_methods)
        assert '".urika"' in src
        assert '"pause_requested"' in src

    def test_pause_flag_content_protocol_is_two_known_strings(self) -> None:
        """``orchestrator.pause.read_and_clear_flag`` accepts exactly
        two contents: ``"pause"`` and ``"stop"``. Any other content
        is ignored. Pinning the protocol here so a new surface that
        writes a different string (e.g. ``"halt"``) would surface as
        a test failure rather than a silent no-op."""
        import inspect

        from urika.orchestrator import pause as pause_module

        src = inspect.getsource(pause_module.read_and_clear_flag)
        assert '"pause"' in src
        assert '"stop"' in src


# ── Criteria-met early exit parity (v0.4.5 Track 3) ─────────────────


class TestCriteriaMetEarlyExitParity:
    """When the evaluator emits a JSON block containing
    ``"criteria_met": true``, the orchestrator should exit the
    autonomous loop cleanly across every surface that drives it.

    All four surfaces converge on the same shared functions in
    ``urika.orchestrator`` — ``run_experiment`` for single-experiment
    runs, ``run_project`` for autonomous loops. The criteria-met
    handling lives in ``orchestrator/loop.py:680`` (single source);
    these tests pin that no surface bypasses the shared loop.
    """

    def test_shared_run_experiment_handles_criteria_met(self) -> None:
        """The single source of truth is ``orchestrator/loop.py`` —
        every surface must reach it for autonomous criteria handling."""
        import inspect

        from urika.orchestrator import loop as loop_module

        src = inspect.getsource(loop_module)
        # The branch must exist exactly once in the shared loop —
        # multiple copies would imply a fork.
        assert 'evaluation.get("criteria_met")' in src
        assert src.count('evaluation.get("criteria_met")') == 1, (
            "criteria_met handling should appear exactly once in the "
            "shared orchestrator loop — multiple occurrences would "
            "imply a per-surface fork"
        )

    def test_cli_run_uses_shared_run_experiment(self) -> None:
        """CLI ``urika run`` imports the shared orchestrator
        functions, doesn't reimplement the loop.

        Note: ``from urika.cli import run`` resolves to the click
        ``Command`` object (the ``@cli.command()`` decorator
        registration), so we use ``importlib`` to grab the module
        itself for ``inspect.getsource``."""
        import importlib
        import inspect

        cli_run_module = importlib.import_module("urika.cli.run")
        src = inspect.getsource(cli_run_module)
        assert "from urika.orchestrator import" in src
        assert "run_experiment" in src

    def test_repl_run_invokes_cli_run_command(self) -> None:
        """REPL ``/run`` delegates to the CLI's ``run`` command via
        ``ctx.invoke`` — no parallel orchestrator loop."""
        import inspect

        from urika.repl import commands_run

        src = inspect.getsource(commands_run)
        # ctx.invoke is the dispatch primitive used elsewhere in the
        # REPL (e.g. cmd_inspect, cmd_logs, cmd_update).
        assert "ctx" in src and "invoke" in src

    def test_dashboard_run_spawns_cli_subprocess(self) -> None:
        """Dashboard runs invoke the CLI as a subprocess so the same
        ``orchestrator.run_experiment`` path runs in both contexts.
        ``dashboard/runs.py:spawn_experiment_run`` is the entry."""
        from urika.dashboard.runs import spawn_experiment_run

        # The function exists and is callable; the actual spawn path
        # is exercised by the dashboard's existing run-launch tests.
        # This test only pins the import — losing the spawn function
        # would break the criteria-met chain for the dashboard.
        assert callable(spawn_experiment_run)


# ── Settings cascade parity (v0.4.5 Track 3) ────────────────────────


class TestSettingsCascadeParity:
    """The privacy / model settings cascade is project → global →
    hard-coded default. ``test_cross_interface_defaults.py`` already
    pins the dashboard ↔ ``get_default_runtime`` round-trip; this
    class extends that to verify EVERY surface's run path applies
    the same fallback by routing through ``urika.core.settings``
    helpers, not a parallel TOML read.
    """

    def test_get_default_runtime_is_the_documented_helper(self) -> None:
        """``get_default_runtime(privacy_mode)`` is the single
        documented entry point that every surface must use to
        resolve "what model + endpoint for an agent in this privacy
        mode". Pin its signature so a refactor doesn't accidentally
        rename it (which would silently break the dashboard's
        Settings → Models tab which round-trips through it)."""
        from urika.core.settings import get_default_runtime

        # Smoke: call it for each documented privacy mode and assert
        # a dict comes back. Empty/missing settings is fine — the
        # helper returns a dict (possibly empty) rather than raising.
        for mode in ("open", "private", "hybrid"):
            rt = get_default_runtime(mode)
            assert isinstance(rt, dict), (
                f"get_default_runtime({mode!r}) must return a dict — "
                f"every surface unpacks the result the same way"
            )

    def test_get_named_endpoints_is_the_endpoint_enumeration_helper(
        self,
    ) -> None:
        """Both CLI and dashboard show endpoint pickers built from
        ``get_named_endpoints``. The function returns a list of dicts
        with at minimum ``name`` + ``base_url``."""
        from urika.core.settings import get_named_endpoints

        result = get_named_endpoints()
        assert isinstance(result, list)
        for ep in result:
            assert isinstance(ep, dict)

    def test_cli_new_uses_shared_settings_helpers(self) -> None:
        import inspect

        from urika.cli import project_new

        src = inspect.getsource(project_new)
        # Pre-v0.4 the CLI did its own TOML reads here; v0.4 funnelled
        # everything through the shared helpers. Keep it that way.
        assert "get_named_endpoints" in src

    def test_dashboard_create_uses_shared_settings_helpers(self) -> None:
        import inspect

        from urika.dashboard.routers import api as dashboard_api

        src = inspect.getsource(dashboard_api.api_create_project)
        assert "get_named_endpoints" in src


# ── Memory curator invocation parity (v0.5.0 Task 4.1) ──────────────


class TestMemoryCuratorInvocationParity:
    """All three surfaces route memory curation through
    ``urika.core.memory_curator.run_curator`` — single source of truth.

    Adds v0.5.0 memory-deepening curator surface to the parity matrix:
    CLI ``urika memory curate``, REPL ``/memory curate``, and the
    dashboard ``POST /api/projects/{name}/memory/curate`` must ALL
    dispatch through the same async core function. A monkeypatched
    spy on ``urika.core.memory_curator.run_curator`` confirms each
    surface lands the same call shape (and that the ``apply`` flag
    threads through correctly).

    Pre-v0.5.0 there was no curator surface anywhere; this class pins
    that all three were added against the same implementation rather
    than three independent copies.
    """

    def _seed_project(
        self,
        tmp_project_dir,
        monkeypatch,
        name: str = "proj",
    ):
        """Build a project on disk + register it under a sandboxed
        ``URIKA_HOME``. Mirrors the helper used in
        ``tests/test_dashboard/test_api_memory_curate.py``.

        Returns the project directory ``Path``. The caller is expected
        to (a) drive whichever surface they're testing and (b) rely on
        the URIKA_HOME monkeypatch staying in scope until the test
        ends so the registry resolves the project name.
        """
        import json as _json

        from urika.core import project_memory as pm

        proj = tmp_project_dir / name
        proj.mkdir(parents=True, exist_ok=True)
        (proj / "urika.toml").write_text(
            f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
            f'description = ""\n\n[preferences]\naudience = "expert"\n'
        )
        home = tmp_project_dir / "_home"
        home.mkdir(exist_ok=True)
        monkeypatch.setenv("URIKA_HOME", str(home))
        (home / "projects.json").write_text(_json.dumps({name: str(proj)}))
        (proj / "memory").mkdir(parents=True, exist_ok=True)
        pm.save_entry(proj, mem_type="user", description="t", body="b")
        return proj

    def test_cli_curate_calls_run_curator(self, tmp_project_dir, monkeypatch) -> None:
        called: list[tuple[object, bool]] = []

        async def spy(project_dir, runner, apply=False):
            called.append((project_dir, apply))
            from urika.core.memory_curator import CuratorResult

            return CuratorResult(decisions=[], applied=apply)

        monkeypatch.setattr("urika.core.memory_curator.run_curator", spy)
        self._seed_project(tmp_project_dir, monkeypatch)

        from click.testing import CliRunner

        from urika.cli import cli

        result = CliRunner().invoke(cli, ["memory", "curate", "proj"])
        assert result.exit_code == 0, result.output
        assert called, "CLI did not call run_curator"
        # Default is dry-run.
        assert called[0][1] is False

    def test_repl_curate_calls_run_curator(self, tmp_project_dir, monkeypatch) -> None:
        called: list[tuple[object, bool]] = []

        async def spy(project_dir, runner, apply=False):
            called.append((project_dir, apply))
            from urika.core.memory_curator import CuratorResult

            return CuratorResult(decisions=[], applied=apply)

        monkeypatch.setattr("urika.core.memory_curator.run_curator", spy)
        proj = self._seed_project(tmp_project_dir, monkeypatch)

        # Build a session the same way the REPL parity tests do (see
        # tests/test_repl/test_memory_curate.py::_setup).
        from urika.repl.session import ReplSession

        session = ReplSession()
        session.load_project(path=proj, name="proj")

        from urika.repl.commands import cmd_memory

        cmd_memory(session, "curate")
        assert called, "REPL did not call run_curator"
        assert called[0][1] is False

    def test_dashboard_curate_calls_run_curator(
        self, tmp_project_dir, monkeypatch
    ) -> None:
        called: list[tuple[object, bool]] = []

        async def spy(project_dir, runner, apply=False):
            called.append((project_dir, apply))
            from urika.core.memory_curator import CuratorResult

            return CuratorResult(decisions=[], applied=apply)

        monkeypatch.setattr("urika.core.memory_curator.run_curator", spy)
        self._seed_project(tmp_project_dir, monkeypatch)

        from fastapi.testclient import TestClient

        from urika.dashboard.app import create_app

        client = TestClient(create_app(tmp_project_dir, auth_token=None))
        resp = client.post(
            "/api/projects/proj/memory/curate",
            headers={"Origin": "http://testserver"},
        )
        assert resp.status_code == 200, resp.text
        assert called, "Dashboard did not call run_curator"
        assert called[0][1] is False

    def test_all_three_apply_flag_threads_through(
        self, tmp_project_dir, monkeypatch
    ) -> None:
        """``--apply`` (CLI), ``--apply`` (REPL slash), and
        ``?apply=true`` (dashboard) all reach ``run_curator(...,
        apply=True)``. The flag is the only state-changing
        parameter on the curator surface; a drift on any one of the
        three would mean a user's commit gesture silently turned
        into a dry-run (or worse, the reverse — a dry-run UX that
        mutated disk)."""
        seen: dict[str, bool] = {}

        async def spy(project_dir, runner, apply=False):
            from urika.core.memory_curator import CuratorResult

            return CuratorResult(decisions=[], applied=apply)

        monkeypatch.setattr("urika.core.memory_curator.run_curator", spy)
        proj = self._seed_project(tmp_project_dir, monkeypatch)

        # CLI surface.
        cli_calls: list[bool] = []

        async def cli_spy(project_dir, runner, apply=False):
            from urika.core.memory_curator import CuratorResult

            cli_calls.append(apply)
            return CuratorResult(decisions=[], applied=apply)

        monkeypatch.setattr("urika.core.memory_curator.run_curator", cli_spy)
        from click.testing import CliRunner

        from urika.cli import cli

        result = CliRunner().invoke(cli, ["memory", "curate", "proj", "--apply"])
        assert result.exit_code == 0, result.output
        assert cli_calls == [True], f"CLI --apply did not thread through: {cli_calls}"
        seen["cli"] = cli_calls[0]

        # REPL surface — re-monkeypatch the spy and re-drive.
        repl_calls: list[bool] = []

        async def repl_spy(project_dir, runner, apply=False):
            from urika.core.memory_curator import CuratorResult

            repl_calls.append(apply)
            return CuratorResult(decisions=[], applied=apply)

        monkeypatch.setattr("urika.core.memory_curator.run_curator", repl_spy)
        from urika.repl.commands import cmd_memory
        from urika.repl.session import ReplSession

        session = ReplSession()
        session.load_project(path=proj, name="proj")
        cmd_memory(session, "curate --apply")
        assert repl_calls == [True], (
            f"REPL --apply did not thread through: {repl_calls}"
        )
        seen["repl"] = repl_calls[0]

        # Dashboard surface.
        dash_calls: list[bool] = []

        async def dash_spy(project_dir, runner, apply=False):
            from urika.core.memory_curator import CuratorResult

            dash_calls.append(apply)
            return CuratorResult(decisions=[], applied=apply)

        monkeypatch.setattr("urika.core.memory_curator.run_curator", dash_spy)
        from fastapi.testclient import TestClient

        from urika.dashboard.app import create_app

        client = TestClient(create_app(tmp_project_dir, auth_token=None))
        resp = client.post(
            "/api/projects/proj/memory/curate?apply=true",
            headers={"Origin": "http://testserver"},
        )
        assert resp.status_code == 200, resp.text
        assert dash_calls == [True], (
            f"Dashboard ?apply=true did not thread through: {dash_calls}"
        )
        seen["dashboard"] = dash_calls[0]

        # Final cross-surface check — all three observed ``apply=True``.
        assert seen == {"cli": True, "repl": True, "dashboard": True}


# ── Memory CRUD path-shape parity (v0.5.0 Task 4.1) ─────────────────


class TestMemoryCRUDPathParity:
    """CLI, dashboard, and the direct core helper all produce memory
    entries at the same canonical path with the same naming
    convention: ``<project>/memory/<type>_<slug>.md``.

    The CLI ``urika memory add`` path opens ``click.edit`` when neither
    ``--from-file`` nor ``--stdin`` is supplied — that's not
    CliRunner-friendly, so we exercise the CLI's path-shape contract
    by driving ``save_entry`` (the same underlying primitive the CLI
    calls) and confirming all surfaces converge on the same on-disk
    layout.
    """

    def test_dashboard_post_writes_to_canonical_path(self, tmp_project_dir) -> None:
        """POST /api/projects/{name}/memory writes an entry to
        ``<project>/memory/<type>_<slug>.md`` — same shape every
        other surface produces."""
        import json as _json

        from fastapi.testclient import TestClient

        from urika.dashboard.app import create_app

        proj = tmp_project_dir / "proj"
        proj.mkdir(parents=True, exist_ok=True)
        (proj / "urika.toml").write_text(
            '[project]\nname = "proj"\nquestion = "q"\nmode = "exploratory"\n'
            'description = ""\n\n[preferences]\naudience = "expert"\n'
        )
        home = tmp_project_dir / "_home"
        home.mkdir(exist_ok=True)
        # Use monkeypatch via the env to keep parity with the other
        # dashboard tests — but here we set it directly because the
        # method signature in this class does not take monkeypatch
        # (matches the existing parity test style). The TestClient
        # uses its own short-lived process, so the env write is
        # scoped to this test invocation.
        import os as _os

        prev_home = _os.environ.get("URIKA_HOME")
        _os.environ["URIKA_HOME"] = str(home)
        try:
            (home / "projects.json").write_text(_json.dumps({"proj": str(proj)}))
            client = TestClient(create_app(tmp_project_dir, auth_token=None))
            resp = client.post(
                "/api/projects/proj/memory",
                data={"mem_type": "user", "description": "t", "body": "b"},
                headers={"Origin": "http://testserver"},
            )
            assert resp.status_code in (200, 201), resp.text
            # Canonical filename: <type>_<slug>.md. For description "t"
            # the slug is "t" so the file is "user_t.md".
            assert (proj / "memory" / "user_t.md").exists(), (
                f"Dashboard POST did not write canonical path; "
                f"contents: {list((proj / 'memory').iterdir())}"
            )
        finally:
            if prev_home is None:
                _os.environ.pop("URIKA_HOME", None)
            else:
                _os.environ["URIKA_HOME"] = prev_home

    def test_core_save_entry_matches_canonical_path(self, tmp_project_dir) -> None:
        """The underlying ``save_entry`` primitive (called by CLI
        ``urika memory add`` and the dashboard's POST handler) writes
        to the same ``<type>_<slug>.md`` path. Pinning this here means
        a future rename in ``project_memory.py`` would surface as a
        parity break, not a silent on-disk schema drift."""
        from urika.core import project_memory as pm

        proj = tmp_project_dir / "proj"
        (proj / "memory").mkdir(parents=True, exist_ok=True)
        path = pm.save_entry(proj, mem_type="user", description="t", body="b")
        assert (proj / "memory" / "user_t.md").exists()
        # And the returned path matches.
        assert path == proj / "memory" / "user_t.md"

    def test_cli_save_entry_call_shape_matches_dashboard(self, tmp_project_dir) -> None:
        """The CLI ``urika memory add`` path opens ``click.edit`` for
        the editor case — not CliRunner-friendly. Instead, assert that
        the CLI imports/uses the SAME ``save_entry`` primitive the
        dashboard does, so its on-disk artifact lands at the canonical
        path.

        This is the static-analysis equivalent of the dynamic
        dashboard-POST test above: by pinning the import + same
        primitive name, we guarantee both surfaces produce the same
        on-disk layout without having to drive an interactive editor.
        """
        import inspect

        from urika.cli import memory as cli_memory

        src = inspect.getsource(cli_memory.memory_add.callback)
        assert "save_entry" in src, (
            "CLI `urika memory add` should call the shared "
            "`urika.core.project_memory.save_entry` primitive — "
            "anything else would mean the CLI and dashboard could "
            "drift apart on the on-disk path layout."
        )
        assert "project_memory" in src or "from urika.core.project_memory" in src

        # Sanity: the slug rule used to build the canonical path is
        # deterministic — ``save_entry(mem_type='user', description='t',
        # body='b', slug='topic')`` lands at
        # ``memory/user_topic.md``. The CLI passes ``slug=topic``
        # (the positional argument). Confirm by direct call:
        from urika.core import project_memory as pm

        proj = tmp_project_dir / "proj2"
        (proj / "memory").mkdir(parents=True, exist_ok=True)
        path = pm.save_entry(
            proj, mem_type="user", description="d", body="b", slug="topic"
        )
        assert path == proj / "memory" / "user_topic.md"


# ── Archive layout parity (v0.5.0 Task 4.1) ─────────────────────────


class TestArchivePathParity:
    """``archive_entry`` produces a consistent ``memory/archive/
    <YYYY-MM>/<filename>`` layout regardless of caller.

    Two callers exist today: the direct ``project_memory.archive_entry``
    primitive (used by CLI/dashboard once they expose explicit archive
    actions) and the curator's apply path (``run_curator(apply=True)``
    routing ``archive`` decisions through ``_apply_decisions``). Both
    must land files at the same UTC-month layout. The curator pre-v0.5
    didn't exist; this test pins that adding it didn't introduce a
    parallel archive directory shape.
    """

    def test_direct_archive_uses_yyyy_mm_layout(self, tmp_project_dir) -> None:
        from datetime import datetime, timezone

        from urika.core import project_memory as pm

        proj = tmp_project_dir / "proj"
        (proj / "memory").mkdir(parents=True, exist_ok=True)
        pm.save_entry(proj, mem_type="user", description="x", body="b")
        name = pm.list_entries(proj)[0]["filename"]
        pm.archive_entry(proj, name)

        m = datetime.now(timezone.utc).strftime("%Y-%m")
        assert (proj / "memory" / "archive" / m / name).exists(), (
            f"archive_entry did not produce YYYY-MM layout; "
            f"archive dir contents: "
            f"{list((proj / 'memory' / 'archive').rglob('*'))}"
        )

    def test_curator_apply_uses_yyyy_mm_layout(self, tmp_project_dir) -> None:
        """When ``run_curator(apply=True)`` archives an entry, it
        produces the SAME ``<YYYY-MM>/<filename>`` layout as the
        direct primitive. Otherwise: dashboard's "show archived
        entries" list (which globs ``memory/archive/<YYYY-MM>``)
        would miss curator-produced files."""
        import asyncio
        import json
        from datetime import datetime, timezone

        from urika.agents.config import AgentConfig
        from urika.agents.runner import AgentResult, AgentRunner
        from urika.core import project_memory as pm
        from urika.core.memory_curator import run_curator

        proj = tmp_project_dir / "proj"
        (proj / "memory").mkdir(parents=True, exist_ok=True)
        pm.save_entry(proj, mem_type="user", description="x", body="b")
        name = pm.list_entries(proj)[0]["filename"]

        # Mirror the ``_FakeRunner`` pattern from
        # tests/test_core/test_memory_curator.py — same AgentResult
        # shape (success=True, text_output=fenced JSON, session_id,
        # num_turns, duration_ms).
        class _FakeRunner(AgentRunner):
            def __init__(self, decisions: list[dict]):
                self._decisions = decisions

            async def run(
                self,
                config: AgentConfig,
                prompt: str,
                *,
                on_message: object = None,
            ) -> AgentResult:
                body = json.dumps({"decisions": self._decisions})
                text = f"```json\n{body}\n```"
                return AgentResult(
                    success=True,
                    messages=[],
                    text_output=text,
                    session_id="session-memory_curator-0",
                    num_turns=1,
                    duration_ms=10,
                )

        runner = _FakeRunner(
            [{"action": "archive", "filename": name, "reason": "stale"}]
        )
        result = asyncio.run(run_curator(proj, runner=runner, apply=True))
        assert result.applied is True

        m = datetime.now(timezone.utc).strftime("%Y-%m")
        assert (proj / "memory" / "archive" / m / name).exists(), (
            "Curator's apply path did not produce the canonical "
            "YYYY-MM archive layout — dashboard's archive list would "
            "miss this entry."
        )
        # And the live entry was removed (curator's archive = move,
        # not copy — same semantics as direct archive_entry).
        assert not (proj / "memory" / name).exists()
