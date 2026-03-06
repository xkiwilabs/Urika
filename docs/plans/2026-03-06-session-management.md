# Session Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build experiment orchestration — start/pause/resume/complete lifecycle with lockfile-based concurrency and agent session tracking.

**Architecture:** A single module `src/urika/core/session.py` with pure functions operating on `project_dir` + `experiment_id`. State persisted as `session.json` per experiment. Lockfile (`.lock`) prevents concurrent runs. Follows the same functional pattern as `progress.py`.

**Tech Stack:** Python stdlib (`json`, `dataclasses`, `datetime`, `pathlib`), pytest.

**Reference files:**
- Design: `docs/plans/2026-03-06-session-management-design.md`
- Pattern to follow: `src/urika/core/progress.py` (functional style, JSON persistence)
- Models pattern: `src/urika/core/models.py` (dataclass with to_dict/from_dict)
- Test pattern: `tests/test_core/test_progress.py` (fixtures for project_dir + experiment_id)

---

### Task 1: SessionState dataclass

**Files:**
- Modify: `src/urika/core/models.py`
- Create: `tests/test_core/test_session.py`

**Step 1: Write the failing tests**

Create `tests/test_core/test_session.py`:

```python
"""Tests for session management."""

from __future__ import annotations

from urika.core.models import SessionState


class TestSessionState:
    def test_create_with_required_fields(self) -> None:
        state = SessionState(
            experiment_id="exp-001-baseline",
            status="running",
            started_at="2026-03-06T10:00:00+00:00",
        )
        assert state.experiment_id == "exp-001-baseline"
        assert state.status == "running"
        assert state.started_at == "2026-03-06T10:00:00+00:00"
        assert state.paused_at is None
        assert state.completed_at is None
        assert state.current_turn == 0
        assert state.max_turns is None
        assert state.agent_sessions == {}
        assert state.checkpoint == {}

    def test_create_with_all_fields(self) -> None:
        state = SessionState(
            experiment_id="exp-002",
            status="paused",
            started_at="2026-03-06T10:00:00+00:00",
            paused_at="2026-03-06T11:00:00+00:00",
            current_turn=15,
            max_turns=50,
            agent_sessions={"task_agent": "sess-abc123"},
            checkpoint={"last_suggestion": "try_xgboost"},
        )
        assert state.paused_at == "2026-03-06T11:00:00+00:00"
        assert state.current_turn == 15
        assert state.max_turns == 50
        assert state.agent_sessions["task_agent"] == "sess-abc123"
        assert state.checkpoint["last_suggestion"] == "try_xgboost"

    def test_to_dict(self) -> None:
        state = SessionState(
            experiment_id="exp-001",
            status="running",
            started_at="2026-03-06T10:00:00+00:00",
        )
        d = state.to_dict()
        assert d["experiment_id"] == "exp-001"
        assert d["status"] == "running"
        assert d["current_turn"] == 0
        assert d["agent_sessions"] == {}

    def test_from_dict(self) -> None:
        d = {
            "experiment_id": "exp-001",
            "status": "paused",
            "started_at": "2026-03-06T10:00:00+00:00",
            "paused_at": "2026-03-06T11:00:00+00:00",
            "current_turn": 5,
            "max_turns": 20,
            "agent_sessions": {"evaluator": "sess-xyz"},
            "checkpoint": {},
        }
        state = SessionState.from_dict(d)
        assert state.experiment_id == "exp-001"
        assert state.status == "paused"
        assert state.current_turn == 5
        assert state.agent_sessions["evaluator"] == "sess-xyz"

    def test_from_dict_with_defaults(self) -> None:
        d = {
            "experiment_id": "exp-001",
            "status": "running",
            "started_at": "2026-03-06T10:00:00+00:00",
        }
        state = SessionState.from_dict(d)
        assert state.paused_at is None
        assert state.completed_at is None
        assert state.current_turn == 0
        assert state.max_turns is None
        assert state.agent_sessions == {}
        assert state.checkpoint == {}
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_session.py -v`
Expected: FAIL — `ImportError: cannot import name 'SessionState' from 'urika.core.models'`

