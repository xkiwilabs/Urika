"""Tests for ``load_runtime_config`` global per-mode fallback.

The loader reads project-level ``urika.toml`` first, then merges in
``[runtime.modes.<project_mode>]`` from ``~/.urika/settings.toml`` so
projects pick up live-inherited defaults without copying them at
creation time.  Project-level overrides always win.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def urika_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    return home


def _write_project(project_dir: Path, body: str) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "urika.toml").write_text(body, encoding="utf-8")


def _write_settings(home: Path, body: str) -> None:
    (home / "settings.toml").write_text(body, encoding="utf-8")


def test_global_per_mode_fills_gap_when_project_lacks_override(
    urika_home, tmp_path
):
    """Project has mode=private but no per-agent overrides; globals
    define [runtime.modes.private.models.task_agent].model — loader
    surfaces the global value on the merged config."""
    from urika.agents.config import load_runtime_config

    _write_settings(
        urika_home,
        '[runtime.modes.private.models.task_agent]\n'
        'model = "qwen3:14b"\n'
        'endpoint = "private"\n',
    )
    proj = tmp_path / "p"
    _write_project(
        proj,
        '[privacy]\nmode = "private"\n'
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n',
    )

    rc = load_runtime_config(proj)
    assert rc.privacy_mode == "private"
    assert "task_agent" in rc.model_overrides
    assert rc.model_overrides["task_agent"].model == "qwen3:14b"
    assert rc.model_overrides["task_agent"].endpoint == "private"


def test_project_runtime_model_wins_over_global_per_mode(
    urika_home, tmp_path
):
    """[runtime].model in the project's urika.toml wins over the
    globals' [runtime.modes.<mode>].model fallback."""
    from urika.agents.config import load_runtime_config

    _write_settings(
        urika_home,
        '[runtime.modes.open]\nmodel = "Y"\n',
    )
    proj = tmp_path / "p"
    _write_project(
        proj,
        '[privacy]\nmode = "open"\n'
        '[runtime]\nmodel = "X"\n',
    )

    rc = load_runtime_config(proj)
    assert rc.model == "X"


def test_project_per_agent_override_wins_over_global_per_mode(
    urika_home, tmp_path
):
    """[runtime.models.task_agent] in the project wins over the
    globals' [runtime.modes.<mode>.models.task_agent] fallback."""
    from urika.agents.config import load_runtime_config

    _write_settings(
        urika_home,
        '[runtime.modes.open.models.task_agent]\nmodel = "Y"\n',
    )
    proj = tmp_path / "p"
    _write_project(
        proj,
        '[privacy]\nmode = "open"\n'
        '[runtime.models.task_agent]\nmodel = "X"\n',
    )

    rc = load_runtime_config(proj)
    assert rc.model_overrides["task_agent"].model == "X"


def test_global_per_mode_default_model_falls_through(
    urika_home, tmp_path
):
    """Global [runtime.modes.<mode>].model fills in [runtime].model
    when the project doesn't set one."""
    from urika.agents.config import load_runtime_config

    _write_settings(
        urika_home,
        '[runtime.modes.private]\nmodel = "qwen3:14b"\n',
    )
    proj = tmp_path / "p"
    _write_project(
        proj,
        '[privacy]\nmode = "private"\n'
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n',
    )

    rc = load_runtime_config(proj)
    assert rc.model == "qwen3:14b"


def test_no_global_block_falls_back_to_built_in_defaults(
    urika_home, tmp_path
):
    """If globals have no [runtime.modes.<mode>] block, the loader
    silently keeps the project's own values (or built-in defaults).
    No errors."""
    from urika.agents.config import load_runtime_config

    # No settings.toml at all
    proj = tmp_path / "p"
    _write_project(
        proj,
        '[privacy]\nmode = "open"\n',
    )

    rc = load_runtime_config(proj)
    assert rc.privacy_mode == "open"
    assert rc.model == ""  # built-in default
    assert rc.model_overrides == {}


