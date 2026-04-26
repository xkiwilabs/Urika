"""Tests for hybrid-mode forced-private agents.

In hybrid mode the data_agent + tool_builder agents must run against
the private endpoint by default — they handle data and project-private
code generation, so the cloud cannot see them.  Other agents are free
to use the cloud unless individually overridden in urika.toml.
"""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import (
    EndpointConfig,
    RuntimeConfig,
    build_agent_env_for_endpoint,
)


def test_hybrid_mode_forces_tool_builder_private(tmp_path: Path) -> None:
    """In hybrid mode, tool_builder defaults to the private endpoint
    (matches data_agent's existing behavior)."""
    rc = RuntimeConfig(
        privacy_mode="hybrid",
        endpoints={
            "private": EndpointConfig(base_url="http://localhost:11434"),
        },
    )
    env = build_agent_env_for_endpoint(tmp_path, "tool_builder", rc)
    assert env is not None
    assert env.get("ANTHROPIC_BASE_URL") == "http://localhost:11434"


def test_hybrid_mode_data_agent_still_private(tmp_path: Path) -> None:
    """data_agent retains its forced-private endpoint in hybrid mode."""
    rc = RuntimeConfig(
        privacy_mode="hybrid",
        endpoints={
            "private": EndpointConfig(base_url="http://localhost:11434"),
        },
    )
    env = build_agent_env_for_endpoint(tmp_path, "data_agent", rc)
    assert env is not None
    assert env.get("ANTHROPIC_BASE_URL") == "http://localhost:11434"


def test_hybrid_mode_other_agent_remains_open(tmp_path: Path) -> None:
    """Agents outside the forced set use the cloud endpoint by default
    in hybrid mode."""
    rc = RuntimeConfig(
        privacy_mode="hybrid",
        endpoints={
            "private": EndpointConfig(base_url="http://localhost:11434"),
        },
    )
    env = build_agent_env_for_endpoint(tmp_path, "task_agent", rc)
    # No private endpoint forced → either env is None (no venv) or it
    # doesn't carry ANTHROPIC_BASE_URL.
    if env is not None:
        assert env.get("ANTHROPIC_BASE_URL") != "http://localhost:11434"


def test_open_mode_tool_builder_not_forced_private(tmp_path: Path) -> None:
    """In open mode, tool_builder does NOT route to the private endpoint."""
    rc = RuntimeConfig(
        privacy_mode="open",
        endpoints={
            "private": EndpointConfig(base_url="http://localhost:11434"),
        },
    )
    env = build_agent_env_for_endpoint(tmp_path, "tool_builder", rc)
    if env is not None:
        assert env.get("ANTHROPIC_BASE_URL") != "http://localhost:11434"
