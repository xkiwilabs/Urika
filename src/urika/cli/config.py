"""Config-related CLI commands: config, notifications, setup, dashboard."""

from __future__ import annotations


import click

from urika.cli._base import cli

from urika.cli._helpers import (
    _resolve_project,
)


# Cloud (Claude) models the CLI wizard offers under ``urika config``.
# Hoisted to module scope in v0.3.2 so the cross-interface invariant
# test in ``tests/test_cross_interface_defaults.py`` can import it
# and assert it agrees with the dashboard's ``KNOWN_CLOUD_MODELS``
# list. Pre-v0.3.2 this lived inside ``_config_interactive`` and the
# two interfaces drifted (CLI offered 4-6 / sonnet-4-5 / haiku-4-5;
# dashboard offered 4-7 / 4-6 / sonnet / haiku) until users hit the
# cryptic "Fatal error in message reader" symptom.
#
# Order matters in CLI display: ``sonnet-4-5`` first because it's
# the recommended-default for the wizard. ``opus-4-6`` is the
# fallback the dashboard uses for new selections (since the bundled
# SDK CLI doesn't speak 4-7's request schema yet).
_CLOUD_MODELS: list[tuple[str, str]] = [
    ("claude-sonnet-4-5", "Best balance of speed and quality (recommended)"),
    ("claude-opus-4-6", "Most capable, slower, higher cost"),
    ("claude-opus-4-7", "Newest Opus — requires public claude CLI on PATH"),
    ("claude-haiku-4-5", "Fastest, lowest cost, less capable"),
]


def _prompt_for_endpoint_key_value(key_env: str) -> None:
    """Paired masked-value prompt for a privacy endpoint API key.

    Mirrors the dashboard's name+value flow: after the user supplies
    the env-var name, ask for the value at the same time. If they
    paste a value, save it to the global secrets vault under that
    name; if they leave it blank, assume the value is already set in
    their shell or vault and move on.

    Aborts (Ctrl-C / EOF) skip silently — the env-var name is still
    written to settings.toml, so the endpoint stays referenced even
    if the user bails out of the value step.
    """
    try:
        key_value = click.prompt(
            "  API key VALUE (leave blank if already set in env)",
            hide_input=True,
            default="",
            show_default=False,
        ).strip()
    except (click.Abort, EOFError, KeyboardInterrupt):
        click.echo("\n  (Skipped value entry.)")
        return

    if not key_value:
        return

    from urika.cli_display import print_success
    from urika.core.registry import _urika_home
    from urika.core.vault import SecretsVault

    # Pin to URIKA_HOME so the value lands next to settings.toml on
    # whichever home the CLI is currently writing to (test boxes set
    # URIKA_HOME to a tmp dir; production resolves to ~/.urika).
    SecretsVault(global_path=_urika_home() / "secrets.env").set_global(
        key_env,
        key_value,
        description="used by privacy endpoint",
    )
    print_success(f"  Saved value under {key_env}.")


@cli.command("dashboard")
@click.argument("project", required=False, default=None)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Server port (default: random free port)",
)
@click.option(
    "--auth-token",
    default=None,
    help=(
        "Require this bearer token on all requests "
        "(Authorization: Bearer <token>). /healthz and /static are exempt."
    ),
)
def dashboard(
    project: str | None,
    port: int | None,
    auth_token: str | None,
) -> None:
    """Open the dashboard in your browser.

    Without PROJECT, opens the projects list at ``/projects``.
    With PROJECT, opens that project's page at ``/projects/<name>``.
    """
    from urika.tui.dashboard_launcher import start_dashboard_server

    open_path = "/projects"
    label = "Urika dashboard"
    if project:
        # Validate project exists; _resolve_project raises ClickException on miss
        _path, _config = _resolve_project(project)
        open_path = f"/projects/{project}"
        label = f"{_config.name} dashboard"

    click.echo(f"\n  Starting {label}...")
    server, _thread, used_port = start_dashboard_server(
        port=port,
        open_path=open_path,
        auth_token=auth_token,
    )
    click.echo(f"  Listening on http://127.0.0.1:{used_port}{open_path}")
    if auth_token:
        click.echo("  Auth: Authorization: Bearer <token> required.")
    click.echo("  Press Ctrl+C to stop.")

    try:
        # Keep the main thread alive while the daemon thread serves
        import time

        while not getattr(server, "should_exit", False):
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.should_exit = True

    click.echo("  Dashboard stopped.")



