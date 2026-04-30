# Criteria System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a versioned criteria system that evolves during experiments — seeded by the project builder, updated by the suggestion agent, evaluated by the evaluator.

**Architecture:** `criteria.json` is a versioned, append-only file in the project directory. `src/urika/core/criteria.py` provides load/append/history functions. The orchestrator parses `criteria_update` from suggestion agent output and writes updates. The evaluator reads the latest version to assess experiments.

**Tech Stack:** Python, dataclasses, JSON, existing agent/orchestrator infrastructure

---

### Task 1: Create criteria module

**Files:**
- Create: `src/urika/core/criteria.py`
- Create: `tests/test_core/test_criteria.py`

**Step 1: Write tests**

```python
"""Tests for criteria system."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from urika.core.criteria import (
    CriteriaVersion,
    append_criteria,
    load_criteria,
    load_criteria_history,
)


class TestCriteriaVersion:
    def test_to_dict(self) -> None:
        v = CriteriaVersion(
            version=1, set_by="project_builder", turn=0,
            rationale="Initial", criteria={"type": "exploratory"},
        )
        d = v.to_dict()
        assert d["version"] == 1
        assert d["set_by"] == "project_builder"

    def test_from_dict(self) -> None:
        d = {"version": 1, "set_by": "user", "turn": 0, "rationale": "x", "criteria": {}}
        v = CriteriaVersion.from_dict(d)
        assert v.version == 1
        assert v.set_by == "user"


class TestLoadCriteria:
    def test_no_file_returns_none(self, tmp_path: Path) -> None:
        assert load_criteria(tmp_path) is None

    def test_returns_latest_version(self, tmp_path: Path) -> None:
        data = {"versions": [
            {"version": 1, "set_by": "a", "turn": 0, "rationale": "", "criteria": {"type": "exploratory"}},
            {"version": 2, "set_by": "b", "turn": 1, "rationale": "", "criteria": {"type": "predictive"}},
        ]}
        (tmp_path / "criteria.json").write_text(json.dumps(data))
        v = load_criteria(tmp_path)
        assert v is not None
        assert v.version == 2
        assert v.criteria["type"] == "predictive"


class TestLoadCriteriaHistory:
    def test_returns_all_versions(self, tmp_path: Path) -> None:
        data = {"versions": [
            {"version": 1, "set_by": "a", "turn": 0, "rationale": "", "criteria": {}},
            {"version": 2, "set_by": "b", "turn": 1, "rationale": "", "criteria": {}},
        ]}
        (tmp_path / "criteria.json").write_text(json.dumps(data))
        history = load_criteria_history(tmp_path)
        assert len(history) == 2

    def test_no_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_criteria_history(tmp_path) == []


class TestAppendCriteria:
    def test_creates_file_if_missing(self, tmp_path: Path) -> None:
        append_criteria(tmp_path, {"type": "exploratory"}, set_by="user", turn=0, rationale="Init")
        assert (tmp_path / "criteria.json").exists()
        v = load_criteria(tmp_path)
        assert v is not None
        assert v.version == 1

    def test_appends_new_version(self, tmp_path: Path) -> None:
        append_criteria(tmp_path, {"type": "exploratory"}, set_by="builder", turn=0, rationale="First")
        append_criteria(tmp_path, {"type": "predictive", "threshold": {"primary": {"metric": "acc", "target": 0.8}}}, set_by="suggestion", turn=3, rationale="Baselines done")
        history = load_criteria_history(tmp_path)
        assert len(history) == 2
        assert history[-1].version == 2
        assert history[-1].criteria["type"] == "predictive"

    def test_version_auto_increments(self, tmp_path: Path) -> None:
        append_criteria(tmp_path, {}, set_by="a", turn=0, rationale="")
        append_criteria(tmp_path, {}, set_by="b", turn=1, rationale="")
        append_criteria(tmp_path, {}, set_by="c", turn=2, rationale="")
        v = load_criteria(tmp_path)
        assert v is not None
        assert v.version == 3

    def test_primary_threshold_met(self, tmp_path: Path) -> None:
        append_criteria(tmp_path, {
            "threshold": {"primary": {"metric": "accuracy", "target": 0.8, "direction": "higher"}}
        }, set_by="user", turn=0, rationale="")
        v = load_criteria(tmp_path)
        assert v is not None
        assert v.criteria["threshold"]["primary"]["target"] == 0.8
```

**Step 2: Implement `src/urika/core/criteria.py`**

```python
"""Versioned project criteria — evolves during experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _criteria_path(project_dir: Path) -> Path:
    return project_dir / "criteria.json"


@dataclass
class CriteriaVersion:
    """A single version of the project criteria."""

    version: int
    set_by: str
    turn: int
    rationale: str
    criteria: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "set_by": self.set_by,
            "turn": self.turn,
            "rationale": self.rationale,
            "criteria": self.criteria,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CriteriaVersion:
        return cls(
            version=d["version"],
            set_by=d["set_by"],
            turn=d.get("turn", 0),
            rationale=d.get("rationale", ""),
            criteria=d.get("criteria", {}),
        )


def load_criteria(project_dir: Path) -> CriteriaVersion | None:
    """Load the latest criteria version, or None if no criteria file exists."""
    path = _criteria_path(project_dir)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    versions = data.get("versions", [])
    if not versions:
        return None
    return CriteriaVersion.from_dict(versions[-1])


def load_criteria_history(project_dir: Path) -> list[CriteriaVersion]:
    """Load all criteria versions."""
    path = _criteria_path(project_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [CriteriaVersion.from_dict(v) for v in data.get("versions", [])]


def append_criteria(
    project_dir: Path,
    criteria: dict[str, Any],
    *,
    set_by: str,
    turn: int,
    rationale: str,
) -> CriteriaVersion:
    """Append a new criteria version. Creates the file if it doesn't exist."""
    path = _criteria_path(project_dir)
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = {"versions": []}

    versions = data.get("versions", [])
    next_version = len(versions) + 1

    entry = CriteriaVersion(
        version=next_version,
        set_by=set_by,
        turn=turn,
        rationale=rationale,
        criteria=criteria,
    )
    versions.append(entry.to_dict())
    data["versions"] = versions
    path.write_text(json.dumps(data, indent=2) + "\n")
    return entry
```

