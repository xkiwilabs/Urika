"""File locking for atomic JSON read-modify-write operations."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


@contextmanager
def locked_json_update(path: Path) -> Generator[Path, None, None]:
    """Context manager for atomic JSON read-modify-write with file locking.

    Creates a .lock file adjacent to the target JSON file and holds an
    exclusive lock for the duration of the block.  Uses ``fcntl.flock``
    on Unix and ``msvcrt.locking`` on Windows.

    Usage::

        with locked_json_update(some_json_path) as p:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["items"].append(new_item)
            p.write_text(json.dumps(data, indent=2) + "\\n", encoding="utf-8")
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.touch(exist_ok=True)

    if sys.platform == "win32":
        import msvcrt

        with open(lock_path, "r+b") as lock_fd:
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield path
            finally:
                lock_fd.seek(0)
                msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        with open(lock_path, "r") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                yield path
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