@cli.command("config")
@click.argument("project", required=False, default=None)
@click.option("--show", is_flag=True, help="Show current settings.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option(
    "--test",
    "test_flag",
    is_flag=True,
    help=(
        "With ``api-key``: send a minimal request to api.anthropic.com "
        "to verify the configured ANTHROPIC_API_KEY actually works."
    ),
)
def config_command(
    project: str | None,
    show: bool,
    json_output: bool,
    test_flag: bool,
) -> None:
    """View or configure privacy mode and models.

    Without PROJECT, configures global defaults (~/.urika/settings.toml).
    With PROJECT, configures that project's urika.toml.

    Special forms:
      * ``urika config api-key``  — interactive Anthropic-API-key setup
        (saves to ``~/.urika/secrets.env``). Add ``--test`` to verify
        the saved key against api.anthropic.com.
      * ``urika config secret``   — interactive setup for an arbitrary
        named secret (e.g. a private vLLM key, HuggingFace token,
        third-party API credential). Saves to the global secrets vault
        the same way; agents and tools read it via ``os.environ.get(NAME)``.

    Examples:

        urika config --show              # show global defaults
        urika config                     # interactive setup (global)
        urika config api-key             # interactive Anthropic API key setup
        urika config api-key --test      # verify the saved key works
        urika config secret              # interactive setup for any named secret
        urika config my-project --show   # show project settings
        urika config my-project          # interactive setup (project)
    """
    from urika.cli_display import print_step
    from urika.cli_helpers import UserCancelled

    # ── Special routing: "urika config api-key" ──
    # ``api-key`` is a reserved pseudo-project name that triggers the
    # Anthropic API key wizard. Implemented here (rather than as a
    # standalone command) so the public surface matches the documented
    # ``urika config api-key`` invocation.
    if project == "api-key":
        if test_flag:
            _config_api_key_test()
            return
        _config_api_key_interactive()
        return

    # ── Special routing: "urika config secret" ──
    # Generic named-secret setup — for credentials Urika doesn't know
    # about specifically (private endpoint keys, HuggingFace tokens,
    # custom-tool API keys). Saves to the global SecretsVault, which
    # backs ~/.urika/secrets.env (or OS keyring when urika[keyring]
    # is installed). Phase B's dashboard Settings → Secrets tab will
    # add a UI for the same flow.
    if project == "secret":
        _config_secret_interactive()
        return

    # ── Determine target: global or project ──
    is_project = False
    project_path = None
    if project is not None:
        is_project = True
        try:
            project_path, _config = _resolve_project(project)
        except click.ClickException:
            raise

    # ── Load current settings ──
    if is_project:
        import tomllib

        toml_path = project_path / "urika.toml"
        with open(toml_path, "rb") as f:
            settings = tomllib.load(f)
    else:
        from urika.core.settings import load_settings

        settings = load_settings()

    # ── Show mode ──
    if show:
        if json_output:
            from urika.cli_helpers import output_json

            output_json(settings)
            return

        label = f"Project: {project}" if is_project else "Global defaults"
        click.echo(f"\n  {label}\n")
        p = settings.get("privacy", {})
        r = settings.get("runtime", {})
        if is_project:
            mode = p.get("mode", "open")
            print_step(f"Privacy mode: {mode}")
        else:
            print_step("Privacy mode: (set per project)")
        eps = p.get("endpoints", {})
        for ep_name, ep in eps.items():
            if isinstance(ep, dict):
                url = ep.get("base_url", "")
                key = ep.get("api_key_env", "")
                label_ep = f"  {ep_name}: {url}"
                if key:
                    label_ep += f" (key: ${key})"
                print_step(label_ep)
        if is_project:
            if r.get("model"):
                print_step(f"Default model: {r['model']}")
            models = r.get("models", {})
            for agent_name, agent_cfg in models.items():
                if isinstance(agent_cfg, dict):
                    m = agent_cfg.get("model", "")
                    ep = agent_cfg.get("endpoint", "open")
                    print_step(f"  {agent_name}: {m} (endpoint: {ep})")
                elif isinstance(agent_cfg, str):
                    print_step(f"  {agent_name}: {agent_cfg}")
        else:
            # Global per-mode defaults are stored under [runtime.modes.<mode>]
            modes = r.get("modes", {}) or {}
            for mode_name in ("open", "private", "hybrid"):
                cfg = modes.get(mode_name)
                if not isinstance(cfg, dict):
                    continue
                if cfg.get("model"):
                    print_step(f"[{mode_name}] default: {cfg['model']}")
                for agent_name, agent_cfg in (cfg.get("models", {}) or {}).items():
                    if isinstance(agent_cfg, dict):
                        m = agent_cfg.get("model", "")
                        ep = agent_cfg.get("endpoint", "open")
                        print_step(
                            f"  [{mode_name}] {agent_name}: {m} (endpoint: {ep})"
                        )
                    elif isinstance(agent_cfg, str):
                        print_step(f"  [{mode_name}] {agent_name}: {agent_cfg}")
        click.echo()
        return

    # ── Interactive setup ──
    current_mode = settings.get("privacy", {}).get("mode", "open")
    scope = f"project ({project})" if is_project else "global default"
    click.echo(f"\n  Current {scope} privacy mode: {current_mode}\n")

    try:
        _config_interactive(
            session=settings,
            current_mode=current_mode,
            is_project=is_project,
            project_path=project_path,
        )
    except UserCancelled:
        click.echo("\n  Cancelled.")
        return