def test_global_settings_for_other_mode_does_not_leak(
    urika_home, tmp_path
):
    """A global [runtime.modes.private.*] block must not affect a
    project whose mode is 'open'."""
    from urika.agents.config import load_runtime_config

    _write_settings(
        urika_home,
        '[runtime.modes.private]\nmodel = "qwen3:14b"\n'
        '[runtime.modes.private.models.task_agent]\nmodel = "qwen3-coder"\n',
    )
    proj = tmp_path / "p"
    _write_project(
        proj,
        '[privacy]\nmode = "open"\n',
    )

    rc = load_runtime_config(proj)
    assert rc.model == ""
    assert rc.model_overrides == {}


def test_unparseable_settings_file_does_not_break_loader(
    urika_home, tmp_path
):
    """A malformed settings.toml is silently ignored; loader returns
    project-level config unchanged."""
    from urika.agents.config import load_runtime_config

    (urika_home / "settings.toml").write_text(
        "this is not valid toml [[[\n", encoding="utf-8"
    )
    proj = tmp_path / "p"
    _write_project(
        proj,
        '[privacy]\nmode = "open"\n'
        '[runtime]\nmodel = "X"\n',
    )

    rc = load_runtime_config(proj)
    assert rc.model == "X"


# ---- Endpoint inheritance from globals ------------------------------------


def test_load_runtime_config_inherits_global_endpoints(urika_home, tmp_path):
    """Project mode=private with no project-level [privacy.endpoints]; the
    loader pulls the endpoint from globals' [privacy.endpoints.private]
    so the runtime can dispatch a private agent without crashing."""
    from urika.agents.config import load_runtime_config

    _write_settings(
        urika_home,
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n',
    )
    proj = tmp_path / "p"
    _write_project(
        proj,
        '[privacy]\nmode = "private"\n',
    )

    rc = load_runtime_config(proj)
    assert rc.privacy_mode == "private"
    assert "private" in rc.endpoints
    assert rc.endpoints["private"].base_url == "http://localhost:11434"


def test_load_runtime_config_project_endpoint_wins_over_global(
    urika_home, tmp_path
):
    """When both project and globals define [privacy.endpoints.private],
    the project's value wins on collision — same precedence rule as the
    per-mode model overrides."""
    from urika.agents.config import load_runtime_config

    _write_settings(
        urika_home,
        '[privacy.endpoints.private]\n'
        'base_url = "http://global.example/inference"\n',
    )
    proj = tmp_path / "p"
    _write_project(
        proj,
        '[privacy]\nmode = "private"\n'
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n',
    )

    rc = load_runtime_config(proj)
    assert rc.endpoints["private"].base_url == "http://localhost:11434"


def test_load_runtime_config_global_endpoints_no_project_block(
    urika_home, tmp_path
):
    """Project urika.toml has no [privacy.endpoints] subblock — only
    [privacy].mode = "private". Global endpoints still surface so the
    runtime can dispatch without falling back to cloud."""
    from urika.agents.config import load_runtime_config

    _write_settings(
        urika_home,
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n',
    )
    proj = tmp_path / "p"
    # Mode set, but no [privacy.endpoints] subblock at all.
    _write_project(
        proj,
        '[privacy]\nmode = "private"\n',
    )

    rc = load_runtime_config(proj)
    assert rc.privacy_mode == "private"
    assert rc.endpoints["private"].base_url == "http://localhost:11434"


def test_load_runtime_config_inherits_multiple_global_endpoints(
    urika_home, tmp_path
):
    """All names defined in globals' [privacy.endpoints.*] surface on
    the project's RuntimeConfig.endpoints — multiple names, not just
    'private'."""
    from urika.agents.config import load_runtime_config

    _write_settings(
        urika_home,
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        '[privacy.endpoints.vllm]\n'
        'base_url = "http://gpu.local:4200"\n',
    )
    proj = tmp_path / "p"
    _write_project(
        proj,
        '[privacy]\nmode = "private"\n',
    )

    rc = load_runtime_config(proj)
    assert rc.endpoints["private"].base_url == "http://localhost:11434"
    assert rc.endpoints["vllm"].base_url == "http://gpu.local:4200"
