"""Unit tests for the builder-session persistence layer
(v0.10.0 Phase 6).

These exercise ``urika.dashboard.builder_sessions`` directly — no
FastAPI / event loop — to pin the serializable-slice persistence,
disk rehydration into a detached session, the answer-replay wrapper,
and its agent-question-drift fallback.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from urika.core.builder_loop import BuilderQuestion
from urika.dashboard import builder_sessions as bs


@pytest.fixture(autouse=True)
def _clear_active():
    bs._active.clear()
    yield
    bs._active.clear()


def _make_session(project_dir: Path, name: str = "alpha") -> bs.BuilderSession:
    return bs.BuilderSession(
        session_id="abc123",
        project_name=name,
        project_dir=project_dir,
    )


class TestPersistence:
    def test_persist_writes_transcript_atomically(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path)
        s.transcript.append(("Q1?", "A1"))
        s.transcript.append(("Q2?", "A2"))
        s.pending_question_data = BuilderQuestion(text="Q3?", options=["x", "y"])
        bs.persist(s)

        path = bs.session_path(tmp_path)
        assert path.exists()
        # Atomic write leaves no .tmp turds behind.
        leftovers = list(path.parent.glob("*.tmp*"))
        assert leftovers == [], f"atomic write leaked temp files: {leftovers}"

        raw = bs.load_persisted(tmp_path)
        assert raw["session_id"] == "abc123"
        assert raw["transcript"] == [["Q1?", "A1"], ["Q2?", "A2"]]
        assert raw["pending_question"]["text"] == "Q3?"
        assert raw["pending_question"]["options"] == ["x", "y"]
        assert raw["done"] is False

    def test_delete_persisted_is_idempotent(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path)
        bs.persist(s)
        assert bs.session_path(tmp_path).exists()
        bs.delete_persisted(tmp_path)
        assert not bs.session_path(tmp_path).exists()
        # Second delete must not raise.
        bs.delete_persisted(tmp_path)


class TestRehydrate:
    def test_get_for_project_rehydrates_detached_after_restart(
        self, tmp_path: Path
    ) -> None:
        # Drive a session through a couple answers, persist, then
        # simulate a restart by clearing _active.
        s = _make_session(tmp_path)
        s.transcript.append(("Q1?", "A1"))
        s.pending_question_data = BuilderQuestion(text="Q2?", options=["a", "b"])
        bs.persist(s)
        bs._active.clear()

        # No in-memory session; lookup without project_dir finds nothing.
        assert bs.get_for_project("alpha") is None

        # With the project_dir, it rehydrates a detached session.
        revived = bs.get_for_project("alpha", tmp_path)
        assert revived is not None
        assert revived.detached is True
        assert revived.task is None
        assert revived.transcript == [("Q1?", "A1")]
        assert revived.pending_question_data.text == "Q2?"
        assert revived.pending_question_data.options == ["a", "b"]
        # It's registered so subsequent lookups are cheap.
        assert bs.get_for_project("alpha") is revived

    def test_terminal_session_is_not_rehydrated(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path)
        s.transcript.append(("Q1?", "A1"))
        s.done = True
        bs.persist(s)
        bs._active.clear()
        # A finished session has nothing to resume.
        assert bs.get_for_project("alpha", tmp_path) is None

    def test_in_memory_session_wins_over_disk(self, tmp_path: Path) -> None:
        live = _make_session(tmp_path)
        bs.register(live)
        # Even with a disk record present, the live session is returned.
        assert bs.get_for_project("alpha", tmp_path) is live


class TestReplayResume:
    def test_replay_consumes_saved_answers_then_blocks_live(self) -> None:
        transcript = [("Q1?", "A1"), ("Q2?", "A2")]
        live_calls: list[str] = []

        async def live(q: BuilderQuestion) -> str:
            live_calls.append(q.text)
            return "LIVE"

        ask = bs.make_replay_ask_user(transcript, live)

        async def drive():
            # Matched questions are auto-answered without going live.
            assert await ask(BuilderQuestion(text="Q1?")) == "A1"
            assert await ask(BuilderQuestion(text="Q2?")) == "A2"
            assert live_calls == []  # no live ask yet
            # Transcript exhausted → next question blocks for live input.
            assert await ask(BuilderQuestion(text="Q3?")) == "LIVE"
            assert live_calls == ["Q3?"]

        asyncio.run(drive())

    def test_drift_falls_back_to_live_without_misapplying_saved_answer(
        self,
    ) -> None:
        transcript = [("Q1?", "A1"), ("Q2?", "A2")]
        live_seen: list[str] = []

        async def live(q: BuilderQuestion) -> str:
            live_seen.append(q.text)
            return f"live-{q.text}"

        ask = bs.make_replay_ask_user(transcript, live)

        async def drive():
            # First question matches → replayed.
            assert await ask(BuilderQuestion(text="Q1?")) == "A1"
            # Second question DRIFTED (agent produced a different text).
            # The saved "A2" must NOT be applied; it goes live instead.
            assert await ask(BuilderQuestion(text="DIFFERENT?")) == "live-DIFFERENT?"
            # Drift is permanent: even a later question whose text
            # matches a remaining saved pair goes live, not replayed.
            assert await ask(BuilderQuestion(text="Q2?")) == "live-Q2?"
            assert live_seen == ["DIFFERENT?", "Q2?"]

        asyncio.run(drive())

    def test_on_replay_callback_fires_for_replayed_only(self) -> None:
        transcript = [("Q1?", "A1")]
        replayed: list[tuple[str, str]] = []

        async def live(q: BuilderQuestion) -> str:
            return "LIVE"

        ask = bs.make_replay_ask_user(
            transcript,
            live,
            on_replay=lambda q, a: replayed.append((q.text, a)),
        )

        async def drive():
            await ask(BuilderQuestion(text="Q1?"))  # replayed
            await ask(BuilderQuestion(text="Q2?"))  # live

        asyncio.run(drive())
        assert replayed == [("Q1?", "A1")]