def _config_interactive(*, session, current_mode, is_project, project_path):
    """Interactive config setup. Raises UserCancelled on cancel/ESC."""
    import click
    from urika.cli_display import print_step, print_success, print_warning
    from urika.cli_helpers import (
        UserCancelled,
        interactive_confirm,
        interactive_numbered,
        interactive_prompt,
    )

    settings = session

    mode = interactive_numbered(
        "  Privacy mode:",
        [
            "open — all agents use Claude API (cloud models only)",
            "private — all agents use local/server models (nothing leaves your network)",
            "hybrid — most agents use Claude API, data agents use local models",
        ],
        default={"open": 1, "private": 2, "hybrid": 3}.get(current_mode, 1),
    )
    mode = mode.split(" —")[0].strip()

    # Warn if changing from private/hybrid to less private
    if current_mode == "private" and mode in ("open", "hybrid"):
        print_warning(
            f"Changing from private to {mode} — agents will send data to cloud APIs."
        )
        if not interactive_confirm("  Continue?", default=False):
            click.echo("  Cancelled.")
            return
    elif current_mode == "hybrid" and mode == "open":
        print_warning(
            "Changing from hybrid to open — "
            "ALL agents (including data agent) will use cloud APIs."
        )
        if not interactive_confirm("  Continue?", default=False):
            click.echo("  Cancelled.")
            return

    # Project-scoped writes still live under flat [privacy]/[runtime];
    # globals now go under [runtime.modes.<mode>].  The runtime loader
    # reads both and prefers the project values.
    if is_project:
        settings.setdefault("privacy", {})["mode"] = mode

    def _set_default_model(model_name: str) -> None:
        """Write the per-mode default model — global goes under
        [runtime.modes.<mode>].model, project under [runtime].model."""
        if is_project:
            settings.setdefault("runtime", {})["model"] = model_name
        else:
            runtime = settings.setdefault("runtime", {})
            modes_section = runtime.setdefault("modes", {})
            modes_section.setdefault(mode, {})["model"] = model_name

    def _set_per_agent(agent: str, model_name: str, endpoint: str) -> None:
        """Write a per-agent override.  Global goes under
        [runtime.modes.<mode>.models.<agent>], project under
        [runtime.models.<agent>]."""
        row = {"model": model_name, "endpoint": endpoint}
        if is_project:
            (settings.setdefault("runtime", {})
                .setdefault("models", {}))[agent] = row
        else:
            runtime = settings.setdefault("runtime", {})
            modes_section = runtime.setdefault("modes", {})
            mode_cfg = modes_section.setdefault(mode, {})
            mode_cfg.setdefault("models", {})[agent] = row

    # ── Open mode: pick cloud model ──
    if mode == "open":
        click.echo()
        options = [f"{m} — {desc}" for m, desc in _CLOUD_MODELS]
        choice = interactive_numbered(
            "  Default model for all agents:",
            options,
            default=1,
        )
        model_name = choice.split(" —")[0].strip()
        _set_default_model(model_name)
        # Clear any private endpoints (project-scope only — globals
        # share endpoint defs across modes).
        if is_project:
            settings.get("privacy", {}).pop("endpoints", None)
        print_success(f"Mode: open · Model: {model_name}")

    # ── Private mode: configure endpoint + model ──
    elif mode == "private":
        # Project-scope: if globals already define a usable private
        # endpoint, the project doesn't need its own copy — leaving the
        # URL blank tells the wizard "use the inherited one". Drop
        # required=True in that case so blank input is a valid answer.
        # Globals-scope: the wizard is configuring the global endpoint
        # itself, so a URL is mandatory regardless.
        from urika.core.settings import get_named_endpoints

        _has_global_ep = any(
            (ep.get("base_url") or "").strip()
            for ep in get_named_endpoints()
        )
        _url_required = not (is_project and _has_global_ep)

        click.echo()
        ep_type = interactive_numbered(
            "  Private endpoint type:",
            [
                "Ollama (localhost:11434)",
                "LM Studio (localhost:1234)",
                "vLLM / LiteLLM server (network)",
                "Custom server URL",
            ],
            default=1,
        )
        if ep_type.startswith("Ollama"):
            ep_url = "http://localhost:11434"
        elif ep_type.startswith("LM Studio"):
            ep_url = "http://localhost:1234"
        elif ep_type.startswith("vLLM"):
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt(
                "  Server URL without /v1 (e.g. http://192.168.1.100:4200)"
                + (" [blank = inherit from globals]" if not _url_required else ""),
                required=_url_required,
            )
        else:
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt(
                "  Server URL"
                + (" [blank = inherit from globals]" if not _url_required else ""),
                required=_url_required,
            )

        # When the user typed a URL we honor it as a project-local
        # override.  When blank AND globals have one, fall through —
        # the runtime loader will inherit the global endpoint
        # (commit 1).  Without globals, refuse to save a blank URL
        # (runtime would raise MissingPrivateEndpointError).
        ep_url = (ep_url or "").strip()
        if not ep_url:
            if not _has_global_ep:
                raise UserCancelled()
            # Blank URL + globals available: skip endpoint write entirely.
            ep = None
        else:
            p = settings.setdefault("privacy", {})
            ep = p.setdefault("endpoints", {}).setdefault("private", {})
            ep["base_url"] = ep_url

            # API key only for remote servers (not Ollama/LM Studio)
            if "localhost" not in ep_url and "127.0.0.1" not in ep_url:
                from urika.cli_helpers import interactive_prompt

                key_env = interactive_prompt(
                    "  API key env var NAME, not the key itself (e.g. INFERENCE_HUB_KEY)",
                    default="",
                )
                if key_env:
                    ep["api_key_env"] = key_env
                    _prompt_for_endpoint_key_value(key_env)

        from urika.cli_helpers import interactive_prompt
        from urika.core.settings import load_settings

        global_settings = load_settings()
        # Read the global per-mode default first; fall back to legacy
        # flat [runtime].model for backward compat.
        global_model = (
            global_settings.get("runtime", {})
            .get("modes", {})
            .get("private", {})
            .get("model", "")
        ) or global_settings.get("runtime", {}).get("model", "")

        model_name = interactive_prompt(
            "  Model name" + (f" [{global_model}]" if global_model else " (e.g. qwen3:14b)"),
            default=global_model if global_model else "",
            required=True,
        )
        _set_default_model(model_name)
        _ep_label = ep_url if ep_url else "(inherits from globals)"
        print_success(
            f"Mode: private · Endpoint: {_ep_label} · Model: {model_name}"
        )

    # ── Hybrid mode: cloud model + private endpoint for data agents ──
    elif mode == "hybrid":
        # Cloud model for most agents
        click.echo()
        options = [f"{m} — {desc}" for m, desc in _CLOUD_MODELS]
        choice = interactive_numbered(
            "  Cloud model for most agents:",
            options,
            default=1,
        )
        cloud_model = choice.split(" —")[0].strip()
        _set_default_model(cloud_model)

        # Project-scope: if globals already define a usable private
        # endpoint, the project doesn't need its own copy — leaving the
        # URL blank tells the wizard "use the inherited one". Drop
        # required=True in that case.
        from urika.core.settings import get_named_endpoints

        _has_global_ep = any(
            (ep.get("base_url") or "").strip()
            for ep in get_named_endpoints()
        )
        _url_required = not (is_project and _has_global_ep)

        # Private endpoint for data agents
        click.echo()
        click.echo("  Data Agent and Tool Builder must use a private model.")
        ep_type = interactive_numbered(
            "  Private endpoint type:",
            [
                "Ollama (localhost:11434)",
                "LM Studio (localhost:1234)",
                "vLLM / LiteLLM server (network)",
                "Custom server URL",
            ],
            default=1,
        )
        if ep_type.startswith("Ollama"):
            ep_url = "http://localhost:11434"
        elif ep_type.startswith("LM Studio"):
            ep_url = "http://localhost:1234"
        elif ep_type.startswith("vLLM"):
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt(
                "  Server URL without /v1 (e.g. http://192.168.1.100:4200)"
                + (" [blank = inherit from globals]" if not _url_required else ""),
                required=_url_required,
            )
        else:
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt(
                "  Server URL"
                + (" [blank = inherit from globals]" if not _url_required else ""),
                required=_url_required,
            )

        # Honor a typed URL as a project-local override.  Blank +
        # globals available → skip endpoint write so the runtime loader
        # inherits.  Blank + no globals → cancel (runtime would crash).
        ep_url = (ep_url or "").strip()
        if not ep_url:
            if not _has_global_ep:
                raise UserCancelled()
        else:
            p = settings.setdefault("privacy", {})
            ep = p.setdefault("endpoints", {}).setdefault("private", {})
            ep["base_url"] = ep_url

            if "localhost" not in ep_url and "127.0.0.1" not in ep_url:
                from urika.cli_helpers import interactive_prompt

                key_env = interactive_prompt(
                    "  API key environment variable name",
                    default="",
                )
                if key_env:
                    ep["api_key_env"] = key_env
                    _prompt_for_endpoint_key_value(key_env)

        from urika.cli_helpers import interactive_prompt
        from urika.core.settings import load_settings

        # Default from global settings if configured. Prefer the new
        # per-mode location; fall back to legacy flat keys.
        global_settings = load_settings()
        global_data_model = (
            global_settings.get("runtime", {})
            .get("modes", {})
            .get("hybrid", {})
            .get("models", {})
            .get("data_agent", {})
            .get("model", "")
        ) or (
            global_settings.get("runtime", {})
            .get("models", {})
            .get("data_agent", {})
            .get("model", "")
        )

        private_model = interactive_prompt(
            "  Private model for data agents"
            + (f" [{global_data_model}]" if global_data_model else " (e.g. qwen3:14b)"),
            default=global_data_model if global_data_model else "",
            required=True,
        )

        # data_agent + tool_builder are forced-private in hybrid mode
        # (see _PRIVATE_AGENTS in agents.config).
        _set_per_agent("data_agent", private_model, "private")
        _set_per_agent("tool_builder", private_model, "private")

        _ep_label = ep_url if ep_url else "(inherits from globals)"
        print_success(
            f"Mode: hybrid · Cloud: {cloud_model} · "
            f"Data agents: {private_model} via {_ep_label}"
        )

    # ── Save ──
    if is_project:
        from urika.core.workspace import _write_toml

        _write_toml(project_path / "urika.toml", settings)
        print_step(f"Saved to {project_path / 'urika.toml'}")
    else:
        from urika.core.settings import save_settings

        save_settings(settings)
        from urika.core.settings import _settings_path

        print_step(f"Saved to {_settings_path()}")

    click.echo()
    click.echo(
        "  Tip: for per-agent model overrides, edit the [runtime.models] "
        "section in urika.toml directly."
    )
    click.echo()





