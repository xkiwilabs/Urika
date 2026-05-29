"""Single source of truth for ANSI escape stripping (CSI/OSC/Fe/Fp).

Previously the regex lived in two places that drifted apart: the run-log
tee (``orchestrator/run_log.py``) hardened it to cover four ECMA-48 escape
families after a Windows run accumulated ~344 MB of ANSI in ``run.log``
(ThinkingPanel cursor save/restore frames at ~8 fps), while the TUI capture
path kept a CSI-only regex that still leaked ``\\x1b7`` / ``\\x1b8`` and OSC
bytes. Both now share this one helper.

The pattern covers four escape families:
  * CSI:  ESC [ <params> <final>      e.g. ESC [20;1H, ESC [36m
  * OSC:  ESC ] <text> BEL|ESC \\      e.g. window-title sets (defensive)
  * Fe :  ESC <0x40-0x5F>              e.g. ESC M, ESC D
  * Fp :  ESC <0x30-0x3F>              e.g. ESC 7 (DECSC), ESC 8 (DECRC)
Without the Fp branch, ``\\x1b7`` / ``\\x1b8`` slip through and the digit
bytes survive — that was the original log-pollution miss.
"""

from __future__ import annotations

import re

_ANSI_RE = re.compile(
    r"\x1B"
    r"(?:"
    r"\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\][^\x07\x1B]*(?:\x07|\x1B\\)"  # OSC, terminated by BEL or ESC \
    r"|[@-Z\\-_]"  # Fe (single-byte C1 equivalents)
    r"|[0-?]"  # Fp (private use, incl. DECSC/DECRC)
    r")"
)


def strip_ansi(data: str) -> str:
    """Remove all ANSI escape sequences (CSI/OSC/Fe/Fp) from ``data``.

    Cheap fast-path: no ESC byte → return unchanged. Most writes are plain
    text; the regex only fires for ThinkingPanel / Spinner frames.
    """
    if "\x1b" not in data:
        return data
    return _ANSI_RE.sub("", data)
