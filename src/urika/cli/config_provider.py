"""``urika config anthropic|openai|google`` — provider auth setup (v0.7.0 Task 4.2).

These three subcommands let users explicitly select the auth mode for each
cloud LLM provider, writing a single key under the matching TOML section in
``~/.urika/settings.toml``:

* ``[anthropic] auth = "api_key" | "subscription"`` — consumed by
  :func:`urika.core.compliance._get_anthropic_auth_preference` (Task 4.1).
* ``[openai] auth = "api_key"`` — subscription mode is rejected up-front
  (OpenAI Plus is a separate product from the API).
* ``[google] auth = "api_key"`` — subscription mode is rejected up-front
  (Google AI Pro/Ultra ToS forbid third-party SDK use).

The Anthropic subscription path additionally probes ``claude --version`` so
the user gets immediate feedback if the local Claude CLI isn't on PATH;
``--no-verify`` skips that probe (used by post-install bootstrap scripts).

Wired into the existing ``urika config`` command (which is a single
positional-arg-dispatch ``@cli.command``, not a ``click.Group``) via
pseudo-project routing inside :func:`urika.cli.config.config_command` so
``urika config anthropic --mode subscription`` Just Works without changing
the existing ``urika config <project>``, ``urika config api-key``, or
``urika config secret`` surfaces.
"""

from __future__ import annotations

import subprocess

import click

from urika.core.settings import load_settings, save_settings


# Recognised provider names — anything else is a normal project name and
# falls through to the existing project-config dispatch.
PROVIDER_NAMES: frozenset[str] = frozenset({"anthropic", "openai", "google"})


# How long to wait for ``claude --version`` before giving up. Subscription
# verification is a courtesy probe; if the user's PATH is misconfigured we
# don't want to block the wizard for the full default subprocess timeout.
_CLAUDE_PROBE_TIMEOUT_SECONDS = 5


def _write_provider_auth(provider: str, mode: str) -> None:
    """Merge ``[<provider>] auth = "<mode>"`` into ``~/.urika/settings.toml``.

    Loads existing settings first so unrelated sections (``[preferences]``,
    ``[runtime]``, ``[privacy]``, etc.) are preserved verbatim. The minimal
    TOML writer in :mod:`urika.core.workspace` re-serialises every section,
    so reading-then-writing the full dict is the safe way to add one key
    without touching the rest of the file.
    """
    data = load_settings()
    section = data.get(provider)
    if not isinstance(section, dict):
        section = {}
    section["auth"] = mode
    data[provider] = section
    save_settings(data)


def _verify_claude_cli_present() -> None:
    """Probe ``claude --version`` and print a stderr warning if it fails.

    Never raises — the setting has already been written by the time we get
    here, and a missing ``claude`` CLI is a soft failure (the user might
    intend to install it next). All exit paths return cleanly so the
    surrounding command exits 0.
    """
    try:
        proc = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_CLAUDE_PROBE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        click.echo(
            "  warning: `claude` CLI not found on PATH — install per "
            "Anthropic's docs before running experiments.",
            err=True,
        )
        return
    except subprocess.TimeoutExpired:
        click.echo(
            "  warning: `claude --version` timed out — the local Claude "
            "CLI may be hung or unreachable.",
            err=True,
        )
        return
    except OSError as exc:
        click.echo(
            f"  warning: `claude --version` failed to launch: {exc}",
            err=True,
        )
        return

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip() or "(no stderr)"
        click.echo(
            f"  warning: `claude --version` returned exit {proc.returncode}: {stderr}",
            err=True,
        )


def run_config_anthropic(mode: str, no_verify: bool) -> None:
    """Implement ``urika config anthropic --mode {api_key|subscription} [--no-verify]``.

    Side-effects:
      * writes ``[anthropic] auth = "<mode>"`` to ``~/.urika/settings.toml``
      * prints a next-steps hint to stdout
      * when ``mode == "subscription"`` and ``not no_verify``, probes
        ``claude --version`` and emits a stderr warning if absent
    """
    _write_provider_auth("anthropic", mode)
    if mode == "subscription":
        click.echo(
            "Anthropic subscription mode enabled. Run `claude login` in your "
            "terminal to authenticate the local Claude CLI before running "
            "experiments."
        )
        if not no_verify:
            _verify_claude_cli_present()
    else:
        click.echo(
            "Anthropic API-key mode set. Ensure ANTHROPIC_API_KEY is "
            "configured (use `urika config api-key`)."
        )


def run_config_openai(mode: str) -> None:
    """Implement ``urika config openai --mode {api_key|subscription}``.

    Subscription mode is rejected (OpenAI Plus is not the API). API-key
    mode writes ``[openai] auth = "api_key"`` and prints a hint pointing
    at the secrets-vault entry name agents will look up at runtime.
    """
    if mode == "subscription":
        raise click.UsageError(
            "OpenAI Plus subscriptions cannot be used with Urika. OpenAI's "
            "API key is a separate product — get one at "
            "https://platform.openai.com/api-keys and re-run with "
            "`--mode api_key`."
        )
    _write_provider_auth("openai", "api_key")
    click.echo(
        "OpenAI API-key mode set. Store your key with "
        "`urika config api-key OPENAI_API_KEY` (or export it in your shell)."
    )


def run_config_google(mode: str) -> None:
    """Implement ``urika config google --mode {api_key|subscription}``.

    Subscription mode is rejected — Google AI Pro/Ultra Terms of Service
    forbid third-party SDK use; only the Gemini API key path is supported.
    API-key mode writes ``[google] auth = "api_key"`` and surfaces the
    expected env-var name (``GEMINI_API_KEY``).
    """
    if mode == "subscription":
        raise click.UsageError(
            "Google AI Pro/Ultra subscriptions cannot be used with Urika — "
            "Google's Terms of Service forbid third-party use. Get a Gemini "
            "API key from https://aistudio.google.com/app/apikey and re-run "
            "with `--mode api_key`."
        )
    _write_provider_auth("google", "api_key")
    click.echo(
        "Google API-key mode set. Store your key with "
        "`urika config api-key GEMINI_API_KEY` (or export it in your shell)."
    )