def _config_api_key_interactive() -> None:
    """Interactive Anthropic API key setup.

    Prompts for the key (masked input), validates the format (should
    start with ``sk-ant-`` and be plausibly long), and saves it to
    ``~/.urika/secrets.env`` as ``ANTHROPIC_API_KEY=...``.

    Per Anthropic's Consumer Terms §3.7 and the April 2026 Agent SDK
    clarification, Pro/Max OAuth tokens cannot authenticate the Agent
    SDK — Urika requires an API key for any of its commands.
    """
    from urika.cli_display import print_step, print_success, print_warning
    from urika.core.secrets import save_secret

    click.echo()
    print_step("Anthropic API key setup")
    click.echo()
    click.echo(
        "  Per Anthropic's Consumer Terms §3.7 and the April 2026 Agent SDK"
    )
    click.echo(
        "  clarification, Urika cannot use a Claude Pro/Max subscription to"
    )
    click.echo(
        "  authenticate the Agent SDK. An API key is required."
    )
    click.echo()
    click.echo(
        "  Get a key at https://console.anthropic.com (Settings → API Keys)."
    )
    click.echo()

    try:
        value = click.prompt(
            "  Paste your ANTHROPIC_API_KEY",
            hide_input=True,
            default="",
            show_default=False,
        ).strip()
    except (click.Abort, EOFError, KeyboardInterrupt):
        click.echo("\n  Cancelled.")
        return

    if not value:
        print_warning("No key entered — cancelled.")
        return

    looks_valid = value.startswith("sk-ant-") and len(value) >= 50
    if not looks_valid:
        print_warning(
            "Key does not look like an Anthropic API key "
            "(expected sk-ant-... and ≥50 chars)."
        )
        try:
            keep = click.confirm("  Save anyway?", default=False)
        except (click.Abort, EOFError, KeyboardInterrupt):
            click.echo("\n  Cancelled.")
            return
        if not keep:
            click.echo("  Cancelled.")
            return

    save_secret("ANTHROPIC_API_KEY", value)
    print_success(
        "Saved to ~/.urika/secrets.env (chmod 600). "
        "Active in this and future sessions."
    )

    # Offer to verify the key end-to-end against api.anthropic.com.
    # If the test fails the spend-limit nudge below is meaningless
    # (the user has bigger problems to fix), so we skip it.
    click.echo()
    try:
        want_test = click.confirm(
            "  Send a test request to verify the key works?",
            default=True,
        )
    except (click.Abort, EOFError, KeyboardInterrupt):
        return

    test_passed = True
    if want_test:
        click.echo()
        test_passed = _print_api_key_test_result(value)

    if not test_passed:
        # Don't prompt about spend limits when the key itself doesn't work.
        return

    # Optional: nudge towards a spend limit.
    click.echo()
    try:
        want_limit = click.confirm(
            "  Set a spend limit on console.anthropic.com?",
            default=True,
        )
    except (click.Abort, EOFError, KeyboardInterrupt):
        return
    if want_limit:
        click.echo()
        click.echo(
            "  Visit https://console.anthropic.com → Settings → Billing →"
        )
        click.echo(
            "  Spend limits, and pick a monthly cap (e.g. $20). Urika does"
        )
        click.echo("  not set the limit programmatically.")
        click.echo()


