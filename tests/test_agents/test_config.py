"""Tests for agent configuration and security policy."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy


class TestSecurityPolicyWriteAllowed:
    """Test is_write_allowed() — checks file paths against writable dirs."""

    def test_write_within_writable_dir(self, tmp_path: Path) -> None:
        writable = tmp_path / "methods"
        writable.mkdir()
        policy = SecurityPolicy(
            writable_dirs=[writable],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_write_allowed(writable / "model.py") is True

    def test_write_to_writable_dir_itself(self, tmp_path: Path) -> None:
        writable = tmp_path / "methods"
        writable.mkdir()
        policy = SecurityPolicy(
            writable_dirs=[writable],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_write_allowed(writable) is True

    def test_write_outside_writable_dir_denied(self, tmp_path: Path) -> None:
        writable = tmp_path / "methods"
        writable.mkdir()
        policy = SecurityPolicy(
            writable_dirs=[writable],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_write_allowed(tmp_path / "evaluation" / "file.py") is False

    def test_write_denied_when_no_writable_dirs(self, tmp_path: Path) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_write_allowed(tmp_path / "anything.py") is False

    def test_write_nested_subdir_allowed(self, tmp_path: Path) -> None:
        writable = tmp_path / "results"
        writable.mkdir()
        policy = SecurityPolicy(
            writable_dirs=[writable],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert (
            policy.is_write_allowed(writable / "sessions" / "001" / "progress.json")
            is True
        )

    def test_multiple_writable_dirs(self, tmp_path: Path) -> None:
        methods = tmp_path / "methods"
        results = tmp_path / "results"
        methods.mkdir()
        results.mkdir()
        policy = SecurityPolicy(
            writable_dirs=[methods, results],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_write_allowed(methods / "model.py") is True
        assert policy.is_write_allowed(results / "out.json") is True
        assert policy.is_write_allowed(tmp_path / "config" / "criteria.json") is False


class TestSecurityPolicyBashAllowed:
    """Test is_bash_allowed() — checks commands against prefixes and blocked patterns."""

    def test_allowed_prefix_matches(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=["python ", "pip "],
            blocked_bash_patterns=[],
        )
        assert policy.is_bash_allowed("python script.py") is True
        assert policy.is_bash_allowed("pip install numpy") is True

    def test_disallowed_prefix_denied(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=["python "],
            blocked_bash_patterns=[],
        )
        assert policy.is_bash_allowed("rm -rf /") is False

    def test_blocked_pattern_overrides_prefix(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=["python "],
            blocked_bash_patterns=["rm -rf"],
        )
        assert policy.is_bash_allowed("rm -rf /") is False

    def test_no_prefixes_allows_all_except_blocked(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=["rm -rf", "git push"],
        )
        assert policy.is_bash_allowed("ls -la") is True
        assert policy.is_bash_allowed("rm -rf /") is False
        assert policy.is_bash_allowed("git push --force") is False

    def test_empty_policy_allows_everything(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        assert policy.is_bash_allowed("anything") is True

    def test_command_stripped_before_check(self) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=["python "],
            blocked_bash_patterns=[],
        )
        assert policy.is_bash_allowed("  python script.py  ") is True


class TestAgentConfig:
    def test_create_with_required_fields(self, tmp_path: Path) -> None:
        policy = SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        )
        config = AgentConfig(
            name="test_agent",
            system_prompt="You are a test agent.",
            allowed_tools=["Read", "Glob"],
            disallowed_tools=[],
            security=policy,
        )
        assert config.name == "test_agent"
        assert config.max_turns == 50
        assert config.model is None
        assert config.cwd is None

    def test_create_with_all_fields(self, tmp_path: Path) -> None:
        policy = SecurityPolicy(
            writable_dirs=[tmp_path],
            readable_dirs=[tmp_path],
            allowed_bash_prefixes=["python "],
            blocked_bash_patterns=[],
        )
        config = AgentConfig(
            name="worker",
            system_prompt="Work prompt",
            allowed_tools=["Read", "Write", "Bash"],
            disallowed_tools=["Edit"],
            security=policy,
            max_turns=10,
            model="sonnet",
            cwd=tmp_path,
        )
        assert config.max_turns == 10
        assert config.model == "sonnet"
        assert config.cwd == tmp_path


class TestAgentRole:
    def test_create_role(self) -> None:
        def build(project_dir: Path, **kwargs: object) -> AgentConfig:
            return AgentConfig(
                name="test",
                system_prompt="prompt",
                allowed_tools=[],
                disallowed_tools=[],
                security=SecurityPolicy(
                    writable_dirs=[],
                    readable_dirs=[],
                    allowed_bash_prefixes=[],
                    blocked_bash_patterns=[],
                ),
            )

        role = AgentRole(
            name="test",
            description="A test role",
            build_config=build,
        )
        assert role.name == "test"
        assert role.description == "A test role"

    def test_build_config_callable(self, tmp_path: Path) -> None:
        def build(project_dir: Path, **kwargs: object) -> AgentConfig:
            return AgentConfig(
                name="worker",
                system_prompt=f"Working in {project_dir}",
                allowed_tools=["Read"],
                disallowed_tools=[],
                security=SecurityPolicy(
                    writable_dirs=[project_dir / "methods"],
                    readable_dirs=[project_dir],
                    allowed_bash_prefixes=[],
                    blocked_bash_patterns=[],
                ),
            )

        role = AgentRole(name="worker", description="Worker", build_config=build)
        config = role.build_config(tmp_path)
        assert config.name == "worker"
        assert f"{tmp_path}" in config.system_prompt