**Step 3: Write minimal implementation**

Add to `src/urika/core/models.py` (after `RunRecord` class):

```python
VALID_SESSION_STATUSES = {"running", "paused", "completed", "failed"}


@dataclass
class SessionState:
    """Orchestration state for an active experiment."""

    experiment_id: str
    status: str
    started_at: str
    paused_at: str | None = None
    completed_at: str | None = None
    current_turn: int = 0
    max_turns: int | None = None
    agent_sessions: dict[str, str] = field(default_factory=dict)
    checkpoint: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "status": self.status,
            "started_at": self.started_at,
            "paused_at": self.paused_at,
            "completed_at": self.completed_at,
            "current_turn": self.current_turn,
            "max_turns": self.max_turns,
            "agent_sessions": self.agent_sessions,
            "checkpoint": self.checkpoint,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionState:
        return cls(
            experiment_id=d["experiment_id"],
            status=d["status"],
            started_at=d["started_at"],
            paused_at=d.get("paused_at"),
            completed_at=d.get("completed_at"),
            current_turn=d.get("current_turn", 0),
            max_turns=d.get("max_turns"),
            agent_sessions=d.get("agent_sessions", {}),
            checkpoint=d.get("checkpoint", {}),
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_session.py -v`
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add src/urika/core/models.py tests/test_core/test_session.py
git commit -m "feat(session): add SessionState dataclass"
```

---

### Task 2: Load/save session and locking

**Files:**
- Create: `src/urika/core/session.py`
- Modify: `tests/test_core/test_session.py`

**Step 1: Write the failing tests**

Append to `tests/test_core/test_session.py`. Add these imports at the top:

```python
from pathlib import Path

import pytest

from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig, SessionState
from urika.core.session import (
    acquire_lock,
    is_locked,
    load_session,
    release_lock,
    save_session,
)
from urika.core.workspace import create_project_workspace
```

Add fixtures after imports:

```python
@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test"
    config = ProjectConfig(name="test", question="?", mode="exploratory")
    create_project_workspace(d, config)
    return d


@pytest.fixture
def experiment_id(project_dir: Path) -> str:
    exp = create_experiment(project_dir, name="Test", hypothesis="Test hypothesis")
    return exp.experiment_id
