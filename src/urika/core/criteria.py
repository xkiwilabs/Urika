"""Versioned project criteria — evolves during experiments."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from urika.core.atomic_write import write_json_atomic
from urika.core.filelock import locked_json_update

logger = logging.getLogger(__name__)


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
    # How this version relates to the one before: "initial", "raise",
    # "lower", "reframe" or "same" (see ``classify_criteria_change``).
    # Empty for versions written before the field existed.
    change_kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "set_by": self.set_by,
            "turn": self.turn,
            "rationale": self.rationale,
            "criteria": self.criteria,
            "change_kind": self.change_kind,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CriteriaVersion:
        return cls(
            version=d["version"],
            set_by=d["set_by"],
            turn=d.get("turn", 0),
            rationale=d.get("rationale", ""),
            criteria=d.get("criteria", {}),
            change_kind=d.get("change_kind", "") or "",
        )


def load_criteria(project_dir: Path) -> CriteriaVersion | None:
    """Load the latest criteria version, or None if no criteria file exists."""
    path = _criteria_path(project_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Corrupt JSON in %s: %s", path, exc)
        return None
    versions = data.get("versions", [])
    if not versions:
        return None
    return CriteriaVersion.from_dict(versions[-1])


def load_criteria_history(project_dir: Path) -> list[CriteriaVersion]:
    """Load all criteria versions.

    Defensive against external writers: malformed version entries
    (non-dict, missing required keys) are silently dropped rather than
    crashing the loader. Mirrors ``method_registry.load_methods`` —
    the orchestrator and dashboard render this list every turn / on
    every page render; one bad entry would otherwise 500 the world.
    """
    path = _criteria_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Corrupt JSON in %s: %s", path, exc)
        return []
    if not isinstance(data, dict):
        logger.warning(
            "criteria.json top-level is not a dict (%s); ignoring",
            type(data).__name__,
        )
        return []
    out: list[CriteriaVersion] = []
    for v in data.get("versions", []) or []:
        if not isinstance(v, dict):
            logger.warning("Dropping malformed criteria entry: %r", v)
            continue
        try:
            out.append(CriteriaVersion.from_dict(v))
        except (KeyError, TypeError) as exc:
            logger.warning("Dropping criteria entry missing required keys: %s", exc)
    return out


def append_criteria(
    project_dir: Path,
    criteria: dict[str, Any],
    *,
    set_by: str,
    turn: int,
    rationale: str,
    change_kind: str = "",
) -> CriteriaVersion:
    """Append a new criteria version. Creates the file if it doesn't exist.

    *change_kind* is recorded as given; when empty it is classified
    against the previous version (``classify_criteria_change``).
    """
    path = _criteria_path(project_dir)
    with locked_json_update(path):
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Corrupt JSON in %s: %s", path, exc)
                data = {"versions": []}
        else:
            data = {"versions": []}

        versions = data.get("versions", [])
        next_version = len(versions) + 1
        if not change_kind:
            prev = versions[-1].get("criteria") if versions else None
            change_kind = classify_criteria_change(
                prev if isinstance(prev, dict) else None, criteria
            )

        entry = CriteriaVersion(
            version=next_version,
            set_by=set_by,
            turn=turn,
            rationale=rationale,
            criteria=criteria,
            change_kind=change_kind,
        )
        versions.append(entry.to_dict())
        data["versions"] = versions
        write_json_atomic(path, data)
    return entry


# ── Change classification and the agent-update guard ───────────────


def _primary_target(criteria: dict[str, Any] | None) -> tuple[str, float, str] | None:
    """``(metric, target, direction)`` of the primary threshold, if any."""
    if not isinstance(criteria, dict):
        return None
    threshold = criteria.get("threshold")
    if not isinstance(threshold, dict):
        return None
    from urika.evaluation.criteria import _target_entries

    entries = _target_entries(threshold)
    if not entries:
        return None
    primary = threshold.get("primary")
    if isinstance(primary, dict) and isinstance(primary.get("metric"), str):
        for e in entries:
            if e[0] == primary["metric"]:
                return e
    return entries[0]


def classify_criteria_change(old: dict[str, Any] | None, new: dict[str, Any]) -> str:
    """Classify *new* relative to *old*.

    - ``"initial"``: there were no criteria before.
    - ``"same"``: nothing changed.
    - ``"raise"``: same primary metric with a stricter target, or a
      layer added, with nothing loosened or removed.
    - ``"lower"``: primary target loosened, or a layer removed.
    - ``"reframe"``: the primary metric itself changed.
    """
    if old is None:
        return "initial"
    if old == new:
        return "same"
    old_p, new_p = _primary_target(old), _primary_target(new)
    if old_p is not None and new_p is not None and old_p[0] != new_p[0]:
        return "reframe"
    if old_p is None and new_p is not None:
        return "raise"
    if old_p is not None and new_p is None:
        return "lower"
    if old_p is not None and new_p is not None:
        _, old_t, direction = old_p
        new_t = new_p[1]
        if direction == "higher" and new_t < old_t:
            return "lower"
        if direction == "lower" and new_t > old_t:
            return "lower"
        if new_t != old_t:
            return "raise"
    old_layers = {k for k in old if k != "type"}
    new_layers = {k for k in new if k != "type"}
    if old_layers - new_layers:
        return "lower"
    if new_layers - old_layers:
        return "raise"
    # Same layers, same primary target, but some layer's content changed:
    # treat as a raise only if nothing was dropped inside a layer.
    for k in old_layers:
        o, n = old.get(k), new.get(k)
        if isinstance(o, dict) and isinstance(n, dict) and set(o) - set(n):
            return "lower"
        if (
            isinstance(o, list)
            and isinstance(n, list)
            and set(map(str, o)) - set(map(str, n))
        ):
            return "lower"
    return "raise"


@dataclass
class CriteriaUpdateOutcome:
    applied: bool
    change_kind: str
    reason: str
    version: int | None = None


def _proposals_path(project_dir: Path) -> Path:
    return project_dir / "criteria-proposals.jsonl"


def load_criteria_proposals(project_dir: Path) -> list[dict[str, Any]]:
    """Agent criteria updates that were refused and kept for a human."""
    from urika.core.jsonl import read_jsonl

    return read_jsonl(_proposals_path(project_dir))


def _project_mode(project_dir: Path) -> str | None:
    """``[project].mode`` from urika.toml, or None when it cannot be read.

    Callers that gate behaviour on the mode must treat None as the
    strict case; a missing or corrupt config is not permission.
    """
    try:
        import tomllib

        with (project_dir / "urika.toml").open("rb") as fh:
            mode = tomllib.load(fh).get("project", {}).get("mode")
    except (OSError, ValueError, TypeError):
        return None
    return str(mode) if isinstance(mode, str) and mode else None


def apply_agent_criteria_update(
    project_dir: Path,
    update: dict[str, Any],
    *,
    set_by: str,
    turn: int,
) -> CriteriaUpdateOutcome:
    """Apply a ``criteria_update`` block with the rules agents are held to.

    Agents may only **raise** the bar (or set criteria where none exist).
    A lowering or a reframe (different primary metric) is not applied; it
    is recorded in ``criteria-proposals.jsonl`` for a human to accept.
    In ``confirmatory`` mode criteria are frozen after setup: every agent
    update is recorded, none applied. The rules apply whatever *set_by*
    says: this function is the agent path by construction. Humans
    change criteria through ``append_criteria`` directly.
    """
    from urika.core.jsonl import append_jsonl

    criteria = update.get("criteria") if isinstance(update, dict) else None
    rationale = (
        str(update.get("rationale", "") or "") if isinstance(update, dict) else ""
    )
    if not isinstance(criteria, dict) or not criteria:
        return CriteriaUpdateOutcome(
            False, "invalid", "criteria_update carried no criteria"
        )

    current = load_criteria(project_dir)
    kind = classify_criteria_change(current.criteria if current else None, criteria)
    if kind == "same":
        return CriteriaUpdateOutcome(False, kind, "criteria unchanged")

    refuse = ""
    mode = _project_mode(project_dir)
    if mode is None and current is not None:
        # Fail closed: without a readable mode we cannot know whether
        # criteria are frozen, so an agent may not change them.
        refuse = "project mode unreadable; agent criteria changes refused"
    elif mode == "confirmatory" and current is not None:
        refuse = "criteria are frozen in confirmatory mode"
    elif kind == "lower":
        refuse = "agents may not lower the bar; recorded as a proposal"
    elif kind == "reframe":
        refuse = "agents may not change the primary metric; recorded as a proposal"
    if refuse:
        append_jsonl(
            _proposals_path(project_dir),
            {
                "turn": turn,
                "set_by": set_by,
                "change_kind": kind,
                "rationale": rationale,
                "criteria": criteria,
                "refused_because": refuse,
                "against_version": current.version if current else None,
            },
        )
        return CriteriaUpdateOutcome(False, kind, refuse)

    entry = append_criteria(
        project_dir,
        criteria,
        set_by=set_by,
        turn=turn,
        rationale=rationale,
        change_kind=kind,
    )
    return CriteriaUpdateOutcome(True, kind, "applied", version=entry.version)
