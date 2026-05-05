"""Tests for ``urika.core.atomic_write``.

Covers:
- Happy path text + JSON writes produce the expected content.
- File mode is honored on POSIX.
- A mid-write exception leaves the prior file contents intact (no
  truncation) and removes the temp sibling.
- Rapid concurrent writes via threads do not produce corrupt files.
- ``write_json_atomic`` round-trips arbitrary JSON-able structures.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest

from urika.core.atomic_write import write_json_atomic, write_text_atomic


def test_write_text_atomic_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    write_text_atomic(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_write_text_atomic_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old contents", encoding="utf-8")
    write_text_atomic(target, "new contents")
    assert target.read_text(encoding="utf-8") == "new contents"


def test_write_text_atomic_creates_parent(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deep" / "out.txt"
    write_text_atomic(target, "ok")
    assert target.read_text(encoding="utf-8") == "ok"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_write_text_atomic_honors_mode(tmp_path: Path) -> None:
    target = tmp_path / "secret.env"
    write_text_atomic(target, "TOKEN=value\n", mode=0o600)
    st = target.stat()
    # Lower 9 bits of st_mode are the permission bits.
    assert (st.st_mode & 0o777) == 0o600


def test_write_text_atomic_partial_failure_preserves_prior(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("survivor", encoding="utf-8")

    # Force os.replace to fail AFTER the temp file has been written, so
    # we can assert that the original target is intact and the temp
    # sibling is cleaned up.
    real_replace = os.replace

    def boom(src: str, dst: str) -> None:
        # Sanity: the temp file exists at this point.
        assert Path(src).exists()
        raise OSError("simulated rename failure")

    with mock.patch("urika.core.atomic_write.os.replace", side_effect=boom):
        with pytest.raises(OSError, match="simulated rename failure"):
            write_text_atomic(target, "new contents")

    # Original is untouched.
    assert target.read_text(encoding="utf-8") == "survivor"
    # Temp sibling was cleaned up.
    siblings = [p.name for p in tmp_path.iterdir() if p.name.startswith(".out.txt.tmp")]
    assert siblings == [], f"leaked temp files: {siblings}"

    # Make sure the real os.replace still works for the next test.
    assert real_replace is os.replace


def test_write_json_atomic_roundtrips_dict(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    payload = {"a": 1, "b": [2, 3], "c": {"nested": True}, "unicode": "ñ"}
    write_json_atomic(target, payload)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == payload


def test_write_json_atomic_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    write_json_atomic(target, [1, 2, 3])
    assert target.read_text(encoding="utf-8").endswith("\n")


def test_concurrent_writes_do_not_corrupt(tmp_path: Path) -> None:
    """Many threads writing to the same file must always leave a
    valid JSON document — never a half-merged or zero-byte result.
    Each thread writes a unique payload; after all threads finish, the
    file content must match one of the payloads exactly.
    """
    target = tmp_path / "concurrent.json"
    threads = []
    payloads = [{"thread": i, "data": list(range(i))} for i in range(20)]

    def worker(payload: dict) -> None:
        write_json_atomic(target, payload)

    for p in payloads:
        t = threading.Thread(target=worker, args=(p,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    # The file must be valid JSON and equal to one of the payloads.
    body = target.read_text(encoding="utf-8")
    loaded = json.loads(body)
    assert loaded in payloads


def test_no_temp_files_left_on_success(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    write_text_atomic(target, "ok")
    siblings = [p.name for p in tmp_path.iterdir() if p.name.startswith(".out.txt.tmp")]
    assert siblings == []