**Step 3: Run tests and commit**

```bash
pytest tests/test_core/test_criteria.py -v
git add src/urika/core/criteria.py tests/test_core/test_criteria.py
git commit -m "feat: add versioned criteria module"
```

---

### Task 2: Update orchestrator to parse criteria_update and pass criteria to evaluator

**Files:**
- Modify: `src/urika/orchestrator/loop.py`
- Modify: `tests/test_orchestrator/test_loop.py`

**Step 1: In the orchestrator loop, after parsing suggestions, check for `criteria_update`**

After line `suggestions = parse_suggestions(suggest_result.text_output)`, add:

```python
# Update criteria if suggestion agent proposed changes
if suggestions and suggestions.get("criteria_update"):
    from urika.core.criteria import append_criteria
    update = suggestions["criteria_update"]
    append_criteria(
        project_dir,
        update.get("criteria", {}),
        set_by="suggestion_agent",
        turn=turn,
        rationale=update.get("rationale", ""),
    )
    progress("result", "Criteria updated")
```

**Step 2: Add test for criteria update parsing**

Add a test that verifies when the suggestion agent output includes `criteria_update`, the orchestrator writes to `criteria.json`.

**Step 3: Run tests and commit**

```bash
pytest tests/test_orchestrator/ -v
git add src/urika/orchestrator/loop.py tests/test_orchestrator/test_loop.py
git commit -m "feat: orchestrator parses criteria_update from suggestions"
```

---

### Task 3: Update evaluator prompt to read criteria.json

**Files:**
- Modify: `src/urika/agents/roles/prompts/evaluator_system.md`

**Step 1: Update the evaluator prompt**

Replace current prompt with version that reads `criteria.json` and evaluates per-layer. Key additions:
- Read `{project_dir}/criteria.json` for current criteria
- Evaluate against all present layers (method_validity, quality, completeness, threshold, comparative)
- `criteria_met: true` only when primary threshold met AND quality/completeness pass
- If no criteria file or no threshold defined: `criteria_met: false`
- Report per-layer status in output

**Step 2: Commit**

```bash
git add src/urika/agents/roles/prompts/evaluator_system.md
git commit -m "feat: evaluator reads criteria.json for structured evaluation"
```

---

### Task 4: Update suggestion agent prompt to propose criteria_update

**Files:**
- Modify: `src/urika/agents/roles/prompts/suggestion_agent_system.md`

**Step 1: Update the suggestion agent prompt**

Add instruction to propose `criteria_update` when appropriate. Add the field to the output format:

```json
{
  "suggestions": [...],
  "needs_tool": false,
  "criteria_update": {
    "rationale": "Baselines established at 60%. Setting predictive target.",
    "criteria": {
      "type": "predictive",
      "threshold": {
        "primary": {"metric": "top1_accuracy", "target": 0.75, "direction": "higher"}
      }
    }
  }
}
```

Include guidance on when to propose updates:
- After baselines reveal realistic ranges
- When analysis type should shift (exploratory → predictive)
- When assumptions fail and quality criteria need updating
- When diminishing returns suggest lowering targets

**Step 2: Commit**

```bash
git add src/urika/agents/roles/prompts/suggestion_agent_system.md
git commit -m "feat: suggestion agent can propose criteria updates"
```

---

### Task 5: Seed criteria.json during project setup

**Files:**
- Modify: `src/urika/core/project_builder.py`
- Modify: `tests/test_core/test_project_builder.py`

**Step 1: Update `write_project()` to seed criteria.json**

In `ProjectBuilder.write_project()`, after creating the workspace, seed an initial criteria file:

```python
from urika.core.criteria import append_criteria

initial_criteria = {
    "type": "exploratory",
    "quality": {"min_approaches": 2},
    "completeness": ["establish baselines"],
}
append_criteria(
    project_dir, initial_criteria,
    set_by="project_builder", turn=0, rationale="Initial project criteria",
)
```

**Step 2: Add test that write_project creates criteria.json**

**Step 3: Run tests and commit**

```bash
pytest tests/test_core/test_project_builder.py -v
git add src/urika/core/project_builder.py tests/test_core/test_project_builder.py
git commit -m "feat: seed criteria.json during project setup"
```

---

### Task 6: Update docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `current-status.md`

**Step 1: Add criteria module to CLAUDE.md core modules list**

**Step 2: Update current-status.md with criteria system**

**Step 3: Run full test suite, commit**

```bash
pytest -v
git add CLAUDE.md current-status.md
git commit -m "docs: update docs for criteria system"
```
