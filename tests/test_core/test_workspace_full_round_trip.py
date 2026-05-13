"""Full ``urika.toml`` round-trip across every section the project
ships with.

A regression in section ordering, key quoting, or the inline-table
encoder for a less-common section (e.g. ``[project.data_hashes]``
inline dict with file-path keys) would currently slip past
``test_workspace.py`` which only round-trips ``[project]`` +
``[preferences]``. This file constructs a project with EVERY section
populated and asserts ``tomllib.loads`` accepts what the writer
produced + round-trips the values.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from urika.core.workspace import _write_toml


def _full_config() -> dict:
    """A urika.toml with every section a real Urika project carries."""
    return {
        "project": {
            "name": "alpha",
            "question": 'Does "X" predict Y, over time?',
            "mode": "exploratory",
            "description": "Pasted from Word\r\nwith CRLF and a tab\there.",
            "audience": "expert",
            "data_paths": [
                "/abs/path/to/data.csv",
                "data/relative.csv",
            ],
            "data_hashes": {
                # Inline table with file-path keys (slashes + dots).
                "/abs/path/to/data.csv": "abc123" * 11,
                "data/relative.csv": "def456" * 11,
            },
        },
        "preferences": {
            "audience": "expert",
            "web_search": True,
            "presentation_theme": "light",
        },
        "data": {
            "source": "/abs/path/to/data",
            "format": "csv",
            "pattern": "**/*.csv",
        },
        "privacy": {
            "mode": "hybrid",
            "endpoints": {
                # Inline-table endpoint with embedded URL + key var.
                "private": {
                    "base_url": "https://vllm.example.com/v1",
                    "api_key_env": "VLLM_KEY",
                    "context_window": 32768,
                    "max_output_tokens": 8000,
                },
            },
        },
        "runtime": {
            "model": "claude-opus-4-6",
            "models": {
                # Per-agent overrides.
                "task_agent": {"model": "claude-haiku-4-5", "endpoint": "open"},
                "planning_agent": {"model": "claude-sonnet-4-5"},
            },
        },
        "environment": {"venv": True},
        "notifications": {
            "channels": ["email", "slack"],
        },
    }


def test_full_config_round_trips(tmp_path: Path) -> None:
    src = _full_config()
    path = tmp_path / "urika.toml"
    _write_toml(path, src)
    # Parse it back. Must not raise.
    loaded = tomllib.loads(path.read_text(encoding="utf-8"))

    # Per-section assertions — the values came back as written.
    assert loaded["project"]["name"] == "alpha"
    assert loaded["project"]["question"] == src["project"]["question"]
    assert loaded["project"]["description"] == src["project"]["description"]
    assert loaded["project"]["data_paths"] == src["project"]["data_paths"]
    assert loaded["project"]["data_hashes"] == src["project"]["data_hashes"]

    assert loaded["preferences"] == src["preferences"]

    assert loaded["data"] == src["data"]

    assert loaded["privacy"]["mode"] == "hybrid"
    assert loaded["privacy"]["endpoints"]["private"]["base_url"] == (
        "https://vllm.example.com/v1"
    )
    assert loaded["privacy"]["endpoints"]["private"]["api_key_env"] == "VLLM_KEY"
    assert loaded["privacy"]["endpoints"]["private"]["context_window"] == 32768

    assert loaded["runtime"]["model"] == "claude-opus-4-6"
    assert (
        loaded["runtime"]["models"]["task_agent"]["model"] == "claude-haiku-4-5"
    )
    assert loaded["runtime"]["models"]["task_agent"]["endpoint"] == "open"

    assert loaded["environment"]["venv"] is True

    assert loaded["notifications"]["channels"] == ["email", "slack"]


def test_round_trip_idempotent(tmp_path: Path) -> None:
    """Writing → reading → writing must produce the same bytes (no
    drift from section ordering changes)."""
    src = _full_config()
    p1 = tmp_path / "u1.toml"
    p2 = tmp_path / "u2.toml"
    _write_toml(p1, src)
    loaded = tomllib.loads(p1.read_text(encoding="utf-8"))
    _write_toml(p2, loaded)
    assert p1.read_text(encoding="utf-8") == p2.read_text(encoding="utf-8")


def test_inline_table_keys_with_slashes_quoted(tmp_path: Path) -> None:
    """``project.data_hashes`` keys are file paths — they contain
    slashes and dots which aren't valid TOML bare keys. The encoder
    must quote them."""
    data = {
        "project": {
            "name": "alpha",
            "data_hashes": {
                "data/x.csv": "abc",
                "data/sub/y.csv": "def",
                "with spaces.csv": "ghi",
            },
        }
    }
    path = tmp_path / "u.toml"
    _write_toml(path, data)
    # Reparses cleanly.
    loaded = tomllib.loads(path.read_text(encoding="utf-8"))
    assert loaded["project"]["data_hashes"] == data["project"]["data_hashes"]


def test_control_chars_in_strings_round_trip(tmp_path: Path) -> None:
    """The v0.4.4.1 fix already covers `\\r` etc. — this asserts the
    cross-section variant (control chars in arbitrary string fields)."""
    data = {
        "project": {
            "name": "x",
            "question": "with\r\nCRLF",
            "description": "\ttab and \x01 control",
        },
        "preferences": {
            "audience": "with \"quotes\" and \\backslashes",
        },
    }
    path = tmp_path / "u.toml"
    _write_toml(path, data)
    loaded = tomllib.loads(path.read_text(encoding="utf-8"))
    assert loaded["project"]["question"] == data["project"]["question"]
    assert loaded["project"]["description"] == data["project"]["description"]
    assert loaded["preferences"]["audience"] == data["preferences"]["audience"]
