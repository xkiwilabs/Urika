"""Tests for the orchestrator's pre-turn curator hook (v0.5.0 Task 2.7).

When ``project_memory.is_curator_due(project_dir, session_id)`` returns
True (set after the soft cap is crossed in T2.3), the orchestrator runs
the memory curator in DRY-RUN at the start of the next agent
invocation, emits the proposed decisions as a notice, then calls
``mark_curator_ran`` so it doesn't fire again this session.
"""

from __future__ import annotations

import asyncio

from urika.core import project_memory as pm


def test_curator_fires_when_due(tmp_path, monkeypatch):
    """When the session-scoped flag is set, ``_maybe_run_curator``
    invokes ``run_curator`` in dry-run, returns a notice, and clears
    the flag."""
    from urika.orchestrator import loop

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    body = "x" * 21_000  # ~6K tokens
    pm.save_entry(proj, mem_type="user", description="big", body=body)
    pm._signal_curator_due(proj, session_id="s1")  # simulate soft-cap signal

    fired = []

    async def fake_run_curator(project_dir, runner, apply=False):
        fired.append((project_dir, apply))
        from urika.core.memory_curator import CuratorResult

        return CuratorResult(
            decisions=[{"action": "archive", "filename": "x", "reason": "r"}]
        )

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake_run_curator)

    notice = asyncio.run(
        loop._maybe_run_curator(proj, runner=object(), session_id="s1")
    )
    assert fired == [(proj, False)]  # dry-run only
    assert notice is not None
    assert "Memory curator" in notice
    assert "1 suggestion" in notice
    assert pm.is_curator_due(proj, session_id="s1") is False  # flag cleared


def test_no_curator_when_session_id_none(tmp_path):
    """No session_id → no curator run."""
    from urika.orchestrator import loop

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    notice = asyncio.run(
        loop._maybe_run_curator(proj, runner=object(), session_id=None)
    )
    assert notice is None


def test_no_curator_when_flag_not_set(tmp_path):
    """Session_id provided but no flag → no curator run."""
    from urika.orchestrator import loop

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    notice = asyncio.run(
        loop._maybe_run_curator(proj, runner=object(), session_id="s1")
    )
    assert notice is None


def test_curator_failure_does_not_propagate(tmp_path, monkeypatch):
    """A curator exception is caught and surfaced as a notice; flag still cleared."""
    from urika.orchestrator import loop

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm._signal_curator_due(proj, session_id="s1")

    async def boom(project_dir, runner, apply=False):
        raise RuntimeError("simulated curator failure")

    monkeypatch.setattr("urika.core.memory_curator.run_curator", boom)
    notice = asyncio.run(
        loop._maybe_run_curator(proj, runner=object(), session_id="s1")
    )
    assert notice is not None
    assert "failed to run" in notice
    assert pm.is_curator_due(proj, session_id="s1") is False  # cleared anyway


def test_curator_idempotent_within_session(tmp_path, monkeypatch):
    """After firing once, a second call in the same session is a no-op."""
    from urika.orchestrator import loop

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm._signal_curator_due(proj, session_id="s1")

    fired = 0

    async def fake(project_dir, runner, apply=False):
        nonlocal fired
        fired += 1
        from urika.core.memory_curator import CuratorResult

        return CuratorResult(decisions=[])

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)

    asyncio.run(loop._maybe_run_curator(proj, runner=object(), session_id="s1"))
    asyncio.run(loop._maybe_run_curator(proj, runner=object(), session_id="s1"))
    assert fired == 1


def test_curator_returns_error_in_notice(tmp_path, monkeypatch):
    """A CuratorResult with error set (soft failure) must surface in the notice,
    not be reported as 'no changes suggested'."""
    from urika.orchestrator import loop

    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    pm._signal_curator_due(proj, session_id="s1")

    async def fake_run_curator(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        return CuratorResult(decisions=[], applied=False, error="agent stream timeout")

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake_run_curator)
    notice = asyncio.run(
        loop._maybe_run_curator(proj, runner=object(), session_id="s1")
    )
    assert notice is not None
    assert "failed" in notice
    assert "agent stream timeout" in notice
    assert "no changes suggested" not in notice
    assert pm.is_curator_due(proj, session_id="s1") is False  # flag cleared
