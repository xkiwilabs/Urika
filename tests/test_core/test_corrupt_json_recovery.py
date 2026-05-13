"""Defensive corrupt-JSON fallbacks across the project metadata files.

Every loader in the project metadata path has a ``try/except
JSONDecodeError`` boundary that logs a warning and returns a default
shape (empty registry, empty runs, empty totals, no experiments) so a
single bad write — an external editor, a `chmod 000`, a crashed write,
a sub-agent corruption — doesn't crash the whole tool.

Only ``method_registry`` directly tests this path (its
``TestMalformedMethodsJson``). This file ports that pattern to the
four other files that share the same defensive try/except:
``registry.py`` (~/.urika/projects.json), ``progress.py``
(experiments/*/progress.json), ``usage.py`` (.urika/usage.json),
``experiment.py`` (list/load).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── ~/.urika/projects.json ─────────────────────────────────────


class TestProjectRegistryCorruptJson:
    def _build(self, tmp_path: Path, monkeypatch, payload: str):
        home = tmp_path / "home"
        home.mkdir()
        (home / "projects.json").write_text(payload, encoding="utf-8")
        monkeypatch.setenv("URIKA_HOME", str(home))
        from urika.core.registry import ProjectRegistry

        return ProjectRegistry()

    def test_corrupt_json_starts_fresh(self, tmp_path, monkeypatch):
        r = self._build(tmp_path, monkeypatch, "{this is not json")
        assert r.list_all() == {}

    def test_non_object_top_level_starts_fresh(self, tmp_path, monkeypatch):
        r = self._build(tmp_path, monkeypatch, "[1, 2, 3]")
        # A list at top-level is invalid for a registry; loader logs +
        # treats as empty (or accepts but list_all coerces). Either way,
        # it must not crash.
        assert isinstance(r.list_all(), dict)

    def test_register_after_corrupt_persists_clean(self, tmp_path, monkeypatch):
        r = self._build(tmp_path, monkeypatch, "garbage{{{")
        # Must not raise — pre-fix this KeyError'd on _projects.
        r.register("alpha", tmp_path / "alpha")
        assert "alpha" in r.list_all()
        # Next instance reads back cleanly.
        from urika.core.registry import ProjectRegistry

        r2 = ProjectRegistry()
        assert "alpha" in r2.list_all()


# ── experiments/<id>/progress.json ─────────────────────────────


class TestProgressCorruptJson:
    def _exp(self, tmp_path: Path):
        proj = tmp_path / "proj"
        (proj / "experiments" / "exp-001").mkdir(parents=True)
        return proj, "exp-001"

    def test_corrupt_returns_default_shape(self, tmp_path):
        from urika.core.progress import load_progress

        proj, exp = self._exp(tmp_path)
        (proj / "experiments" / exp / "progress.json").write_text(
            "not json at all", encoding="utf-8"
        )
        data = load_progress(proj, exp)
        assert data == {"runs": [], "status": "pending"}

    def test_missing_returns_default_shape(self, tmp_path):
        from urika.core.progress import load_progress

        proj, exp = self._exp(tmp_path)
        # No file written.
        data = load_progress(proj, exp)
        assert data == {"runs": [], "status": "pending"}

    def test_append_run_after_corrupt_recovers(self, tmp_path):
        """A run appended after a corrupt file overwrites with a clean
        shape — pre-fix this would have raised."""
        from urika.core.models import RunRecord
        from urika.core.progress import append_run, load_progress

        proj, exp = self._exp(tmp_path)
        (proj / "experiments" / exp / "progress.json").write_text(
            "{not valid", encoding="utf-8"
        )
        append_run(
            proj,
            exp,
            RunRecord(run_id="r1", method="m", params={}, metrics={"r2": 0.5}),
        )
        data = load_progress(proj, exp)
        assert len(data["runs"]) == 1
        assert data["runs"][0]["run_id"] == "r1"


# ── usage.json ─────────────────────────────────────────────────


class TestUsageCorruptJson:
    def test_corrupt_returns_empty_totals(self, tmp_path):
        from urika.core.usage import load_usage

        (tmp_path / ".urika").mkdir()
        (tmp_path / ".urika" / "usage.json").write_text(
            "{this is broken", encoding="utf-8"
        )
        data = load_usage(tmp_path)
        # Must return a default-shaped dict with sessions=[] + totals.
        assert isinstance(data, dict)
        assert data.get("sessions", []) == []
        assert "totals" in data

    def test_missing_returns_empty_totals(self, tmp_path):
        from urika.core.usage import load_usage

        # No .urika/usage.json on disk.
        data = load_usage(tmp_path)
        assert isinstance(data, dict)
        assert data.get("sessions", []) == []

    def test_record_after_corrupt_writes_clean(self, tmp_path):
        from urika.core.usage import load_usage, record_session

        (tmp_path / ".urika").mkdir()
        (tmp_path / ".urika" / "usage.json").write_text("garbage", encoding="utf-8")
        record_session(
            tmp_path,
            started="2026-01-01T00:00:00",
            ended="2026-01-01T00:00:01",
            duration_ms=1000,
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.001,
            agent_calls=1,
            experiments_run=0,
        )
        data = load_usage(tmp_path)
        assert len(data["sessions"]) == 1
        assert data["totals"]["total_agent_calls"] == 1


# ── experiments/<id>/experiment.json + list_experiments ────────


class TestExperimentLoaderCorruptJson:
    def _proj(self, tmp_path: Path) -> Path:
        proj = tmp_path / "p"
        (proj / "experiments").mkdir(parents=True)
        return proj

    def test_list_experiments_skips_corrupt_entry(self, tmp_path):
        from urika.core.experiment import list_experiments

        proj = self._proj(tmp_path)
        # One good, one corrupt.
        (proj / "experiments" / "exp-001").mkdir()
        (proj / "experiments" / "exp-001" / "experiment.json").write_text(
            json.dumps({"experiment_id": "exp-001", "name": "ok", "hypothesis": "h"}),
            encoding="utf-8",
        )
        (proj / "experiments" / "exp-002").mkdir()
        (proj / "experiments" / "exp-002" / "experiment.json").write_text(
            "{not json", encoding="utf-8"
        )
        # Must not raise; the good experiment still loads, the corrupt
        # one is silently skipped (logged at WARNING).
        exps = list_experiments(proj)
        ids = {e.experiment_id for e in exps}
        assert "exp-001" in ids
        assert "exp-002" not in ids

    def test_progress_with_non_dict_run_records_loads_cleanly(self, tmp_path) -> None:
        """A non-dict entry in progress.json's ``runs`` list (a
        sub-agent corruption, an external editor) — load_progress
        must return the file without crashing. Downstream consumers
        (the page renderers in v0.4.4.1) defend against per-run
        garbage."""
        from urika.core.progress import load_progress

        proj = tmp_path / "p"
        (proj / "experiments" / "exp-001").mkdir(parents=True)
        (proj / "experiments" / "exp-001" / "progress.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "runs": [
                        {"run_id": "ok", "metrics": {"r2": 0.5}},
                        "not a dict",
                        42,
                        None,
                        {"metrics": ["wrong shape"]},
                    ],
                }
            )
        )
        # Must not raise.
        data = load_progress(proj, "exp-001")
        assert isinstance(data, dict)
        assert isinstance(data.get("runs"), list)

    def test_criteria_corrupt_json_via_load_criteria_history(self, tmp_path) -> None:
        """criteria.py has the same try/except boundary —
        load_criteria_history must return an empty list on corrupt JSON
        rather than crashing the orchestrator."""
        from urika.core.criteria import load_criteria_history

        (tmp_path / "criteria.json").write_text("{this is broken")
        hist = load_criteria_history(tmp_path)
        assert hist == []

    def test_criteria_non_dict_version_filtered(self, tmp_path) -> None:
        """A version entry that isn't a dict — defensive loader keeps
        going."""
        from urika.core.criteria import load_criteria_history

        (tmp_path / "criteria.json").write_text(
            json.dumps(
                {
                    "versions": [
                        {"version": 1, "criteria": {"r2": ">= 0.5"}},
                        "not a dict",
                        None,
                        42,
                    ]
                }
            )
        )
        hist = load_criteria_history(tmp_path)
        # Either filtered (best) or all returned but the good one is present.
        # Contract: must not raise.
        assert isinstance(hist, list)

    def test_load_experiment_with_corrupt_raises_filenotfound(self, tmp_path):
        """``load_experiment`` for an individual experiment with corrupt
        JSON converts to FileNotFoundError (same surface as a missing
        config). Caller-side is expected to catch FileNotFoundError to
        mean 'this experiment isn't usable' — pinning the contract."""
        from urika.core.experiment import load_experiment

        proj = self._proj(tmp_path)
        (proj / "experiments" / "exp-001").mkdir()
        (proj / "experiments" / "exp-001" / "experiment.json").write_text(
            "garbage", encoding="utf-8"
        )
        with pytest.raises(FileNotFoundError):
            load_experiment(proj, "exp-001")
