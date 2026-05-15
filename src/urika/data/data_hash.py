"""SHA-256 hashing for project data files (v0.4 Track 4).

Closes a long-standing reproducibility gap: ``urika new`` profiles
the data file but never records a content hash. If the user re-runs
an experiment after the data has been edited (a real risk during
analysis), there's no record. v0.4 stores ``sha256`` of every
registered data file in the project's ``urika.toml`` under
``[project.data_hashes]`` and re-checks on each ``urika run``;
mismatches surface in ``urika status`` and the run's
``progress.json``.

This module is intentionally separate from ``data/loader.py`` so
hashing has no `pandas` / `numpy` import cost — `urika status`
shouldn't pull the analytical stack just to verify file integrity.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


_CHUNK_SIZE = 65536  # 64 KiB — small enough to handle multi-GB files
# without memory pressure, big enough to keep
# syscall overhead negligible.


def hash_data_file(path: Path) -> str:
    """Streaming SHA-256 of *path*.

    Returns the hex digest as a string. Returns an empty string when
    the path doesn't exist or can't be read (so the caller can record
    "missing" / "unreadable" without raising). Symlinks are followed.
    """
    if not path.exists():
        return ""
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while True:
                chunk = f.read(_CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def hash_data_files(paths: Iterable[Path | str]) -> dict[str, str]:
    """Map ``{relative_path_str: sha256}`` for an iterable of paths.

    The keys are the input paths verbatim (not resolved), so callers
    can write the result straight into TOML without losing the
    user's chosen representation. Empty hashes (missing / unreadable
    files) are still included so the absence is recorded.
    """
    out: dict[str, str] = {}
    for raw in paths:
        p = Path(raw)
        out[str(raw)] = hash_data_file(p)
    return out


def detect_drift(
    recorded: dict[str, str],
    paths: Iterable[Path | str],
) -> list[dict[str, str]]:
    """Compare recorded hashes to current file state.

    Returns a list of drift records, one per path that doesn't match
    its recorded hash. Each record has keys ``path``, ``old_hash``,
    ``new_hash``. Files missing from *recorded* are treated as new
    (not drifted). Files in *recorded* that are missing on disk
    surface with ``new_hash`` = ``""``.
    """
    drifted: list[dict[str, str]] = []
    for raw in paths:
        key = str(raw)
        old = recorded.get(key, "")
        if not old:
            # Not previously recorded → no drift to report.
            continue
        new = hash_data_file(Path(raw))
        if new != old:
            drifted.append({"path": key, "old_hash": old, "new_hash": new})
    return drifted
