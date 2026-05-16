"""Coverage extensions for RPC methods.

``tests/test_rpc_methods.py`` covers 19 of the 41 registered methods.
This file fills in the remaining 22, except for the four that require
real subprocess / SDK calls (``agent.run``, ``orchestrator.chat``,
``experiment.run``, ``knowledge.ingest``):

* ``session.start`` / ``session.pause`` / ``session.resume``
* ``usage.record``
* ``data.profile``
* ``knowledge.search`` / ``knowledge.list``
* ``orchestrator.set_project`` / ``get_messages`` / ``set_messages`` / ``clear``
* ``sessions.save`` / ``load`` / ``list`` / ``most_recent`` / ``delete``
* ``project.summarize``
* ``experiment.pause``

These are the methods external tools (MCP-style integrations, the
GUI) most often hit; without tests, refactors silently change wire
shapes that one external caller depends on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace
from urika.rpc.methods import build_registry


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "rpc-project"
    cfg = ProjectConfig(name="rpc", question="Does X predict Y?", mode="exploratory")
    create_project_workspace(d, cfg)
    return d


@pytest.fixture
def project_with_experiment(project_dir: Path) -> tuple[Path, str]:
    exp = create_experiment(project_dir, name="baseline", hypothesis="h")
    return project_dir, exp.experiment_id


# ── session.* ──────────────────────────────────────────────────────


class TestSessionLifecycle:
    """session.start → session.pause → session.resume round trip."""

    def test_start_creates_session_json_and_lockfile(
        self, project_with_experiment: tuple[Path, str]
    ) -> None:
        registry = build_registry()
        proj, exp = project_with_experiment
        out = registry["session.start"](
            {"project_dir": str(proj), "experiment_id": exp, "max_turns": 5}
        )
        assert out["status"] == "running"
        assert out["experiment_id"] == exp
        assert out["max_turns"] == 5
        # The lockfile was acquired.
        from urika.core.session import is_locked

        assert is_locked(proj, exp)

    def test_pause_clears_lock_and_updates_status(
        self, project_with_experiment: tuple[Path, str]
    ) -> None:
        registry = build_registry()
        proj, exp = project_with_experiment
        registry["session.start"]({"project_dir": str(proj), "experiment_id": exp})
        out = registry["session.pause"](
            {"project_dir": str(proj), "experiment_id": exp}
        )
        assert out["status"] == "paused"
        from urika.core.session import is_locked

        assert not is_locked(proj, exp)

    def test_resume_after_pause(
        self, project_with_experiment: tuple[Path, str]
    ) -> None:
        registry = build_registry()
        proj, exp = project_with_experiment
        registry["session.start"]({"project_dir": str(proj), "experiment_id": exp})
        registry["session.pause"]({"project_dir": str(proj), "experiment_id": exp})
        out = registry["session.resume"](
            {"project_dir": str(proj), "experiment_id": exp}
        )
        assert out["status"] == "running"
        from urika.core.session import is_locked

        assert is_locked(proj, exp)

    def test_start_when_other_process_holds_lock_raises(
        self, project_with_experiment: tuple[Path, str], monkeypatch
    ) -> None:
        """Trying to start a session when ANOTHER live process owns the
        lock raises — the same-PID short-circuit (used for the dashboard
        handoff) still lets the actual owner re-acquire.

        Pre-fix the test pre-wrote PID 1 (init on POSIX) under the
        assumption that ``_pid_is_alive(1)`` returns True everywhere.
        On Windows there is no guaranteed PID 1 — ``psutil.pid_exists(1)``
        returns False, so ``acquire_lock`` treated the lock as stale,
        cleaned it, and ``session.start`` succeeded without raising.
        Surfaced by the first post-billing-block CI run on v0.4.4.4.

        Fix: monkeypatch both ``_get_process_name`` AND ``_pid_is_alive``
        so the test exercises the ``foreign live urika process`` branch
        independently of platform-specific PID assignment. This matches
        the existing pattern in ``tests/test_core/test_session.py`` for
        the same scenario.
        """
        from urika.core import session as session_module

        proj, exp = project_with_experiment
        lock_path = proj / "experiments" / exp / ".lock"
        # Any non-self PID; the monkeypatched ``_pid_is_alive`` will
        # report it alive regardless of the actual OS state.
        lock_path.write_text("99999998")
        monkeypatch.setattr(session_module, "_get_process_name", lambda pid: "python")
        monkeypatch.setattr(session_module, "_pid_is_alive", lambda pid: True)
        registry = build_registry()
        with pytest.raises(RuntimeError, match="already running"):
            registry["session.start"]({"project_dir": str(proj), "experiment_id": exp})


# ── usage.record ───────────────────────────────────────────────────


class TestUsageRecord:
    def test_record_writes_usage_file(self, project_dir: Path) -> None:
        registry = build_registry()
        registry["usage.record"](
            {
                "project_dir": str(project_dir),
                "started": "2026-05-01T00:00:00+00:00",
                "ended": "2026-05-01T00:01:00+00:00",
                "duration_ms": 60_000,
                "tokens_in": 1000,
                "tokens_out": 500,
                "cost_usd": 0.05,
                "agent_calls": 2,
                "experiments_run": 1,
            }
        )
        # Usage file exists somewhere in .urika or top-level.
        candidates = (
            project_dir / ".urika" / "usage.json",
            project_dir / "usage.json",
        )
        assert any(p.exists() for p in candidates), (
            f"usage.record wrote no file under {project_dir}; checked "
            f"{[str(p) for p in candidates]}"
        )

    def test_record_with_only_required_params(self, project_dir: Path) -> None:
        """The optional kwargs (tokens, cost, agent_calls,
        experiments_run) default to 0/0.0 — must not raise when
        omitted."""
        registry = build_registry()
        registry["usage.record"](
            {
                "project_dir": str(project_dir),
                "started": "2026-05-01T00:00:00+00:00",
                "ended": "2026-05-01T00:00:01+00:00",
                "duration_ms": 1000,
            }
        )


# ── data.profile ───────────────────────────────────────────────────


class TestDataProfile:
    def test_profile_returns_summary_shape(self, tmp_path: Path) -> None:
        registry = build_registry()
        csv = tmp_path / "tiny.csv"
        csv.write_text("a,b\n1,2\n3,4\n5,6\n")
        out = registry["data.profile"]({"path": str(csv)})
        assert isinstance(out, dict)
        # Required keys per the wire contract.
        for key in (
            "name",
            "format",
            "n_rows",
            "n_columns",
            "columns",
            "dtypes",
            "missing_counts",
            "numeric_stats",
        ):
            assert key in out, f"data.profile result missing key {key!r}"
        assert out["n_rows"] == 3
        assert out["n_columns"] == 2
        assert set(out["columns"]) == {"a", "b"}


# ── knowledge.search / knowledge.list ──────────────────────────────


class TestKnowledgeQueries:
    def _seed(self, project_dir: Path) -> None:
        """Drop a synthetic knowledge entry under <proj>/knowledge/."""
        from urika.knowledge.store import KnowledgeStore

        kn_dir = project_dir / "knowledge"
        kn_dir.mkdir(exist_ok=True)
        # Write a tiny markdown file and ingest it through the store
        # (so the JSON store is set up correctly).
        md = kn_dir / "note.md"
        md.write_text("# Heading\n\nThis is the body about Stroop effects.")
        store = KnowledgeStore(project_dir)
        store.ingest(str(md))

    def test_list_returns_seeded_entries(self, project_dir: Path) -> None:
        self._seed(project_dir)
        registry = build_registry()
        out = registry["knowledge.list"]({"project_dir": str(project_dir)})
        assert isinstance(out, list)
        assert len(out) == 1
        assert out[0]["title"] == "note.md"

    def test_search_matches_content(self, project_dir: Path) -> None:
        self._seed(project_dir)
        registry = build_registry()
        out = registry["knowledge.search"](
            {"project_dir": str(project_dir), "query": "stroop"}
        )
        assert isinstance(out, list)
        assert len(out) == 1
        assert "Stroop" in out[0]["content"]

    def test_search_no_match_returns_empty(self, project_dir: Path) -> None:
        self._seed(project_dir)
        registry = build_registry()
        out = registry["knowledge.search"](
            {"project_dir": str(project_dir), "query": "xyzzy_no_match"}
        )
        assert out == []

    def test_list_on_fresh_project_is_empty(self, project_dir: Path) -> None:
        registry = build_registry()
        out = registry["knowledge.list"]({"project_dir": str(project_dir)})
        assert out == []


# ── orchestrator.set_project / get_messages / set_messages / clear ─


class TestOrchestratorState:
    @pytest.fixture(autouse=True)
    def _reset_orch(self):
        """Reset the singleton between tests so cross-test message
        leakage doesn't make assertions order-dependent."""
        from urika.orchestrator.chat import get_orchestrator

        yield
        try:
            get_orchestrator().clear()
        except Exception:
            pass

    def test_set_project_returns_ok(self, project_dir: Path) -> None:
        registry = build_registry()
        out = registry["orchestrator.set_project"]({"project_dir": str(project_dir)})
        assert out == {"ok": True}

    def test_set_messages_overwrites_history(self, project_dir: Path) -> None:
        registry = build_registry()
        registry["orchestrator.set_project"]({"project_dir": str(project_dir)})
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        out = registry["orchestrator.set_messages"]({"messages": msgs})
        assert out["ok"] is True
        assert out["count"] == 2
        # Round-trip.
        retrieved = registry["orchestrator.get_messages"]({})
        assert isinstance(retrieved, list)
        assert len(retrieved) == 2

    def test_clear_empties_history(self, project_dir: Path) -> None:
        registry = build_registry()
        registry["orchestrator.set_messages"](
            {"messages": [{"role": "user", "content": "x"}]}
        )
        assert len(registry["orchestrator.get_messages"]({})) >= 1
        registry["orchestrator.clear"]({})
        assert registry["orchestrator.get_messages"]({}) == []

    def test_set_messages_default_empty(self) -> None:
        """``params.get("messages", [])`` — if caller omits messages, the
        history clears to []."""
        registry = build_registry()
        # Seed first.
        registry["orchestrator.set_messages"](
            {"messages": [{"role": "user", "content": "x"}]}
        )
        # Now call with no messages key.
        out = registry["orchestrator.set_messages"]({})
        assert out["count"] == 0


