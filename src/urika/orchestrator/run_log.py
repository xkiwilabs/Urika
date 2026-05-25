"""Tee stdout to ``<exp>/run.log`` so the dashboard's SSE log tailer
has a single, on-disk source of truth for live output.

Used by:

- ``urika run`` (CLI) — wraps the orchestrator call.
- The dashboard (Phase 6) — spawns a subprocess; the daemon thread
  reads the subprocess's stdout and writes to ``run.log`` directly.
- The TUI — when run from inside the TUI, the TUI's OutputCapture is
  already in play; ``OrchestratorLogger`` composes safely with it
  because it just adds an extra write target.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import IO, Any

# ANSI stripping is shared with the TUI capture path via a single source of
# truth (``urika.core.ansi``). Pre-fix, ``ThinkingPanel`` wrote raw ANSI
# (cursor save/restore, scroll-region set, colour codes) via
# ``sys.stdout.write`` at ~8 frames/second — every frame went straight
# through ``_Tee`` to ``run.log``. A 26-hour Windows run accumulated
# ~344 MB of ANSI escapes in the log, and the constantly-ticking mtime made
# monitoring tools think the run was still doing real work when in fact the
# agent had hung mid-stream. The terminal needs the escapes; the log file
# does not. The hardened CSI/OSC/Fe/Fp regex (incl. DECSC/DECRC) now lives
# in ``urika.core.ansi`` so the TUI panel can't regress to CSI-only.
from urika.core.ansi import strip_ansi as _strip_ansi


class _Tee:
    """Forward writes to two underlying streams (stdout + log file)."""

    def __init__(self, primary: IO[str], log_file: IO[str]) -> None:
        self._primary = primary
        self._log = log_file

    def write(self, data: str) -> int:
        n = self._primary.write(data)
        try:
            clean = _strip_ansi(data)
            if clean:
                self._log.write(clean)
                self._log.flush()
        except Exception:
            # Never break the user-facing stream because of a log-file
            # issue. Stale or read-only filesystems shouldn't kill a run.
            pass
        return n

    def flush(self) -> None:
        self._primary.flush()
        try:
            self._log.flush()
        except Exception:
            pass

    def __getattr__(self, name: str) -> Any:
        # Pass through anything else (isatty, fileno, etc.) to the
        # primary stream so terminal-detection code works as expected.
        return getattr(self._primary, name)


class OrchestratorLogger:
    """Context manager: tee ``sys.stdout`` to ``log_path`` for the duration."""

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path
        self._log_file: IO[str] | None = None
        self._original_stdout: IO[str] | None = None

    def __enter__(self) -> "OrchestratorLogger":
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = open(self._log_path, "a", buffering=1, encoding="utf-8")
        self._original_stdout = sys.stdout
        sys.stdout = _Tee(self._original_stdout, self._log_file)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._original_stdout is not None:
            sys.stdout = self._original_stdout
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
        # Don't suppress exceptions
        return None