def _mask_api_key(key: str) -> str:
    """Return a redacted display form of an API key (last 4 chars only)."""
    if not key:
        return "(unset)"
    if len(key) <= 4:
        return "***"
    return f"sk-ant-***...***{key[-4:]}"


def _print_api_key_test_result(key: str) -> bool:
    """Run the API key test and pretty-print the outcome.

    Returns True on success, False otherwise. Output mirrors the
    ``urika config api-key --test`` standalone path, so the same
    message arrives regardless of whether the user invoked the test
    interactively after save or directly via the flag.
    """
    from urika.cli_display import print_success, print_error
    from urika.core.anthropic_check import verify_anthropic_api_key

    click.echo("  Sending a minimal test request to api.anthropic.com...")
    click.echo()
    ok, message = verify_anthropic_api_key(key)
    if ok:
        print_success(f"API key works.  {message}")
        click.echo(
            "  Cost: this test consumed ~8 input + up to 5 output tokens (~$0.0001)."
        )
        click.echo()
        click.echo(
            "  Urika will use this key for all commands. Your Pro/Max"
        )
        click.echo(
            "  subscription is not used by Urika (per Anthropic's"
        )
        click.echo("  Consumer Terms §3.7).")
        return True

    print_error(f"API key test failed: {message}")
    click.echo()
    click.echo(
        "  Fix: regenerate at https://console.anthropic.com -> Settings ->"
    )
    click.echo("  API Keys, then re-run: urika config api-key")
    return False


