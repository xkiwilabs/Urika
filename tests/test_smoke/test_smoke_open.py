"""Integration: open-mode end-to-end smoke via the shell harness.

v0.4.2 M16 — pre-fix the only path to run the open-mode E2E smoke
was the shell script ``dev/scripts/smoke-v04-e2e-open.sh`` invoked
manually before a release. There was no way for ``pytest`` to find
or report on the run. This wrapper marks it as a real
``@pytest.mark.integration`` case so CI can opt in via
``pytest -m integration``.

The test is deliberately minimal: it just shells out to the
existing harness and asserts a clean exit. Full assertions live
in the harness itself (a brittle pytest re-implementation would
duplicate hundreds of lines of bash for no benefit).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = REPO_ROOT / "dev" / "scripts" / "smoke-v04-e2e-open.sh"


@pytest.mark.integration
def test_smoke_open_mode() -> None:
    """Run the open-mode smoke harness end-to-end.

    Skipped automatically when the harness or bash is unavailable.
    Set ``URIKA_SKIP_SMOKE=1`` to skip even when bash is present
    (for the dev's local fast loop).
    """
    if os.environ.get("URIKA_SKIP_SMOKE"):
        pytest.skip("URIKA_SKIP_SMOKE set in environment")
    if not SMOKE_SCRIPT.exists():
        pytest.skip(f"Smoke harness not present at {SMOKE_SCRIPT}")
    if not shutil.which("bash"):
        pytest.skip("bash not on PATH")

    result = subprocess.run(
        ["bash", str(SMOKE_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        # 50-minute cap matches the harness's own timeout — a real run
        # is 10-15 min on a warm cache.
        timeout=3000,
    )
    if result.returncode != 0:
        # Surface the harness's own log on failure rather than just
        # the return code — the harness writes detail to stderr.
        pytest.fail(
            f"smoke-v04-e2e-open.sh exited {result.returncode}\n"
            f"--- stderr ---\n{result.stderr}\n"
            f"--- stdout (last 4kb) ---\n{result.stdout[-4096:]}"
        )