```

Add test classes:

```python
class TestLoadSaveSession:
    def test_load_nonexistent_returns_none(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        assert load_session(project_dir, experiment_id) is None

    def test_save_and_load_roundtrip(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        state = SessionState(
            experiment_id=experiment_id,
            status="running",
            started_at="2026-03-06T10:00:00+00:00",
            current_turn=3,
            agent_sessions={"task_agent": "sess-abc"},
        )
        save_session(project_dir, experiment_id, state)
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.experiment_id == experiment_id
        assert loaded.status == "running"
        assert loaded.current_turn == 3
        assert loaded.agent_sessions["task_agent"] == "sess-abc"

    def test_save_overwrites_previous(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        state1 = SessionState(
            experiment_id=experiment_id,
            status="running",
            started_at="2026-03-06T10:00:00+00:00",
        )
        save_session(project_dir, experiment_id, state1)

        state2 = SessionState(
            experiment_id=experiment_id,
            status="paused",
            started_at="2026-03-06T10:00:00+00:00",
            paused_at="2026-03-06T11:00:00+00:00",
        )
        save_session(project_dir, experiment_id, state2)

        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.status == "paused"


class TestLocking:
    def test_acquire_lock(self, project_dir: Path, experiment_id: str) -> None:
        assert acquire_lock(project_dir, experiment_id) is True
        assert is_locked(project_dir, experiment_id) is True

    def test_acquire_lock_twice_fails(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        acquire_lock(project_dir, experiment_id)
        assert acquire_lock(project_dir, experiment_id) is False

    def test_release_lock(self, project_dir: Path, experiment_id: str) -> None:
        acquire_lock(project_dir, experiment_id)
        release_lock(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is False

    def test_release_nonexistent_lock_is_safe(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        release_lock(project_dir, experiment_id)  # Should not raise

    def test_is_locked_when_no_lock(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        assert is_locked(project_dir, experiment_id) is False
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_session.py::TestLoadSaveSession -v`
Expected: FAIL — `ImportError: cannot import name 'load_session' from 'urika.core.session'`

**Step 3: Write minimal implementation**

Create `src/urika/core/session.py`:

```python
"""Experiment orchestration: start, pause, resume, complete."""

from __future__ import annotations

import json
from pathlib import Path

from urika.core.models import SessionState


def _session_path(project_dir: Path, experiment_id: str) -> Path:
    return project_dir / "experiments" / experiment_id / "session.json"


def _lock_path(project_dir: Path, experiment_id: str) -> Path:
    return project_dir / "experiments" / experiment_id / ".lock"


def load_session(project_dir: Path, experiment_id: str) -> SessionState | None:
    """Load session state, or None if no session.json exists."""
    path = _session_path(project_dir, experiment_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return SessionState.from_dict(data)


def save_session(
    project_dir: Path, experiment_id: str, state: SessionState
) -> None:
    """Persist session state to session.json."""
    path = _session_path(project_dir, experiment_id)
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n")


def acquire_lock(project_dir: Path, experiment_id: str) -> bool:
    """Create .lock file. Returns False if already locked."""
    path = _lock_path(project_dir, experiment_id)
    if path.exists():
        return False
    path.touch()
    return True


def release_lock(project_dir: Path, experiment_id: str) -> None:
    """Remove .lock file."""
    path = _lock_path(project_dir, experiment_id)
    if path.exists():
        path.unlink()


def is_locked(project_dir: Path, experiment_id: str) -> bool:
    """Check if experiment is locked."""
    return _lock_path(project_dir, experiment_id).exists()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_session.py -v`
Expected: 13 PASSED (5 SessionState + 3 load/save + 5 locking)

**Step 5: Commit**

```bash
git add src/urika/core/session.py tests/test_core/test_session.py
git commit -m "feat(session): add load/save session and lockfile management"
```

---

### Task 3: Lifecycle functions (start, pause, resume, complete, fail)

**Files:**
- Modify: `src/urika/core/session.py`
- Modify: `tests/test_core/test_session.py`

**Step 1: Write the failing tests**

Add these imports to the top of `tests/test_core/test_session.py`:

```python
from urika.core.session import (
    acquire_lock,
    complete_session,
    fail_session,
    is_locked,
    load_session,
    pause_session,
    release_lock,
    resume_session,
    save_session,
    start_session,
)
```

Append test classes:

```python
class TestStartSession:
    def test_start_creates_session(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        state = start_session(project_dir, experiment_id)
        assert state.status == "running"
        assert state.experiment_id == experiment_id
        assert state.current_turn == 0
        assert state.started_at != ""

    def test_start_acquires_lock(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is True

    def test_start_with_max_turns(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        state = start_session(project_dir, experiment_id, max_turns=50)
        assert state.max_turns == 50

    def test_start_persists_to_disk(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.status == "running"

    def test_start_raises_if_locked(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        with pytest.raises(RuntimeError, match="already running"):
            start_session(project_dir, experiment_id)


class TestPauseSession:
    def test_pause_updates_status(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        state = pause_session(project_dir, experiment_id)
        assert state.status == "paused"
        assert state.paused_at is not None

    def test_pause_releases_lock(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is False

    def test_pause_persists_to_disk(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.status == "paused"


class TestResumeSession:
    def test_resume_updates_status(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)
        state = resume_session(project_dir, experiment_id)
        assert state.status == "running"

    def test_resume_acquires_lock(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)
        resume_session(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is True

    def test_resume_preserves_turn_count(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        # Manually set turn count
        state = load_session(project_dir, experiment_id)
        assert state is not None
        state.current_turn = 10
        save_session(project_dir, experiment_id, state)
        pause_session(project_dir, experiment_id)
        resumed = resume_session(project_dir, experiment_id)
        assert resumed.current_turn == 10

    def test_resume_raises_if_locked(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        with pytest.raises(RuntimeError, match="already running"):
            resume_session(project_dir, experiment_id)

    def test_resume_raises_if_no_session(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        with pytest.raises(FileNotFoundError, match="No session"):
            resume_session(project_dir, experiment_id)


class TestCompleteSession:
    def test_complete_updates_status(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        state = complete_session(project_dir, experiment_id)
        assert state.status == "completed"
        assert state.completed_at is not None

    def test_complete_releases_lock(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        complete_session(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is False


class TestFailSession:
    def test_fail_updates_status(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        state = fail_session(project_dir, experiment_id, error="Out of memory")
        assert state.status == "failed"
        assert state.completed_at is not None
        assert state.checkpoint.get("error") == "Out of memory"

    def test_fail_releases_lock(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        fail_session(project_dir, experiment_id)
        assert is_locked(project_dir, experiment_id) is False

    def test_fail_without_error_message(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        state = fail_session(project_dir, experiment_id)
        assert state.status == "failed"
        assert "error" not in state.checkpoint
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_session.py::TestStartSession -v`
Expected: FAIL — `ImportError: cannot import name 'start_session' from 'urika.core.session'`

**Step 3: Write minimal implementation**

Add to `src/urika/core/session.py`:

```python
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_session(
    project_dir: Path,
    experiment_id: str,
    max_turns: int | None = None,
) -> SessionState:
    """Start orchestration for an experiment. Creates session.json and lockfile."""
    if not acquire_lock(project_dir, experiment_id):
        msg = f"Experiment {experiment_id} is already running"
        raise RuntimeError(msg)

    state = SessionState(
        experiment_id=experiment_id,
        status="running",
        started_at=_now_iso(),
        max_turns=max_turns,
    )
    save_session(project_dir, experiment_id, state)
    return state


def pause_session(project_dir: Path, experiment_id: str) -> SessionState:
    """Pause a running session. Updates status, removes lockfile."""
    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.status = "paused"
    state.paused_at = _now_iso()
    save_session(project_dir, experiment_id, state)
    release_lock(project_dir, experiment_id)
    return state


def resume_session(project_dir: Path, experiment_id: str) -> SessionState:
    """Resume a paused session. Restores status to running, re-acquires lock."""
    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    if not acquire_lock(project_dir, experiment_id):
        msg = f"Experiment {experiment_id} is already running"
        raise RuntimeError(msg)

    state.status = "running"
    save_session(project_dir, experiment_id, state)
    return state


def complete_session(project_dir: Path, experiment_id: str) -> SessionState:
    """Mark session as completed. Updates status, removes lockfile."""
    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.status = "completed"
    state.completed_at = _now_iso()
    save_session(project_dir, experiment_id, state)
    release_lock(project_dir, experiment_id)
    return state


def fail_session(
    project_dir: Path, experiment_id: str, error: str | None = None
) -> SessionState:
    """Mark session as failed. Records error in checkpoint, removes lockfile."""
    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.status = "failed"
    state.completed_at = _now_iso()
    if error is not None:
        state.checkpoint["error"] = error
    save_session(project_dir, experiment_id, state)
    release_lock(project_dir, experiment_id)
    return state
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_session.py -v`
Expected: 28 PASSED (5 model + 3 load/save + 5 locking + 5 start + 3 pause + 5 resume + 2 complete + 3 fail = ~31, but some test classes have fewer — count carefully from the tests above: 5 + 3 + 5 + 5 + 3 + 5 + 2 + 3 = 31 PASSED)

**Step 5: Commit**

```bash
git add src/urika/core/session.py tests/test_core/test_session.py
git commit -m "feat(session): add lifecycle functions (start, pause, resume, complete, fail)"
```

---

### Task 4: Turn tracking, agent session recording, and active experiment query

**Files:**
- Modify: `src/urika/core/session.py`
- Modify: `tests/test_core/test_session.py`

**Step 1: Write the failing tests**

Add imports to the top of `tests/test_core/test_session.py`:

```python
from urika.core.session import (
    # ... existing imports ...
    get_active_experiment,
    record_agent_session,
    update_turn,
)
```

Append test classes:

```python
class TestUpdateTurn:
    def test_increments_turn(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        state = update_turn(project_dir, experiment_id)
        assert state.current_turn == 1

    def test_increments_multiple_times(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        update_turn(project_dir, experiment_id)
        update_turn(project_dir, experiment_id)
        state = update_turn(project_dir, experiment_id)
        assert state.current_turn == 3

    def test_persists_to_disk(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        update_turn(project_dir, experiment_id)
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.current_turn == 1


class TestRecordAgentSession:
    def test_record_agent_session(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        record_agent_session(project_dir, experiment_id, "task_agent", "sess-abc")
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.agent_sessions["task_agent"] == "sess-abc"

    def test_record_multiple_agents(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        record_agent_session(project_dir, experiment_id, "task_agent", "sess-1")
        record_agent_session(project_dir, experiment_id, "evaluator", "sess-2")
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert len(loaded.agent_sessions) == 2

    def test_record_overwrites_same_role(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        record_agent_session(project_dir, experiment_id, "task_agent", "sess-old")
        record_agent_session(project_dir, experiment_id, "task_agent", "sess-new")
        loaded = load_session(project_dir, experiment_id)
        assert loaded is not None
        assert loaded.agent_sessions["task_agent"] == "sess-new"


class TestGetActiveExperiment:
    def test_no_active_experiment(self, project_dir: Path) -> None:
        assert get_active_experiment(project_dir) is None

    def test_finds_active_experiment(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        active = get_active_experiment(project_dir)
        assert active == experiment_id

    def test_no_active_after_pause(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        pause_session(project_dir, experiment_id)
        assert get_active_experiment(project_dir) is None

    def test_no_active_after_complete(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        start_session(project_dir, experiment_id)
        complete_session(project_dir, experiment_id)
        assert get_active_experiment(project_dir) is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_session.py::TestUpdateTurn -v`
Expected: FAIL — `ImportError: cannot import name 'update_turn' from 'urika.core.session'`

**Step 3: Write minimal implementation**

Add to `src/urika/core/session.py`:

```python
def update_turn(project_dir: Path, experiment_id: str) -> SessionState:
    """Increment turn counter. Returns updated state."""
    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.current_turn += 1
    save_session(project_dir, experiment_id, state)
    return state


def record_agent_session(
    project_dir: Path, experiment_id: str, role: str, session_id: str
) -> None:
    """Store an agent's SDK session_id for later resumption."""
    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.agent_sessions[role] = session_id
    save_session(project_dir, experiment_id, state)


def get_active_experiment(project_dir: Path) -> str | None:
    """Find which experiment is currently running. Scans for lockfiles."""
    experiments_dir = project_dir / "experiments"
    if not experiments_dir.exists():
        return None

    for exp_dir in sorted(experiments_dir.iterdir()):
        if exp_dir.is_dir() and (exp_dir / ".lock").exists():
            return exp_dir.name
    return None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_session.py -v`
Expected: All PASSED

**Step 5: Run full test suite and lint**

Run: `pytest -v --tb=short`
Expected: All tests pass (282 existing + new session tests).

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`
Expected: No errors.

**Step 6: Commit**

```bash
git add src/urika/core/session.py tests/test_core/test_session.py
git commit -m "feat(session): add turn tracking, agent session recording, and active experiment query"
```