def _config_secret_interactive() -> None:
    """Interactive setup for an arbitrary named secret.

    Prompts for a name (e.g. ``LLM_INFERENCE_KEY``) and a value (masked).
    Saves to the global ``SecretsVault`` — backs ``~/.urika/secrets.env``
    on file backend, OS keyring on ``urika[keyring]`` install. Designed
    for credentials Urika doesn't know about by name: private inference
    endpoints, HuggingFace tokens, custom-tool API keys.

    Common case: setting up hybrid mode where the data agent calls a
    local vLLM. The Privacy tab's ``api_key_env`` field stores the
    NAME of the env var; this command stores the VALUE under that name.

    Phase B's dashboard Settings -> Secrets tab adds a UI for the same
    flow. This CLI version stays for scriptability.
    """
    from urika.cli_display import print_step, print_success, print_warning

    click.echo()
    print_step("Set a named secret")
    click.echo()
    click.echo(
        "  Use this to store credentials by name — e.g. an API key for a"
    )
    click.echo(
        "  private vLLM endpoint, a HuggingFace token, or any other secret"
    )
    click.echo(
        "  a tool / agent reads via ``os.environ.get(NAME)``."
    )
    click.echo()
    click.echo(
        "  Convention: uppercase letters, digits, and underscores"
    )
    click.echo(
        "  (e.g. LLM_INFERENCE_KEY, HUGGINGFACE_HUB_TOKEN, WANDB_API_KEY)."
    )
    click.echo()

    try:
        name = click.prompt(
            "  Variable name",
            default="",
            show_default=False,
        ).strip()
    except (click.Abort, EOFError, KeyboardInterrupt):
        click.echo("\n  Cancelled.")
        return

    if not name:
        print_warning("No name entered — cancelled.")
        return

    # Sanity check: leading 'sk-' / 'hf_' / 'xoxb-' suggests the user
    # pasted a value into the name field. Catch the common foot-gun
    # before saving and creating noise.
    looks_like_value = (
        name.startswith(("sk-", "hf_", "xoxb-", "xapp-", "ghp_", "github_pat_"))
        or " " in name
        or len(name) > 64
    )
    if looks_like_value:
        print_warning(
            "That looks like a secret VALUE, not a name. The name is something"
        )
        click.echo(
            "  like LLM_INFERENCE_KEY — uppercase letters / digits / underscores."
        )
        click.echo(
            "  The value (sk-..., hf_..., etc.) gets entered next, masked."
        )
        try:
            keep = click.confirm("  Continue with that name anyway?", default=False)
        except (click.Abort, EOFError, KeyboardInterrupt):
            click.echo("\n  Cancelled.")
            return
        if not keep:
            click.echo("  Cancelled.")
            return

    try:
        value = click.prompt(
            f"  Value for {name}",
            hide_input=True,
            default="",
            show_default=False,
        ).strip()
    except (click.Abort, EOFError, KeyboardInterrupt):
        click.echo("\n  Cancelled.")
        return

    if not value:
        print_warning("No value entered — cancelled.")
        return

    try:
        description = click.prompt(
            "  Description (optional, for your records)",
            default="",
            show_default=False,
        ).strip()
    except (click.Abort, EOFError, KeyboardInterrupt):
        description = ""

    from urika.core.vault import SecretsVault

    vault = SecretsVault()
    vault.set_global(name, value, description=description or "")

    print_success(
        f"Saved {name} (chmod 0600). Active in this shell and future Urika commands."
    )
    click.echo()
    click.echo(
        f"  Reference it in the dashboard's Privacy tab by entering"
    )
    click.echo(
        f"  {name} in the 'API key env var' field — NOT the value itself."
    )
    click.echo()


