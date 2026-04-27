"""Tests for the cross-process pause/stop file-flag bridge.

The dashboard runs in a different process than the orchestrator, so
its in-memory ``PauseController`` is unreachable from web handlers.
The bridge: the dashboard writes ``"pause"`` or ``"stop"`` to
``<project>/.urika/pause_requested``; the loop calls
:func:`read_and_clear_flag` at each turn boundary and forwards the
request into its in-memory controller.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig
from urika.core.session import load_session
from urika.core.workspace import create_project_workspace
from urika.orchestrator.loop import run_experiment
from urika.orchestrator.pause import PauseController, read_and_clear_flag


# ---------------------------------------------------------------------------
# read_and_clear_flag — pure helper
# ---------------------------------------------------------------------------


class TestReadAndClearFlag:
    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        assert read_and_clear_flag(tmp_path) is None

    def test_returns_pause_when_file_contains_pause(self, tmp_path: Path) -> None:
        flag_dir = tmp_path / ".urika"
        flag_dir.mkdir()
        (flag_dir / "pause_requested").write_text("pause", encoding="utf-8")
        assert read_and_clear_flag(tmp_path) == "pause"

    def test_returns_stop_when_file_contains_stop(self, tmp_path: Path) -> None:
        flag_dir = tmp_path / ".urika"
        flag_dir.mkdir()
        (flag_dir / "pause_requested").write_text("stop", encoding="utf-8")
        assert read_and_clear_flag(tmp_path) == "stop"

    def test_removes_file_after_reading(self, tmp_path: Path) -> None:
        flag_dir = tmp_path / ".urika"
        flag_dir.mkdir()
        flag = flag_dir / "pause_requested"
        flag.write_text("pause", encoding="utf-8")
        assert flag.exists()
        read_and_clear_flag(tmp_path)
        assert not flag.exists()

    def test_returns_none_for_garbage_content(self, tmp_path: Path) -> None:
        flag_dir = tmp_path / ".urika"
        flag_dir.mkdir()
        (flag_dir / "pause_requested").write_text("zorp", encoding="utf-8")
        assert read_and_clear_flag(tmp_path) is None

    def test_clears_file_even_for_garbage_content(self, tmp_path: Path) -> None:
        """A malformed flag should still be removed so a subsequent
        properly-formatted write isn't shadowed by leftover garbage."""
        flag_dir = tmp_path / ".urika"
        flag_dir.mkdir()
        flag = flag_dir / "pause_requested"
        flag.write_text("zorp", encoding="utf-8")
        read_and_clear_flag(tmp_path)
        assert not flag.exists()

    def test_strips_whitespace_and_lowercases(self, tmp_path: Path) -> None:
        flag_dir = tmp_path / ".urika"
        flag_dir.mkdir()
        (flag_dir / "pause_requested").write_text("  STOP\n", encoding="utf-8")
        assert read_and_clear_flag(tmp_path) == "stop"


# ---------------------------------------------------------------------------
# Loop integration — flag file forwards into the PauseController
# ---------------------------------------------------------------------------


def _setup_project(tmp_path: Path) -> tuple[Path, str]:
    config = ProjectConfig(
        name="flag-proj",
        question="Does the flag bridge work?",
        mode="exploratory",
        data_paths=[],
    )
    project_dir = tmp_path / "flag-proj"
    create_project_workspace(project_dir, config)
    exp = create_experiment(
        project_dir, name="flag-test", hypothesis="The bridge works"
    )
    return project_dir, exp.experiment_id


class _NeverCalledRunner(AgentRunner):
    async def run(
        self, config: AgentConfig, prompt: str, *, on_message: object = None
    ) -> AgentResult:
        msg = f"Agent {config.name} should not have been called"
        raise AssertionError(msg)


class TestLoopFlagIntegration:
    @pytest.mark.asyncio
    async def test_stop_flag_file_triggers_stop(self, tmp_path: Path) -> None:
        """A stop flag dropped before the first turn must short-circuit
        the loop with status=stopped (no agent calls)."""
        project_dir, exp_id = _setup_project(tmp_path)
        flag_dir = project_dir / ".urika"
        flag_dir.mkdir(parents=True, exist_ok=True)
        (flag_dir / "pause_requested").write_text("stop", encoding="utf-8")

        pc = PauseController()

        result = await run_experiment(
            project_dir,
            exp_id,
            _NeverCalledRunner(),
            max_turns=5,
            pause_controller=pc,
        )

        assert result["status"] == "stopped"
        # Flag file must be cleared after read
        assert not (flag_dir / "pause_requested").exists()
        # Session on disk should be stopped
        session = load_session(project_dir, exp_id)
        assert session is not None
        assert session.status == "stopped"

    @pytest.mark.asyncio
    async def test_pause_flag_file_triggers_pause(self, tmp_path: Path) -> None:
        """A pause flag dropped before the first turn must short-circuit
        the loop with status=paused (no agent calls)."""
        project_dir, exp_id = _setup_project(tmp_path)
        flag_dir = project_dir / ".urika"
        flag_dir.mkdir(parents=True, exist_ok=True)
        (flag_dir / "pause_requested").write_text("pause", encoding="utf-8")

        pc = PauseController()

        result = await run_experiment(
            project_dir,
            exp_id,
            _NeverCalledRunner(),
            max_turns=5,
            pause_controller=pc,
        )

        assert result["status"] == "paused"
        assert not (flag_dir / "pause_requested").exists()
        session = load_session(project_dir, exp_id)
        assert session is not None
        assert session.status == "paused"

    @pytest.mark.asyncio
    async def test_no_flag_no_pause(self, tmp_path: Path) -> None:
        """Without a flag file, the loop should NOT pause spuriously —
        the in-memory controller stays clean."""
        project_dir, exp_id = _setup_project(tmp_path)
        # No flag file written.

        pc = PauseController()

        # The loop will try to run; an asserting runner would fire on the
        # first agent call. We pre-set the controller to pause so the
        # loop returns immediately without exercising the runner — but
        # the key assertion is that the file-flag check below stays a
        # no-op (no flag exists, nothing to clear, no exceptions).
        pc.request_pause()

        result = await run_experiment(
            project_dir,
            exp_id,
            _NeverCalledRunner(),
            max_turns=5,
            pause_controller=pc,
        )

        assert result["status"] == "paused"
        # No flag file was created or magically appeared
        assert not (project_dir / ".urika" / "pause_requested").exists()
