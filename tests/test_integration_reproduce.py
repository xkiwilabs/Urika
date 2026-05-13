"""Integration test: the ``reproduce.sh`` the finalizer is instructed
to write actually runs.

Nothing else in the suite executes a reproduce script — the e2e smoke
only ``pip install``s the agent-generated ``requirements.txt`` (and
only under ``URIKA_SMOKE_REAL``). This builds a tiny project that
matches the finalizer's deliverable layout — ``methods/final_*.py`` +
``requirements.txt`` + a ``reproduce.sh`` following the exact template
in ``agents/roles/prompts/finalizer_system.md`` (venv → activate →
``pip install -r requirements.txt`` → run each final method) — and runs
it end to end, asserting it exits 0 and the method produced its output.

Catches the day the reproduce.sh template (or the assumption that a
``final_*.py`` is runnable as ``python methods/final_x.py --data ...``)
breaks. Marked ``integration`` because it spawns a subprocess and
builds a venv (~few seconds); uses a stdlib-only method + an empty
requirements.txt so it needs no network.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_FINALIZER_PROMPT = (
    Path(__file__).resolve().parent.parent
    / "src" / "urika" / "agents" / "roles" / "prompts" / "finalizer_system.md"
)

# A self-contained final method: loads the CSV, computes a trivial
# statistic, writes a results JSON. Stdlib only — no requirements.
_FINAL_METHOD = '''\
"""Standalone final method (test fixture, mirrors the finalizer's
``methods/final_<name>.py`` deliverable shape)."""
import argparse
import csv
import json
import statistics
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    args = ap.parse_args()
    rows = list(csv.DictReader(open(args.data)))
    ys = [float(r["y"]) for r in rows]
    out = {"n": len(ys), "mean_y": statistics.fmean(ys)}
    Path("results.json").write_text(json.dumps(out))
    print(f"final_demo: wrote results.json {out}")


if __name__ == "__main__":
    main()
'''


def _reproduce_sh_template_body() -> str:
    """Pull the ```` ```bash ```` block under "## Step 6: Write
    reproduce scripts" out of the finalizer prompt — so this test
    breaks if the template the agent is told to write changes."""
    text = _FINALIZER_PROMPT.read_text(encoding="utf-8")
    # The reproduce.sh template is the first ```bash block after the
    # "Write `{project_dir}/reproduce.sh`" line.
    after = text.split("reproduce.sh`", 1)[1]
    m = re.search(r"```bash\s*(.*?)```", after, re.DOTALL)
    assert m is not None, "couldn't find the reproduce.sh ```bash block in the finalizer prompt"
    return m.group(1)


@pytest.mark.skipif(sys.platform == "win32", reason="reproduce.sh is the POSIX variant")
def test_finalizer_reproduce_sh_template_runs(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    (proj / "methods").mkdir(parents=True)
    (proj / "data").mkdir()
    (proj / "data" / "x.csv").write_text("x,y\n1,2.0\n3,4.0\n5,6.0\n")
    (proj / "methods" / "final_demo.py").write_text(_FINAL_METHOD)
    # Empty (comment-only) requirements — `pip install -r` is then a
    # near-instant no-op; the e2e smoke covers "agent deps install".
    (proj / "requirements.txt").write_text("# no third-party deps for this fixture\n")

    # Build reproduce.sh from the prompt's template, uncommenting the
    # "one line per final method" placeholder for our one method.
    body = _reproduce_sh_template_body()
    body = body.replace(
        "# python methods/final_<name>.py --data data/...",
        "python methods/final_demo.py --data data/x.csv",
    )
    (proj / "reproduce.sh").write_text(body)

    # Sanity: the template is shell-valid before we run it.
    syntax = subprocess.run(
        ["bash", "-n", "reproduce.sh"], cwd=proj, capture_output=True, text=True
    )
    assert syntax.returncode == 0, syntax.stderr

    # Run it. (Uses the system python for `python -m venv`; the venv it
    # creates is inside tmp_path so it's cleaned up with the fixture.)
    env = {**os.environ}
    result = subprocess.run(
        ["bash", "reproduce.sh"], cwd=proj, capture_output=True, text=True,
        env=env, timeout=300,
    )
    assert result.returncode == 0, (
        f"reproduce.sh failed (exit {result.returncode}).\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    # The venv was created where the template says.
    assert (proj / ".reproduce-env").is_dir()
    # The final method ran and produced its output.
    assert (proj / "results.json").exists()
    import json as _json

    out = _json.loads((proj / "results.json").read_text())
    assert out["n"] == 3 and out["mean_y"] == pytest.approx(4.0)
    assert "final_demo: wrote results.json" in result.stdout