def _config_api_key_test() -> None:
    """Standalone path for ``urika config api-key --test``.

    Reads the current ``ANTHROPIC_API_KEY`` from the environment
    (which ``load_secrets()`` populates from ``~/.urika/secrets.env``
    at CLI start) and runs the same verification used by the
    interactive setup. Exits 1 if the key is unset or the test fails,
    so this is safe to drop into a shell pipeline / CI gate.
    """
    import os

    from urika.cli_display import print_error, print_step

    click.echo()
    print_step("Anthropic API key check")
    click.echo()

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print_error("ANTHROPIC_API_KEY is not set.")
        click.echo()
        click.echo(
            "  Set one with:  urika config api-key"
        )
        click.echo(
            "  Or export it:  export ANTHROPIC_API_KEY=sk-ant-..."
        )
        raise click.exceptions.Exit(1)

    click.echo(f"  Configured key: {_mask_api_key(key)}")
    click.echo("  Source:         ~/.urika/secrets.env (loaded at CLI start)")
    click.echo()
    ok = _print_api_key_test_result(key)
    if not ok:
        raise click.exceptions.Exit(1)


# ── Re-exports from sibling modules (Phase 8 split) ───────────────
# Importing these registers their @cli.command decorators and keeps
# the old import path working for cli.__init__ etc.
from urika.cli.config_notifications import notifications_command  # noqa: E402, F401
from urika.cli.config_setup import setup_command  # noqa: E402, F401
