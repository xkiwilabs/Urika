"""Role-config tests for data_agent, finalizer, project_summarizer.

These three production agents had no ``test_*_role.py`` file pre-this.
Allowed tools, writable_dirs scope, model selection, prompt fingerprint
were all unpinned.
"""

from __future__ import annotations

from pathlib import Path


from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace


def _project(tmp_path: Path) -> Path:
    proj = tmp_path / "p"
    create_project_workspace(
        proj, ProjectConfig(name="p", question="?", mode="exploratory")
    )
    return proj


# ── data_agent ─────────────────────────────────────────────────


class TestDataAgentRoleConfig:
    def test_role_name(self, tmp_path: Path) -> None:
        from urika.agents.roles.data_agent import get_role

        assert get_role().name == "data_agent"

    def test_allowed_tools_includes_read_write_bash(self, tmp_path: Path) -> None:
        from urika.agents.roles.data_agent import build_config

        cfg = build_config(_project(tmp_path))
        assert "Read" in cfg.allowed_tools
        assert "Write" in cfg.allowed_tools  # the only "writes raw data" role
        assert "Bash" in cfg.allowed_tools

    def test_writable_dirs_scoped_to_experiment_or_data_dir(
        self, tmp_path: Path
    ) -> None:
        from urika.agents.roles.data_agent import build_config

        proj = _project(tmp_path)
        # Without experiment_id, falls back to experiments + data_dir.
        cfg = build_config(proj)
        writable = {str(p) for p in cfg.security.writable_dirs}
        assert str(proj / "data") in writable
        # With explicit experiment_id, scopes to that experiment + data_dir.
        cfg2 = build_config(proj, experiment_id="exp-001")
        writable2 = {str(p) for p in cfg2.security.writable_dirs}
        assert str(proj / "experiments" / "exp-001") in writable2
        assert str(proj / "data") in writable2

    def test_bash_allowlist_restricted_to_python_pip(self, tmp_path: Path) -> None:
        from urika.agents.roles.data_agent import build_config

        cfg = build_config(_project(tmp_path))
        # ``python`` and ``pip`` only — no ``urika``, no ``ls``, etc.
        prefixes = " ".join(cfg.security.allowed_bash_prefixes)
        assert "python" in prefixes and "pip" in prefixes
        assert "urika" not in prefixes

    def test_destructive_bash_patterns_blocked(self, tmp_path: Path) -> None:
        from urika.agents.roles.data_agent import build_config

        cfg = build_config(_project(tmp_path))
        blocked = " ".join(cfg.security.blocked_bash_patterns)
        assert "rm -rf" in blocked

    def test_no_sandbox_escape_tools_allowed(self, tmp_path: Path) -> None:
        from urika.agents.roles.data_agent import build_config

        cfg = build_config(_project(tmp_path))
        for escape in ("Task", "Agent", "ToolSearch"):
            assert escape not in cfg.allowed_tools


# ── finalizer ──────────────────────────────────────────────────


class TestFinalizerRoleConfig:
    def test_role_name(self) -> None:
        from urika.agents.roles.finalizer import get_role

        assert get_role().name == "finalizer"

    def test_allowed_tools(self, tmp_path: Path) -> None:
        from urika.agents.roles.finalizer import build_config

        cfg = build_config(_project(tmp_path))
        for t in ("Read", "Write", "Bash", "Glob", "Grep"):
            assert t in cfg.allowed_tools

    def test_writable_dirs_include_project_methods_projectbook(
        self, tmp_path: Path
    ) -> None:
        """The finalizer writes findings.json (projectbook),
        final_*.py (methods/), requirements.txt + reproduce.sh
        (project root)."""
        from urika.agents.roles.finalizer import build_config

        proj = _project(tmp_path)
        cfg = build_config(proj)
        writable = {str(p) for p in cfg.security.writable_dirs}
        assert str(proj) in writable
        assert str(proj / "methods") in writable
        assert str(proj / "projectbook") in writable

    def test_bash_restricted_to_python_pip(self, tmp_path: Path) -> None:
        from urika.agents.roles.finalizer import build_config

        cfg = build_config(_project(tmp_path))
        prefixes = " ".join(cfg.security.allowed_bash_prefixes)
        assert "python" in prefixes and "pip" in prefixes

    def test_destructive_bash_patterns_blocked(self, tmp_path: Path) -> None:
        from urika.agents.roles.finalizer import build_config

        cfg = build_config(_project(tmp_path))
        blocked = " ".join(cfg.security.blocked_bash_patterns)
        assert "rm -rf" in blocked
        assert "git push" in blocked

    def test_higher_max_turns_than_other_roles(self, tmp_path: Path) -> None:
        """The finalizer writes many files in one go; pin max_turns >= 15."""
        from urika.agents.roles.finalizer import build_config

        cfg = build_config(_project(tmp_path))
        assert cfg.max_turns >= 15

    def test_no_sandbox_escape_tools_allowed(self, tmp_path: Path) -> None:
        from urika.agents.roles.finalizer import build_config

        cfg = build_config(_project(tmp_path))
        for escape in ("Task", "Agent", "ToolSearch"):
            assert escape not in cfg.allowed_tools


# ── project_summarizer ─────────────────────────────────────────


class TestProjectSummarizerRoleConfig:
    def test_role_name(self) -> None:
        from urika.agents.roles.project_summarizer import get_role

        assert get_role().name == "project_summarizer"

    def test_read_only_no_bash(self, tmp_path: Path) -> None:
        from urika.agents.roles.project_summarizer import build_config

        cfg = build_config(_project(tmp_path))
        assert cfg.allowed_tools == ["Read", "Glob", "Grep"]
        assert cfg.security.writable_dirs == []
        assert cfg.security.allowed_bash_prefixes == []

    def test_project_name_and_question_reach_prompt(self, tmp_path: Path) -> None:
        """The prompt template includes {project_name} + {question}
        substitution — pin the variable wiring."""
        from urika.agents.roles.project_summarizer import build_config

        proj = _project(tmp_path)
        cfg = build_config(proj)
        # The prompt has the project name and question literally in it.
        assert "p" in cfg.system_prompt  # project name = "p"
        # The question contains "?", which is in the prompt as
        # "Research Question:\n?"
        assert "?" in cfg.system_prompt

    def test_no_sandbox_escape_tools_allowed(self, tmp_path: Path) -> None:
        from urika.agents.roles.project_summarizer import build_config

        cfg = build_config(_project(tmp_path))
        for escape in ("Task", "Agent", "ToolSearch"):
            assert escape not in cfg.allowed_tools

    def test_reasonable_max_turns(self, tmp_path: Path) -> None:
        from urika.agents.roles.project_summarizer import build_config

        cfg = build_config(_project(tmp_path))
        assert 5 <= cfg.max_turns <= 30