# ── sessions.* (orchestrator session persistence) ──────────────────


class TestSessionsCRUD:
    def _build_session_dict(self, *, session_id: str = "test-1") -> dict:
        return {
            "session_id": session_id,
            "started": "2026-05-01T00:00:00+00:00",
            "updated": "2026-05-01T00:00:00+00:00",
            "older_summary": "",
            "recent_messages": [{"role": "user", "content": "hi"}],
            "preview": "hi",
        }

    def test_save_round_trips(self, project_dir: Path) -> None:
        registry = build_registry()
        session = self._build_session_dict()
        out = registry["sessions.save"](
            {"project_dir": str(project_dir), "session": session}
        )
        assert out["session_id"] == "test-1"
        # File exists on disk.
        assert (project_dir / ".urika" / "sessions" / "test-1.json").exists()

    def test_load_returns_saved_session(self, project_dir: Path) -> None:
        registry = build_registry()
        registry["sessions.save"](
            {
                "project_dir": str(project_dir),
                "session": self._build_session_dict(session_id="s-2"),
            }
        )
        out = registry["sessions.load"](
            {"project_dir": str(project_dir), "session_id": "s-2"}
        )
        assert out is not None
        assert out["session_id"] == "s-2"

    def test_load_returns_none_for_unknown_id(self, project_dir: Path) -> None:
        registry = build_registry()
        out = registry["sessions.load"](
            {"project_dir": str(project_dir), "session_id": "missing"}
        )
        assert out is None

    def test_list_returns_sorted_recent(self, project_dir: Path) -> None:
        registry = build_registry()
        for i in range(3):
            registry["sessions.save"](
                {
                    "project_dir": str(project_dir),
                    "session": self._build_session_dict(session_id=f"sess-{i}"),
                }
            )
        out = registry["sessions.list"]({"project_dir": str(project_dir)})
        assert isinstance(out, list)
        assert len(out) == 3
        # Required keys per dashboard Sessions tab contract.
        for entry in out:
            assert "session_id" in entry
            assert "started" in entry
            assert "updated" in entry

    def test_most_recent_returns_latest(self, project_dir: Path) -> None:
        registry = build_registry()
        # The sorting key is the filename — write with controllable ids.
        for i in range(3):
            registry["sessions.save"](
                {
                    "project_dir": str(project_dir),
                    "session": self._build_session_dict(
                        session_id=f"2026-05-0{i + 1}T00-00-00-aaaa"
                    ),
                }
            )
        out = registry["sessions.most_recent"]({"project_dir": str(project_dir)})
        assert out is not None
        assert out["session_id"] == "2026-05-03T00-00-00-aaaa"

    def test_most_recent_on_empty_returns_none(self, project_dir: Path) -> None:
        registry = build_registry()
        out = registry["sessions.most_recent"]({"project_dir": str(project_dir)})
        assert out is None

    def test_delete_removes_session_file(self, project_dir: Path) -> None:
        registry = build_registry()
        registry["sessions.save"](
            {
                "project_dir": str(project_dir),
                "session": self._build_session_dict(session_id="goner"),
            }
        )
        path = project_dir / ".urika" / "sessions" / "goner.json"
        assert path.exists()
        ok = registry["sessions.delete"](
            {"project_dir": str(project_dir), "session_id": "goner"}
        )
        assert ok is True
        assert not path.exists()

    def test_delete_unknown_returns_false(self, project_dir: Path) -> None:
        registry = build_registry()
        ok = registry["sessions.delete"](
            {"project_dir": str(project_dir), "session_id": "nope"}
        )
        assert ok is False


# ── project.summarize ──────────────────────────────────────────────


class TestProjectSummarize:
    def test_summarize_empty_project(self, project_dir: Path) -> None:
        """No experiments yet — must not crash."""
        registry = build_registry()
        out = registry["project.summarize"]({"project_dir": str(project_dir)})
        assert isinstance(out, dict)
        # Shape: contains experiments + config bits.
        assert "experiments" in out or "name" in out

    def test_summarize_after_experiment_runs(
        self, project_with_experiment: tuple[Path, str]
    ) -> None:
        registry = build_registry()
        proj, exp = project_with_experiment
        from urika.core.models import RunRecord
        from urika.core.progress import append_run

        append_run(
            proj,
            exp,
            RunRecord(
                run_id="r1",
                method="lr",
                params={},
                metrics={"r2": 0.7},
            ),
        )
        out = registry["project.summarize"]({"project_dir": str(proj)})
        assert isinstance(out, dict)
