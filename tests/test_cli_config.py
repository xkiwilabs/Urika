"""Tests for ``urika config`` writing per-mode storage globally.

The CLI used to write flat ``[runtime].model`` and
``[runtime.models.<agent>]`` to ``~/.urika/settings.toml``.  After the
Phase 12 redesign, globals store per-mode defaults under
``[runtime.modes.<mode>]`` instead.  Project-scoped writes still go to
flat ``[runtime].model`` / ``[runtime.models.<agent>]`` because a
project lives in exactly one mode.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


@pytest.fixture
def urika_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    return home


def test_global_open_writes_per_mode_default_model(urika_home, monkeypatch):
    """`urika config` (no project) for open mode writes
    [runtime.modes.open].model — not flat [runtime].model."""
    from urika.cli.config import _config_interactive

    seq = iter(
        [
            "open — agents use cloud models",
            "claude-sonnet-4-5 — best",
        ]
    )

    def fake_numbered(*args, **kwargs):
        return next(seq)

    monkeypatch.setattr(
        "urika.cli_helpers.interactive_numbered", fake_numbered
    )

    settings: dict = {}
    _config_interactive(
        session=settings,
        current_mode="open",
        is_project=False,
        project_path=None,
    )

    s = tomllib.loads((urika_home / "settings.toml").read_text())
    assert s["runtime"]["modes"]["open"]["model"] == "claude-sonnet-4-5"
    # Flat top-level [runtime].model is NOT used for global writes.
    assert "model" not in s.get("runtime", {})


def test_global_hybrid_writes_per_mode_per_agent(urika_home, monkeypatch):
    """Hybrid global config writes per-agent overrides under
    [runtime.modes.hybrid.models.<agent>] and forces both data_agent
    and tool_builder to private."""
    from urika.cli.config import _config_interactive

    nums = iter(
        [
            "hybrid — most agents use Claude API",
            "claude-sonnet-4-5 — best",
            "Ollama (localhost:11434)",
        ]
    )

    def fake_numbered(*args, **kwargs):
        return next(nums)

    prompts = iter(["qwen3:14b"])

    def fake_prompt(*args, **kwargs):
        return next(prompts)

    monkeypatch.setattr(
        "urika.cli_helpers.interactive_numbered", fake_numbered
    )
    monkeypatch.setattr(
        "urika.cli_helpers.interactive_prompt", fake_prompt
    )

    settings: dict = {}
    _config_interactive(
        session=settings,
        current_mode="hybrid",
        is_project=False,
        project_path=None,
    )

    s = tomllib.loads((urika_home / "settings.toml").read_text())
    hybrid = s["runtime"]["modes"]["hybrid"]
    assert hybrid["model"] == "claude-sonnet-4-5"
    assert hybrid["models"]["data_agent"]["model"] == "qwen3:14b"
    assert hybrid["models"]["data_agent"]["endpoint"] == "private"
    assert hybrid["models"]["tool_builder"]["model"] == "qwen3:14b"
    assert hybrid["models"]["tool_builder"]["endpoint"] == "private"


def test_project_scoped_config_still_uses_flat_keys(
    urika_home, monkeypatch, tmp_path
):
    """Project-scoped `urika config <project>` keeps writing flat
    [privacy].mode + [runtime].model — a project lives in one mode."""
    from urika.cli.config import _config_interactive
    from urika.core.workspace import _write_toml

    proj = tmp_path / "proj"
    proj.mkdir()
    _write_toml(
        proj / "urika.toml",
        {"project": {"name": "proj", "question": "q", "mode": "exploratory"}},
    )

    seq = iter(
        [
            "open — agents use cloud models",
            "claude-sonnet-4-5 — best",
        ]
    )

    def fake_numbered(*args, **kwargs):
        return next(seq)

    monkeypatch.setattr(
        "urika.cli_helpers.interactive_numbered", fake_numbered
    )

    settings: dict = {"project": {"name": "proj"}}
    _config_interactive(
        session=settings,
        current_mode="open",
        is_project=True,
        project_path=proj,
    )

    s = tomllib.loads((proj / "urika.toml").read_text())
    assert s["privacy"]["mode"] == "open"
    assert s["runtime"]["model"] == "claude-sonnet-4-5"
    assert "modes" not in s.get("runtime", {})


# ---- Paired key-name + value prompt --------------------------------------
# Parity with the dashboard's name+value flow (Phase B+ UX overhaul):
# after the user enters an env-var name for an endpoint API key, the CLI
# also prompts for the value and saves it to the secrets vault.


def test_prompt_for_endpoint_key_value_writes_to_vault(urika_home, monkeypatch):
    """A non-empty value passes through to ``vault.set_global``."""
    from urika.cli.config import _prompt_for_endpoint_key_value

    monkeypatch.setattr(
        "click.prompt", lambda *a, **kw: "sk-test-12345-padding-ok"
    )

    _prompt_for_endpoint_key_value("TEST_PRIVATE_KEY")

    secrets_env = (urika_home / "secrets.env").read_text()
    assert "TEST_PRIVATE_KEY=sk-test-12345-padding-ok" in secrets_env


def test_prompt_for_endpoint_key_value_blank_skips_vault(urika_home, monkeypatch):
    """Blank value = user already has it in the shell; no vault write."""
    from urika.cli.config import _prompt_for_endpoint_key_value

    monkeypatch.setattr("click.prompt", lambda *a, **kw: "")

    _prompt_for_endpoint_key_value("ANOTHER_KEY")

    # secrets.env shouldn't carry an entry for that name.
    secrets_path = urika_home / "secrets.env"
    if secrets_path.exists():
        assert "ANOTHER_KEY" not in secrets_path.read_text()


def test_prompt_for_endpoint_key_value_handles_abort(urika_home, monkeypatch):
    """Ctrl-C / EOF during the value prompt is logged but not fatal."""
    from urika.cli.config import _prompt_for_endpoint_key_value

    def _abort(*a, **kw):
        raise click.Abort()

    import click

    monkeypatch.setattr("click.prompt", _abort)
    # Should NOT raise — the helper swallows the abort.
    _prompt_for_endpoint_key_value("CANCELLED_KEY")
    secrets_path = urika_home / "secrets.env"
    if secrets_path.exists():
        assert "CANCELLED_KEY" not in secrets_path.read_text()


def test_global_hybrid_prompts_for_endpoint_key_value(urika_home, monkeypatch):
    """End-to-end: hybrid mode setup with a remote private endpoint
    asks for both the env-var name AND the value."""
    from urika.cli.config import _config_interactive

    nums = iter(
        [
            "hybrid — most agents use Claude API",
            "claude-sonnet-4-5 — best",
            "Custom server URL",  # forces remote URL, triggers key prompt
        ]
    )

    def fake_numbered(*args, **kwargs):
        return next(nums)

    # Sequence of interactive_prompt calls: server URL, key env name,
    # private model (in that order, as written in the hybrid branch).
    prompts = iter(
        [
            "https://my-llm.example.com",
            "MY_PRIVATE_KEY",
            "qwen3:14b",
        ]
    )

    def fake_prompt(*args, **kwargs):
        return next(prompts)

    # The masked value prompt goes through click.prompt directly.
    monkeypatch.setattr("click.prompt", lambda *a, **kw: "sk-private-value-padding")
    monkeypatch.setattr(
        "urika.cli_helpers.interactive_numbered", fake_numbered
    )
    monkeypatch.setattr(
        "urika.cli_helpers.interactive_prompt", fake_prompt
    )

    settings: dict = {}
    _config_interactive(
        session=settings,
        current_mode="hybrid",
        is_project=False,
        project_path=None,
    )

    # settings.toml: env-var name only.
    s = tomllib.loads((urika_home / "settings.toml").read_text())
    ep = s["privacy"]["endpoints"]["private"]
    assert ep["api_key_env"] == "MY_PRIVATE_KEY"
    assert "sk-private-value-padding" not in (urika_home / "settings.toml").read_text()

    # secrets.env: value lands here.
    secrets_env = (urika_home / "secrets.env").read_text()
    assert "MY_PRIVATE_KEY=sk-private-value-padding" in secrets_env
