"""Config-related CLI commands: config, notifications, setup, dashboard."""

from __future__ import annotations


import click

from urika.cli._base import cli

from urika.cli._helpers import (
    _resolve_project,
)


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
def config_command(
    project: str | None,
    show: bool,
    json_output: bool,
) -> None:
    """View or configure privacy mode and models.

    Without PROJECT, configures global defaults (~/.urika/settings.toml).
    With PROJECT, configures that project's urika.toml.

    Examples:

        urika config --show              # show global defaults
        urika config                     # interactive setup (global)
        urika config my-project --show   # show project settings
        urika config my-project          # interactive setup (project)
    """
    from urika.cli_display import print_step
    from urika.cli_helpers import UserCancelled

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
        interactive_confirm,
        interactive_numbered,
        interactive_prompt,
    )

    _CLOUD_MODELS = [
        ("claude-sonnet-4-5", "Best balance of speed and quality (recommended)"),
        ("claude-opus-4-6", "Most capable, slower, higher cost"),
        ("claude-haiku-4-5", "Fastest, lowest cost, less capable"),
    ]

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
            )
        else:
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt("  Server URL")

        p = settings.setdefault("privacy", {})
        ep = p.setdefault("endpoints", {}).setdefault("private", {})
        ep["base_url"] = ep_url

        # API key only for remote servers (not needed for Ollama/LM Studio)
        if "localhost" not in ep_url and "127.0.0.1" not in ep_url:
            from urika.cli_helpers import interactive_prompt

            key_env = interactive_prompt(
                "  API key env var NAME, not the key itself (e.g. INFERENCE_HUB_KEY)",
                default="",
            )
            if key_env:
                ep["api_key_env"] = key_env

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
        print_success(f"Mode: private · Endpoint: {ep_url} · Model: {model_name}")

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
            )
        else:
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt("  Server URL")

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

        print_success(
            f"Mode: hybrid · Cloud: {cloud_model} · "
            f"Data agents: {private_model} via {ep_url}"
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





# ── Re-exports from sibling modules (Phase 8 split) ───────────────
# Importing these registers their @cli.command decorators and keeps
# the old import path working for cli.__init__ etc.
from urika.cli.config_notifications import notifications_command  # noqa: E402, F401
from urika.cli.config_setup import setup_command  # noqa: E402, F401
