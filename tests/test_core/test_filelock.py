"""Tests for file locking context manager."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from urika.core.filelock import locked_json_update


class TestLockedJsonUpdate:
    def test_lock_file_created(self, tmp_path: Path) -> None:
        """Lock file should be created next to the JSON file."""
        json_path = tmp_path / "data.json"
        json_path.write_text("{}")

        with locked_json_update(json_path):
            pass

        lock_path = json_path.with_suffix(".json.lock")
        assert lock_path.exists()

    def test_yields_path(self, tmp_path: Path) -> None:
        """Context manager should yield the original path."""
        json_path = tmp_path / "data.json"
        json_path.write_text("{}")

        with locked_json_update(json_path) as p:
            assert p == json_path

    def test_read_modify_write_inside_lock(self, tmp_path: Path) -> None:
        """Should be able to read, modify, and write JSON inside the lock."""
        json_path = tmp_path / "data.json"
        json_path.write_text(json.dumps({"items": []}))

        with locked_json_update(json_path):
            data = json.loads(json_path.read_text())
            data["items"].append("one")
            json_path.write_text(json.dumps(data))

        result = json.loads(json_path.read_text())
        assert result == {"items": ["one"]}

    def test_lock_file_created_when_json_missing(self, tmp_path: Path) -> None:
        """Lock file should be created even if the JSON file doesn't exist yet."""
        json_path = tmp_path / "new.json"

        with locked_json_update(json_path):
            json_path.write_text(json.dumps({"created": True}))

        assert json_path.with_suffix(".json.lock").exists()
        assert json.loads(json_path.read_text()) == {"created": True}

    def test_concurrent_writers_serialize(self, tmp_path: Path) -> None:
        """Multiple threads writing to the same file should not lose data."""
        json_path = tmp_path / "counter.json"
        json_path.write_text(json.dumps({"count": 0}))

        num_threads = 10
        increments_per_thread = 20
        barrier = threading.Barrier(num_threads)

        def increment() -> None:
            barrier.wait()
            for _ in range(increments_per_thread):
                with locked_json_update(json_path):
                    data = json.loads(json_path.read_text())
                    data["count"] += 1
                    json_path.write_text(json.dumps(data))

        threads = [threading.Thread(target=increment) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = json.loads(json_path.read_text())
        assert final["count"] == num_threads * increments_per_thread

    def test_exception_inside_lock_releases(self, tmp_path: Path) -> None:
        """An exception inside the lock block should still release the lock."""
        json_path = tmp_path / "data.json"
        json_path.write_text(json.dumps({"v": 1}))

        try:
            with locked_json_update(json_path):
                raise ValueError("boom")
        except ValueError:
            pass

        # Should be able to acquire the lock again without deadlocking
        with locked_json_update(json_path):
            data = json.loads(json_path.read_text())
            assert data == {"v": 1}
