"""Tests for reading run records from <experiment>/labbook/run-*.json files.

Modern Claude task agents often write run records to disk via Bash tool
calls instead of (or in addition to) emitting them as inline ```json
blocks. The orchestrator merges these with any text-parsed records so a
tools-only agent still gets its work captured in the leaderboard.

This test module covers the v0.5.0.2 fix that closes the "empty
leaderboard despite real work" gap surfaced by the open-mode e2e smoke
on 2026-05-31.
"""

from __future__ import annotations

import json
from pathlib import Path


def _seed(exp_dir: Path, name: str, record: dict) -> Path:
    (exp_dir / "labbook").mkdir(parents=True, exist_ok=True)
    path = exp_dir / "labbook" / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_read_labbook_picks_up_single_record(tmp_path):
    from urika.orchestrator.parsing import read_labbook_run_records

    exp = tmp_path / "exp-001"
    _seed(
        exp,
        "run-001-paired-t.json",
        {
            "run_id": "run-001",
            "method": "paired-t-test",
            "params": {"alpha": 0.05},
            "metrics": {"t": 18.0, "p": 1e-37},
        },
    )

    records = read_labbook_run_records(exp)

    assert len(records) == 1
    assert records[0].run_id == "run-001"
    assert records[0].method == "paired-t-test"
    assert records[0].metrics == {"t": 18.0, "p": 1e-37}
    assert records[0].params == {"alpha": 0.05}


def test_read_labbook_sorts_by_filename(tmp_path):
    """Sorted iteration so run-001 lands before run-002 etc."""
    from urika.orchestrator.parsing import read_labbook_run_records

    exp = tmp_path / "exp-001"
    _seed(
        exp,
        "run-002-wilcoxon.json",
        {"run_id": "run-002", "method": "w", "metrics": {}},
    )
    _seed(
        exp, "run-001-paired.json", {"run_id": "run-001", "method": "p", "metrics": {}}
    )

    records = read_labbook_run_records(exp)
    assert [r.run_id for r in records] == ["run-001", "run-002"]


def test_read_labbook_ignores_malformed_json(tmp_path):
    from urika.orchestrator.parsing import read_labbook_run_records

    exp = tmp_path / "exp"
    (exp / "labbook").mkdir(parents=True)
    (exp / "labbook" / "run-001-broken.json").write_text("{not valid json")
    _seed(exp, "run-002-good.json", {"run_id": "run-002", "method": "m", "metrics": {}})

    records = read_labbook_run_records(exp)
    assert [r.run_id for r in records] == ["run-002"]


def test_read_labbook_skips_record_without_required_fields(tmp_path):
    """Same field-presence + type checks as parse_run_records."""
    from urika.orchestrator.parsing import read_labbook_run_records

    exp = tmp_path / "exp"
    _seed(exp, "run-001-no-metrics.json", {"run_id": "r1", "method": "x"})  # no metrics
    _seed(
        exp,
        "run-002-bad-metrics.json",
        {"run_id": "r2", "method": "x", "metrics": "not-a-dict"},
    )
    _seed(exp, "run-003-ok.json", {"run_id": "r3", "method": "x", "metrics": {"a": 1}})

    records = read_labbook_run_records(exp)
    assert [r.run_id for r in records] == ["r3"]


def test_read_labbook_empty_when_no_labbook_dir(tmp_path):
    from urika.orchestrator.parsing import read_labbook_run_records

    assert read_labbook_run_records(tmp_path / "nonexistent") == []
    (tmp_path / "exp").mkdir()  # exists but no labbook/
    assert read_labbook_run_records(tmp_path / "exp") == []


def test_read_labbook_ignores_non_run_files(tmp_path):
    """Only ``run-*.json`` is considered. notes.md, summary.md, etc. ignored."""
    from urika.orchestrator.parsing import read_labbook_run_records

    exp = tmp_path / "exp"
    (exp / "labbook").mkdir(parents=True)
    (exp / "labbook" / "notes.md").write_text("# notes\n")
    (exp / "labbook" / "summary.md").write_text("# summary\n")
    (exp / "labbook" / "narrative.md").write_text("# narrative\n")
    _seed(exp, "run-001.json", {"run_id": "r1", "method": "x", "metrics": {}})

    records = read_labbook_run_records(exp)
    assert [r.run_id for r in records] == ["r1"]
