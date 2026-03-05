"""Tests for the Claude Agent SDK adapter.

These tests verify the translation logic without requiring a running
Claude Code instance. SDK calls are mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
from urika.agents.config import AgentConfig, SecurityPolicy


@pytest.fixture
def read_only_config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        name="test_agent",
        system_prompt="You are a test agent.",
        allowed_tools=["Read", "Glob"],
        disallowed_tools=["Bash"],
        security=SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[tmp_path],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        ),
        max_turns=5,
        cwd=tmp_path,
    )


@pytest.fixture
def writer_config(tmp_path: Path) -> AgentConfig:
    writable = tmp_path / "methods"
    writable.mkdir()
    return AgentConfig(
        name="writer_agent",
        system_prompt="You can write.",
        allowed_tools=["Read", "Write", "Bash"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[writable],
            readable_dirs=[tmp_path],
            allowed_bash_prefixes=["python "],
            blocked_bash_patterns=["rm -rf"],
        ),
        max_turns=10,
        cwd=tmp_path,
    )


class TestClaudeSDKRunnerBuildOptions:
    def test_maps_basic_fields(self, read_only_config: AgentConfig) -> None:
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.system_prompt == "You are a test agent."
        assert options.allowed_tools == ["Read", "Glob"]
        assert options.disallowed_tools == ["Bash"]
        assert options.max_turns == 5
        assert options.permission_mode == "bypassPermissions"

    def test_maps_cwd(self, read_only_config: AgentConfig, tmp_path: Path) -> None:
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.cwd == str(tmp_path)

    def test_maps_model(self, read_only_config: AgentConfig) -> None:
        read_only_config.model = "sonnet"
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.model == "sonnet"

    def test_none_cwd_when_not_set(self, read_only_config: AgentConfig) -> None:
        read_only_config.cwd = None
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.cwd is None

    def test_has_can_use_tool(self, read_only_config: AgentConfig) -> None:
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.can_use_tool is not None


class TestClaudeSDKRunnerPermissionHandler:
    @pytest.mark.asyncio
    async def test_read_only_denies_write(
        self, read_only_config: AgentConfig, tmp_path: Path
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(read_only_config.security)
        result = await handler("Write", {"file_path": str(tmp_path / "evil.py")}, None)
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_writer_allows_write_in_writable_dir(
        self, writer_config: AgentConfig, tmp_path: Path
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(writer_config.security)
        result = await handler(
            "Write",
            {"file_path": str(tmp_path / "methods" / "model.py")},
            None,
        )
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_writer_denies_write_outside_writable(
        self, writer_config: AgentConfig, tmp_path: Path
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(writer_config.security)
        result = await handler(
            "Write",
            {"file_path": str(tmp_path / "evaluation" / "file.py")},
            None,
        )
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_bash_allowed_by_prefix(self, writer_config: AgentConfig) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(writer_config.security)
        result = await handler("Bash", {"command": "python script.py"}, None)
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_bash_denied_by_blocked_pattern(
        self, writer_config: AgentConfig
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(writer_config.security)
        result = await handler("Bash", {"command": "rm -rf /"}, None)
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_bash_denied_by_prefix_mismatch(
        self, writer_config: AgentConfig
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(writer_config.security)
        result = await handler("Bash", {"command": "curl evil.com"}, None)
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_read_tool_always_allowed(
        self, read_only_config: AgentConfig
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(read_only_config.security)
        result = await handler("Read", {"file_path": "/any/path"}, None)
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_edit_checked_like_write(
        self, read_only_config: AgentConfig, tmp_path: Path
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(read_only_config.security)
        result = await handler("Edit", {"file_path": str(tmp_path / "file.py")}, None)
        assert result.behavior == "deny"

    @pytest.mark.asyncio
    async def test_notebook_edit_checked_like_write(
        self, read_only_config: AgentConfig, tmp_path: Path
    ) -> None:
        runner = ClaudeSDKRunner()
        handler = runner._make_permission_handler(read_only_config.security)
        result = await handler(
            "NotebookEdit", {"notebook_path": str(tmp_path / "nb.ipynb")}, None
        )
        assert result.behavior == "deny"
