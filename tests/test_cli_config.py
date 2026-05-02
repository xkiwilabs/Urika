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


def test_global_open_opus_applies_reasoning_execution_split(urika_home, monkeypatch):
    """When the user picks Opus as the open-mode default, the wizard
    auto-writes a per-agent split: reasoning agents on Opus,
    execution agents on Sonnet 4.5. Saves ~5x per execution call
    with no quality impact (Sonnet is indistinguishable on
    "execute this plan" / "format these numbers" tasks).
    """
    from urika.cli.config import _config_interactive, _EXECUTION_AGENT_DEFAULT_MODEL

    seq = iter(
        [
            "open — agents use cloud models",
            "claude-opus-4-6 — most capable",
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
    open_mode = s["runtime"]["modes"]["open"]
    # The "default model" still records Opus — that's what gets
    # used for any agent without an explicit override.
    assert open_mode["model"] == "claude-opus-4-6"
    # Reasoning agents got explicit Opus pins.
    for agent in ("planning_agent", "advisor_agent", "finalizer", "project_builder"):
        assert open_mode["models"][agent]["model"] == "claude-opus-4-6"
        assert open_mode["models"][agent]["endpoint"] == "open"
    # Execution agents got the cheaper tier.
    for agent in (
        "task_agent", "evaluator", "report_agent", "presentation_agent",
        "tool_builder", "literature_agent", "data_agent", "project_summarizer",
    ):
        assert open_mode["models"][agent]["model"] == _EXECUTION_AGENT_DEFAULT_MODEL
        assert open_mode["models"][agent]["endpoint"] == "open"


def test_global_open_sonnet_skips_split(urika_home, monkeypatch):
    """When the user picks Sonnet as the default, no split is
    needed — everything's already at the cheaper tier. The wizard
    writes only the [runtime.modes.open].model field, no per-agent
    overrides.
    """
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
    open_mode = s["runtime"]["modes"]["open"]
    assert open_mode["model"] == "claude-sonnet-4-5"
    # No split applied — Sonnet is already the execution-tier default,
    # so per-agent overrides would just be noise.
    assert "models" not in open_mode


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


# ── --reset-models flag ──────────────────────────────────────────────


def test_reset_models_global_opus_writes_split(urika_home, monkeypatch):
    """`urika config --reset-models` rebuilds the per-agent split for
    every mode whose default model is Opus. Pre-existing custom
    overrides are dropped (idempotent: running twice produces the
    same file).
    """
    from click.testing import CliRunner

    from urika.cli import cli

    # Seed a global settings.toml with an Opus open default and a
    # bunch of stale per-agent pinning that pre-dates the split.
    (urika_home / "settings.toml").write_text(
        """[runtime.modes.open]
model = "claude-opus-4-6"

[runtime.modes.open.models.task_agent]
model = "claude-opus-4-6"
endpoint = "open"

[runtime.modes.open.models.advisor_agent]
model = "claude-opus-4-6"
endpoint = "open"

[runtime.modes.open.models.report_agent]
model = "claude-haiku-4-5"
endpoint = "open"
"""
    )

    result = CliRunner().invoke(cli, ["config", "--reset-models"])
    assert result.exit_code == 0, result.output
    assert "open" in result.output

    s = tomllib.loads((urika_home / "settings.toml").read_text())
    open_mode = s["runtime"]["modes"]["open"]
    assert open_mode["model"] == "claude-opus-4-6"
    # Reasoning agents pinned to the configured default.
    for agent in ("planning_agent", "advisor_agent", "finalizer", "project_builder"):
        assert open_mode["models"][agent]["model"] == "claude-opus-4-6"
        assert open_mode["models"][agent]["endpoint"] == "open"
    # Execution agents pinned to the cheaper tier.
    for agent in ("task_agent", "evaluator", "report_agent", "presentation_agent",
                  "tool_builder", "literature_agent", "data_agent",
                  "project_summarizer"):
        assert open_mode["models"][agent]["model"] == "claude-sonnet-4-5"
        assert open_mode["models"][agent]["endpoint"] == "open"

    # Idempotent — second run produces the same file.
    before = (urika_home / "settings.toml").read_text()
    result2 = CliRunner().invoke(cli, ["config", "--reset-models"])
    assert result2.exit_code == 0
    after = (urika_home / "settings.toml").read_text()
    assert before == after


def test_reset_models_global_sonnet_clears_overrides(urika_home, monkeypatch):
    """When the mode default is already Sonnet, the split is a no-op
    and any leftover per-agent overrides are dropped (they would
    just be noise — the runtime falls back to the mode default).
    """
    from click.testing import CliRunner

    from urika.cli import cli

    (urika_home / "settings.toml").write_text(
        """[runtime.modes.open]
model = "claude-sonnet-4-5"

[runtime.modes.open.models.task_agent]
model = "claude-haiku-4-5"
endpoint = "open"
"""
    )

    result = CliRunner().invoke(cli, ["config", "--reset-models"])
    assert result.exit_code == 0, result.output

    s = tomllib.loads((urika_home / "settings.toml").read_text())
    open_mode = s["runtime"]["modes"]["open"]
    assert open_mode["model"] == "claude-sonnet-4-5"
    # No per-agent block — the leftover task_agent override is gone.
    assert "models" not in open_mode


def test_reset_models_global_hybrid_preserves_private_pins(urika_home, monkeypatch):
    """Hybrid mode's data_agent + tool_builder private-endpoint pins
    are preserved across a reset — the rebuild puts cloud-Sonnet
    placeholders for execution agents, then overrides those two
    with the carried-forward private assignment.
    """
    from click.testing import CliRunner

    from urika.cli import cli

    (urika_home / "settings.toml").write_text(
        """[runtime.modes.hybrid]
model = "claude-opus-4-6"

[runtime.modes.hybrid.models.data_agent]
model = "qwen3:14b"
endpoint = "private"

[runtime.modes.hybrid.models.tool_builder]
model = "qwen3:14b"
endpoint = "private"
"""
    )

    result = CliRunner().invoke(cli, ["config", "--reset-models"])
    assert result.exit_code == 0, result.output

    s = tomllib.loads((urika_home / "settings.toml").read_text())
    hybrid = s["runtime"]["modes"]["hybrid"]
    assert hybrid["model"] == "claude-opus-4-6"
    # Reasoning + cloud-execution split applied.
    assert hybrid["models"]["planning_agent"]["model"] == "claude-opus-4-6"
    assert hybrid["models"]["task_agent"]["model"] == "claude-sonnet-4-5"
    # Private pins survived the rebuild.
    assert hybrid["models"]["data_agent"]["model"] == "qwen3:14b"
    assert hybrid["models"]["data_agent"]["endpoint"] == "private"
    assert hybrid["models"]["tool_builder"]["model"] == "qwen3:14b"
    assert hybrid["models"]["tool_builder"]["endpoint"] == "private"


def test_reset_models_project_scope(urika_home, monkeypatch, tmp_path):
    """`urika config <project> --reset-models` rebuilds the project's
    own urika.toml under the flat [runtime] / [runtime.models.*]
    keys.
    """
    from click.testing import CliRunner

    from urika.cli import cli

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "urika.toml").write_text(
        """[project]
name = "my-proj"
question = "?"
mode = "exploratory"

[privacy]
mode = "open"

[runtime]
model = "claude-opus-4-6"

[runtime.models.task_agent]
model = "claude-opus-4-6"
endpoint = "open"
"""
    )

    monkeypatch.setattr(
        "urika.cli.config._resolve_project",
        lambda name: (project_dir, None),
    )

    result = CliRunner().invoke(cli, ["config", "my-proj", "--reset-models"])
    assert result.exit_code == 0, result.output

    s = tomllib.loads((project_dir / "urika.toml").read_text())
    assert s["runtime"]["model"] == "claude-opus-4-6"
    assert s["runtime"]["models"]["task_agent"]["model"] == "claude-sonnet-4-5"
    assert s["runtime"]["models"]["planning_agent"]["model"] == "claude-opus-4-6"
