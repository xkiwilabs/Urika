"""Tests for the corrupt-tolerant JSON loader (src/urika/core/json_io.py)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from urika.core.json_io import load_json_or_preserve, preserve_corrupt_file


class TestPreserveCorruptFile:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """preserve_corrupt_file on a non-existent path → None (no crash)."""
        result = preserve_corrupt_file(tmp_path / "ghost.json")
        assert result is None

    def test_renames_to_timestamped_name(self, tmp_path: Path) -> None:
        """A file is renamed to ``<name>.corrupt-<ts>`` and the original is gone."""
        f = tmp_path / "data.json"
        f.write_text("{broken", encoding="utf-8")

        preserved = preserve_corrupt_file(f)

        assert preserved is not None
        assert not f.exists(), "original should have been renamed away"
        assert preserved.exists(), "preserved file should exist"
        assert preserved.name.startswith("data.json.corrupt-"), (
            f"unexpected preserved name: {preserved.name}"
        )

    def test_preserved_name_does_not_match_json_glob(self, tmp_path: Path) -> None:
        """The preserved file must NOT be picked up by a ``*.json`` glob."""
        f = tmp_path / "sess-1.json"
        f.write_text("{broken", encoding="utf-8")

        preserve_corrupt_file(f)

        json_files = list(tmp_path.glob("*.json"))
        assert json_files == [], f"preserved file matched *.json glob: {json_files}"

    def test_collision_safety_appends_counter(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When the target already exists (same-second collision), a counter is appended."""
        f = tmp_path / "data.json"
        f.write_text("{broken1", encoding="utf-8")

        # Fix time.time() so both calls produce the same timestamp.
        fixed_ts = int(time.time())
        monkeypatch.setattr("urika.core.json_io.time.time", lambda: fixed_ts)

        # Pre-create the first collision target.
        first_target = tmp_path / f"data.json.corrupt-{fixed_ts}"
        first_target.write_text("earlier corrupt", encoding="utf-8")

        preserved = preserve_corrupt_file(f)

        assert preserved is not None
        assert preserved != first_target, "should not overwrite the existing file"
        assert preserved.name == f"data.json.corrupt-{fixed_ts}-1", (
            f"unexpected counter name: {preserved.name}"
        )
        assert preserved.exists()
        assert first_target.exists(), "earlier corrupt file must not be overwritten"


class TestLoadJsonOrPreserve:
    def test_missing_file_returns_fallback(self, tmp_path: Path) -> None:
        """A missing file returns the fallback without creating any corrupt file."""
        result = load_json_or_preserve(tmp_path / "nope.json", {"default": True})
        assert result == {"default": True}
        assert list(tmp_path.glob("*.corrupt-*")) == []

    def test_valid_json_returns_parsed(self, tmp_path: Path) -> None:
        """A valid JSON file is parsed and returned."""
        f = tmp_path / "good.json"
        f.write_text(json.dumps({"key": "value", "n": 42}), encoding="utf-8")

        result = load_json_or_preserve(f, {})
        assert result == {"key": "value", "n": 42}
        assert f.exists(), "valid file must not be renamed"

    def test_corrupt_json_returns_fallback_and_preserves(self, tmp_path: Path) -> None:
        """Corrupt JSON → fallback returned, original gone, one .corrupt-* file."""
        f = tmp_path / "state.json"
        f.write_text("{this is not json", encoding="utf-8")

        result = load_json_or_preserve(f, [])
        assert result == [], "should return the fallback"
        assert not f.exists(), "original corrupt file should be renamed away"
        preserved = list(tmp_path.glob("state.json.corrupt-*"))
        assert len(preserved) == 1, (
            f"expected exactly one .corrupt-* file, found: {preserved}"
        )

    def test_double_corruption_preserves_two_files(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Two separate corruptions produce two distinct .corrupt-* files.

        Because int(time.time()) can return the same value within one second,
        the collision-safe counter in preserve_corrupt_file must ensure the
        second preserve does NOT overwrite the first.
        """
        f = tmp_path / "sess-1.json"

        # First corruption.
        f.write_text("{broken first", encoding="utf-8")
        # Freeze time so both corruptions share the same timestamp.
        fixed_ts = int(time.time())
        monkeypatch.setattr("urika.core.json_io.time.time", lambda: fixed_ts)

        result1 = load_json_or_preserve(f, None)
        assert result1 is None

        # Second corruption — re-write the file (simulates a new crash).
        f.write_text("{broken second", encoding="utf-8")
        result2 = load_json_or_preserve(f, None)
        assert result2 is None

        # Both originals are gone; two distinct .corrupt-* files survive.
        assert not f.exists()
        preserved = sorted(tmp_path.glob("sess-1.json.corrupt-*"))
        assert len(preserved) == 2, f"expected two .corrupt-* files, found: {preserved}"
        # Their names must differ.
        assert preserved[0].name != preserved[1].name

    def test_fallback_returned_as_is(self, tmp_path: Path) -> None:
        """The fallback instance is returned unchanged (not copied or mutated)."""
        sentinel = object()
        result = load_json_or_preserve(tmp_path / "missing.json", sentinel)
        assert result is sentinel
