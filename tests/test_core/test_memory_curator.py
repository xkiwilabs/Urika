"""Tests for ``urika.core.memory_curator`` (v0.5.0 Task 2.5 + 2.6).

The curator dispatch invokes the ``memory_curator`` agent role with a
rendered snapshot of the project's memory directory, parses the JSON
``decisions`` block out of the response, and (optionally) applies them.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.core import project_memory as pm


class _FakeRunner(AgentRunner):
    """Stand-in for the agent runner. Returns a canned decisions block.

    Matches the real ``AgentRunner.run`` signature
    (``async def run(config, prompt, *, on_message=None) -> AgentResult``).
    """

    def __init__(self, decisions: list[dict]):
        self._decisions = decisions
        self.last_prompt: str | None = None
        self.last_config_name: str | None = None

    async def run(
        self,
        config: AgentConfig,
        prompt: str,
        *,
        on_message: object = None,
    ) -> AgentResult:
        self.last_prompt = prompt
        self.last_config_name = config.name
        body = json.dumps({"decisions": self._decisions})
        text = f"```json\n{body}\n```"
        return AgentResult(
            success=True,
            messages=[],
            text_output=text,
            session_id="session-memory_curator-0",
            num_turns=1,
            duration_ms=10,
        )


# ---------------------------------------------------------------------------
# T2.5 — dry-run path
# ---------------------------------------------------------------------------


def test_run_curator_dry_run_returns_decisions(tmp_path: Path) -> None:
    from urika.core.memory_curator import run_curator

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm.save_entry(proj, mem_type="user", description="a", body="b1")
    runner = _FakeRunner(
        [{"action": "archive", "filename": "user_a.md", "reason": "stale"}]
    )
    result = asyncio.run(run_curator(proj, runner=runner, apply=False))
    assert len(result.decisions) == 1
    assert result.decisions[0]["action"] == "archive"
    assert result.applied is False
    # Nothing on disk changed — entry still in place.
    assert any(e["filename"].startswith("user_") for e in pm.list_entries(proj))


def test_run_curator_returns_empty_when_no_decisions(tmp_path: Path) -> None:
    from urika.core.memory_curator import run_curator

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm.save_entry(proj, mem_type="user", description="a", body="b1")
    runner = _FakeRunner([])
    result = asyncio.run(run_curator(proj, runner=runner, apply=False))
    assert result.decisions == []
    assert result.applied is False


def test_build_curator_input_includes_each_entry(tmp_path: Path) -> None:
    """The user message contains each memory entry's filename + body."""
    from urika.core.memory_curator import _build_curator_input

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm.save_entry(proj, mem_type="user", description="alpha", body="content-alpha")
    pm.save_entry(proj, mem_type="user", description="beta", body="content-beta")
    msg = _build_curator_input(proj)
    assert "content-alpha" in msg
    assert "content-beta" in msg
    # Both filenames present.
    assert "user_alpha.md" in msg
    assert "user_beta.md" in msg


# ---------------------------------------------------------------------------
# T2.6 — apply path: archive / merge / flag
# ---------------------------------------------------------------------------


def test_apply_archive_moves_entry(tmp_path: Path) -> None:
    from urika.core.memory_curator import run_curator

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm.save_entry(proj, mem_type="user", description="old", body="stale")
    name = pm.list_entries(proj)[0]["filename"]
    runner = _FakeRunner([{"action": "archive", "filename": name, "reason": "stale"}])
    result = asyncio.run(run_curator(proj, runner=runner, apply=True))
    assert result.applied is True
    assert not (proj / "memory" / name).exists()
    archived = list((proj / "memory" / "archive").rglob(name))
    assert len(archived) == 1


def test_apply_merge_keeps_one_and_archives_other(tmp_path: Path) -> None:
    from urika.core.memory_curator import run_curator

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm.save_entry(proj, mem_type="user", description="a", body="first claim")
    pm.save_entry(
        proj, mem_type="user", description="b", body="same claim, more detail"
    )
    names = [e["filename"] for e in pm.list_entries(proj)]
    keep, drop = names[0], names[1]
    runner = _FakeRunner(
        [{"action": "merge", "into": keep, "from": [drop], "reason": "dup"}]
    )
    asyncio.run(run_curator(proj, runner=runner, apply=True))
    assert (proj / "memory" / keep).exists()
    assert not (proj / "memory" / drop).exists()
    body = (proj / "memory" / keep).read_text()
    assert "first claim" in body
    assert "same claim" in body


def test_apply_flag_stale_appends_flag(tmp_path: Path) -> None:
    from urika.core.memory_curator import run_curator

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm.save_entry(proj, mem_type="user", description="x", body="b")
    name = pm.list_entries(proj)[0]["filename"]
    runner = _FakeRunner(
        [
            {
                "action": "flag_stale",
                "filename": name,
                "reason": "no longer matches code",
            }
        ]
    )
    asyncio.run(run_curator(proj, runner=runner, apply=True))
    text = (proj / "memory" / name).read_text()
    assert "flagged_stale:" in text
    # Idempotent — running again should not duplicate the flag.
    asyncio.run(run_curator(proj, runner=runner, apply=True))
    text2 = (proj / "memory" / name).read_text()
    assert text2.count("flagged_stale:") == 1


def test_apply_handles_malformed_decision_without_crashing(tmp_path: Path) -> None:
    """A decision missing required fields is silently skipped."""
    from urika.core.memory_curator import run_curator

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm.save_entry(proj, mem_type="user", description="x", body="b")
    runner = _FakeRunner(
        [
            {"action": "merge"},  # missing 'into' / 'from'
            {"action": "archive", "filename": "nonexistent.md"},
        ]
    )
    # Should not raise.
    result = asyncio.run(run_curator(proj, runner=runner, apply=True))
    assert result.applied is True
