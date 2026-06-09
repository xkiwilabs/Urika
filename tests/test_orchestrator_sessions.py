"""Tests for orchestrator conversation session persistence."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

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


@pytest.fixture
def monotonic_session_ids(monkeypatch):
    """Replace ``_timestamp_id`` with a monotonically-increasing counter.

    v0.4.2 H13: pre-fix this suite paid ~6.6s of ``time.sleep(1.1)``
    per run just so the second-resolution timestamp prefix advanced
    between saves. The fixture injects a counter so ordering is
    deterministic, the suite is fast, and behaviour under clock skew
    or load lag becomes irrelevant.
    """
    from urika.core import orchestrator_sessions as os_mod

    counter = {"n": 0}

    def _gen() -> str:
        counter["n"] += 1
        # Match the production format ``YYYY-MM-DDTHH-MM-SS-XXXX`` so
        # length-checking tests still pass; encode the counter into the
        # seconds + suffix portions so lex order matches insert order.
        return f"2026-01-01T00-00-{counter['n']:02d}-{counter['n']:04x}"

    monkeypatch.setattr(os_mod, "_timestamp_id", _gen)
    yield counter


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
        # Format: YYYY-MM-DDTHH-MM-SS-XXXX (4 hex chars suffix added in
        # v0.4.2 to break sub-second collisions — see C10).
        assert len(session.session_id) == 24
        assert session.session_id[4] == "-"
        assert session.session_id[10] == "T"
        assert session.session_id[19] == "-"
        # Suffix is 4 hex chars.
        suffix = session.session_id[20:]
        assert len(suffix) == 4
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_session_ids_unique_when_timestamp_collides(self, monkeypatch) -> None:
        # Pre-v0.4.2 used second-resolution timestamps with no suffix,
        # so two sessions started in the same second produced the same
        # ``session_id`` and the second save_session overwrote the first.
        # The C10 fix appends a random suffix; force the timestamp half
        # to be identical and prove the suffix half still differs.
        from urika.core import orchestrator_sessions as os_mod

        fixed_stamp = "2026-01-01T00-00-01"
        monkeypatch.setattr(
            os_mod,
            "_timestamp_id",
            lambda: fixed_stamp + "-" + os_mod.secrets.token_hex(2),
        )
        ids = {create_new_session().session_id for _ in range(20)}
        # All ids share the timestamp prefix...
        assert all(i.startswith(fixed_stamp) for i in ids)
        # ...but at least 18 of 20 are unique (4 hex chars = 65k space,
        # collision probability over 20 draws is ~0.3%; 18/20 floor is
        # safely above any realistic flake threshold).
        assert len(ids) >= 18


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

    def test_list_ordering_most_recent_first(
        self, tmp_path: Path, monotonic_session_ids
    ) -> None:
        # v0.4.2 H13: pre-fix this test had 2.2s of ``time.sleep(1.1)``
        # between saves so the second-resolution timestamp prefix
        # advanced. The ``monotonic_session_ids`` fixture replaces the
        # timestamp generator with a counter so ordering is
        # deterministic and the sleeps are gone.
        s1 = create_new_session()
        save_session(tmp_path, s1)
        s2 = create_new_session()
        save_session(tmp_path, s2)
        s3 = create_new_session()
        save_session(tmp_path, s3)

        result = list_sessions(tmp_path)
        assert len(result) == 3
        # Most recent first (reverse sorted by id)
        assert result[0]["session_id"] == s3.session_id
        assert result[1]["session_id"] == s2.session_id
        assert result[2]["session_id"] == s1.session_id

    def test_list_honors_limit(self, tmp_path: Path, monotonic_session_ids) -> None:
        for _ in range(3):
            save_session(tmp_path, create_new_session())

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

    def test_most_recent_returns_latest(
        self, tmp_path: Path, monotonic_session_ids
    ) -> None:
        s1 = create_new_session()
        save_session(tmp_path, s1)
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


def test_save_auto_prunes_when_over_keep_limit(tmp_path):
    """Saving the 21st session triggers an auto-prune that keeps only 20.

    Without this, sessions accumulate forever — the prune helper exists but
    was never called from the save path before this fix.
    """
    project_dir = tmp_path

    # Save 25 sessions in sequence.
    for i in range(25):
        session = OrchestratorSession(
            session_id=f"session-{i:04d}",
            started=f"2026-01-{(i % 28) + 1:02d}T00:00:00Z",
            updated=f"2026-01-{(i % 28) + 1:02d}T00:00:00Z",
        )
        save_session(project_dir, session)

    # After the 25th save, only 20 should remain on disk.
    sessions_dir = project_dir / ".urika" / "sessions"
    surviving = list(sessions_dir.glob("*.json"))
    assert len(surviving) == 20, (
        f"expected 20 sessions after auto-prune, found {len(surviving)}"
    )

    # The most recent (largest session_id) must NOT have been pruned —
    # auto-prune should never delete the file we just wrote.
    surviving_ids = sorted(f.stem for f in surviving)
    assert "session-0024" in surviving_ids, (
        "auto-prune deleted the freshly-saved session — sort order is wrong"
    )


class TestPruneOldSessions:
    def test_prune_nothing_when_under_limit(
        self, tmp_path: Path, monotonic_session_ids
    ) -> None:
        for _ in range(3):
            save_session(tmp_path, create_new_session())

        deleted = prune_old_sessions(tmp_path, keep=5)
        assert deleted == 0
        assert len(list_sessions(tmp_path)) == 3

    def test_prune_removes_oldest(self, tmp_path: Path, monotonic_session_ids) -> None:
        ids = []
        for _ in range(5):
            s = create_new_session()
            save_session(tmp_path, s)
            ids.append(s.session_id)

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


class TestCorruptSessionHandling:
    """Task 1.2: corrupt or missing session files must not crash callers."""

    def test_load_session_corrupt_json_returns_none_and_preserves(
        self, tmp_path: Path
    ) -> None:
        """Corrupt JSON → load_session returns None, original gone, .corrupt exists."""
        sessions_dir = tmp_path / ".urika" / "sessions"
        sessions_dir.mkdir(parents=True)
        corrupt_file = sessions_dir / "sess-1.json"
        corrupt_file.write_text('{"truncated": ', encoding="utf-8")

        result = load_session(tmp_path, "sess-1")
        assert result is None
        assert not corrupt_file.exists(), "original should have been renamed away"
        preserved = list(sessions_dir.glob("sess-1.json.corrupt-*"))
        assert len(preserved) == 1, f"expected one .corrupt-* file, found: {preserved}"

    def test_load_session_missing_returns_none(self, tmp_path: Path) -> None:
        """Missing session file → load_session returns None (no crash)."""
        result = load_session(tmp_path, "totally-missing-id")
        assert result is None

    def test_list_sessions_skips_corrupt(self, tmp_path: Path) -> None:
        """One valid + one corrupt session → list_sessions returns only the valid one."""
        # Create a valid session
        valid_session = create_new_session()
        valid_session.preview = "good session"
        save_session(tmp_path, valid_session)

        # Create a corrupt session file directly
        sessions_dir = tmp_path / ".urika" / "sessions"
        corrupt_file = sessions_dir / "2026-01-01T00-00-00-dead.json"
        corrupt_file.write_text("{bad json", encoding="utf-8")

        result = list_sessions(tmp_path)
        # Only the valid session should appear
        assert len(result) == 1
        assert result[0]["session_id"] == valid_session.session_id

        # The corrupt file should have been preserved with a timestamped name
        # that does NOT match *.json (so it won't be picked up by a subsequent scan)
        assert not corrupt_file.exists(), "original corrupt file should be renamed away"
        preserved = list(sessions_dir.glob("2026-01-01T00-00-00-dead.json.corrupt-*"))
        assert len(preserved) == 1, f"expected one .corrupt-* file, found: {preserved}"
        # Confirm the preserved file is NOT picked up by a fresh list_sessions scan
        result2 = list_sessions(tmp_path)
        assert len(result2) == 1, (
            "preserved .corrupt-* file must not appear in list_sessions"
        )


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
