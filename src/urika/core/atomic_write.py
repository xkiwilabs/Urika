"""Atomic file writes with crash-safe rename.

Wraps the temp-file + ``os.replace`` pattern that every JSON state file
in Urika needs but rarely got. A crash mid-write previously left
truncated JSON behind (registry, sessions, progress, criteria, methods,
usage, advisor history); now the original file stays intact unless the
new contents made it all the way to disk.

POSIX guarantees ``os.replace`` is atomic when source and target are on
the same filesystem — which they are by construction (the temp file is
a sibling of the target). Windows offers the same guarantee for same-
volume replaces. On power loss the parent directory is fsynced so the
rename survives.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any


def write_text_atomic(path: Path, body: str, *, mode: int = 0o644) -> None:
    """Write *body* to *path* atomically with the requested file *mode*.

    The file is created via ``O_CREAT|O_EXCL|O_WRONLY`` with the mode
    baked in by ``os.open``, closing the write-then-chmod race that the
    previous ``write_text`` + ``chmod`` pattern left open for secrets
    files. The parent directory is ``mkdir(parents=True)``ed first.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def write_json_atomic(
    path: Path,
    data: Any,
    *,
    mode: int = 0o644,
    indent: int = 2,
) -> None:
    """JSON-encode *data* and write to *path* atomically with trailing newline."""
    body = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    write_text_atomic(path, body, mode=mode)
