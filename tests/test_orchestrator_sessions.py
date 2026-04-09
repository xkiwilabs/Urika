"""Tests for orchestrator conversation session persistence."""

from __future__ import annotations

import time
from pathlib import Path

from urika.core.orchestrator_sessions import (
    OrchestratorSession,
    create_new_session,
    delete_session,
    get_most_recent,
    list_sessions,
    load_session,
    prune_old_sessions,
    save_session,
)


class TestCreateNewSession:
    def test_create_returns_populated_session(self) -> None:
        session = create_new_session()
        assert session.session_id
        assert session.started
        assert session.updated
        assert session.older_summary == ""
        assert session.recent_messages == []
        assert session.preview == ""

    def test_session_id_has_timestamp_format(self) -> None:
        session = create_new_session()
        # Format: YYYY-MM-DDTHH-MM-SS
        assert len(session.session_id) == 19
        assert session.session_id[4] == "-"
        assert session.session_id[10] == "T"


class TestSaveAndLoad:
    def test_save_then_load_roundtrip(self, tmp_path: Path) -> None:
        session = create_new_session()
        session.recent_messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi back"},
        ]
        session.preview = "hello"
        save_session(tmp_path, session)

        loaded = load_session(tmp_path, session.session_id)
        assert loaded is not None
        assert loaded.session_id == session.session_id
        assert loaded.preview == "hello"
        assert len(loaded.recent_messages) == 2
        assert loaded.recent_messages[0]["content"] == "hello"

    def test_save_updates_updated_timestamp(self, tmp_path: Path) -> None:
        session = create_new_session()
        original_updated = session.updated
        time.sleep(0.01)
        save_session(tmp_path, session)
        # The save should have refreshed `updated`
        assert session.updated >= original_updated

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        result = load_session(tmp_path, "does-not-exist")
        assert result is None

    def test_save_creates_sessions_directory(self, tmp_path: Path) -> None:
        session = create_new_session()
        save_session(tmp_path, session)
        assert (tmp_path / ".urika" / "sessions").is_dir()
        assert (
            tmp_path / ".urika" / "sessions" / f"{session.session_id}.json"
        ).exists()


class TestListSessions:
    def test_list_empty(self, tmp_path: Path) -> None:
        assert list_sessions(tmp_path) == []

    def test_list_ordering_most_recent_first(self, tmp_path: Path) -> None:
        s1 = create_new_session()
        save_session(tmp_path, s1)
        time.sleep(1.1)
        s2 = create_new_session()
        save_session(tmp_path, s2)
        time.sleep(1.1)
        s3 = create_new_session()
        save_session(tmp_path, s3)

        result = list_sessions(tmp_path)
        assert len(result) == 3
        # Most recent first (reverse sorted by id)
        assert result[0]["session_id"] == s3.session_id
        assert result[1]["session_id"] == s2.session_id
        assert result[2]["session_id"] == s1.session_id

    def test_list_honors_limit(self, tmp_path: Path) -> None:
        for _ in range(3):
            save_session(tmp_path, create_new_session())
            time.sleep(1.1)

        result = list_sessions(tmp_path, limit=2)
        assert len(result) == 2

    def test_list_entry_shape(self, tmp_path: Path) -> None:
        session = create_new_session()
        session.preview = "my preview"
        session.recent_messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        session.older_summary = "earlier stuff"
        save_session(tmp_path, session)

        result = list_sessions(tmp_path)
        assert len(result) == 1
        entry = result[0]
        assert entry["session_id"] == session.session_id
        assert entry["preview"] == "my preview"
        assert entry["turn_count"] == 2  # 4 messages / 2
        assert entry["has_older_summary"] is True


class TestGetMostRecent:
    def test_most_recent_empty(self, tmp_path: Path) -> None:
        assert get_most_recent(tmp_path) is None

    def test_most_recent_returns_latest(self, tmp_path: Path) -> None:
        s1 = create_new_session()
        save_session(tmp_path, s1)
        time.sleep(1.1)
        s2 = create_new_session()
        save_session(tmp_path, s2)

        result = get_most_recent(tmp_path)
        assert result is not None
        assert result.session_id == s2.session_id


class TestDeleteSession:
    def test_delete_existing(self, tmp_path: Path) -> None:
        session = create_new_session()
        save_session(tmp_path, session)

        assert delete_session(tmp_path, session.session_id) is True
        assert load_session(tmp_path, session.session_id) is None

    def test_delete_nonexistent(self, tmp_path: Path) -> None:
        assert delete_session(tmp_path, "does-not-exist") is False


class TestPruneOldSessions:
    def test_prune_nothing_when_under_limit(self, tmp_path: Path) -> None:
        for _ in range(3):
            save_session(tmp_path, create_new_session())
            time.sleep(1.1)

        deleted = prune_old_sessions(tmp_path, keep=5)
        assert deleted == 0
        assert len(list_sessions(tmp_path)) == 3

    def test_prune_removes_oldest(self, tmp_path: Path) -> None:
        ids = []
        for _ in range(5):
            s = create_new_session()
            save_session(tmp_path, s)
            ids.append(s.session_id)
            time.sleep(1.1)

        deleted = prune_old_sessions(tmp_path, keep=3)
        assert deleted == 2
        remaining = list_sessions(tmp_path)
        assert len(remaining) == 3
        # Most recent 3 should survive
        surviving_ids = {r["session_id"] for r in remaining}
        assert ids[2] in surviving_ids
        assert ids[3] in surviving_ids
        assert ids[4] in surviving_ids
        assert ids[0] not in surviving_ids
        assert ids[1] not in surviving_ids


class TestOrchestratorSessionDataclass:
    def test_to_dict_roundtrip(self) -> None:
        session = OrchestratorSession(
            session_id="2026-04-09T12-00-00",
            started="2026-04-09T12:00:00+00:00",
            updated="2026-04-09T12:00:00+00:00",
            older_summary="summary",
            recent_messages=[{"role": "user", "content": "hi"}],
            preview="hi",
        )
        d = session.to_dict()
        restored = OrchestratorSession.from_dict(d)
        assert restored == session

    def test_from_dict_with_missing_optionals(self) -> None:
        d = {
            "session_id": "abc",
            "started": "2026-04-09T12:00:00+00:00",
            "updated": "2026-04-09T12:00:00+00:00",
        }
        session = OrchestratorSession.from_dict(d)
        assert session.older_summary == ""
        assert session.recent_messages == []
        assert session.preview == ""
