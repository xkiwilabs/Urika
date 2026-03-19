"""Core data models for Urika projects, experiments, and runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

VALID_MODES = {"exploratory", "confirmatory", "pipeline"}


@dataclass
class ProjectConfig:
    """Configuration for a Urika project. Serializes to/from urika.toml."""

    name: str
    question: str
    mode: str
    description: str = ""
    data_paths: list[str] = field(default_factory=list)
    success_criteria: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in VALID_MODES:
            msg = f"mode must be one of {VALID_MODES}, got '{self.mode}'"
            raise ValueError(msg)

    def to_toml_dict(self) -> dict[str, Any]:
        """Convert to a nested dict suitable for TOML serialization."""
        d: dict[str, Any] = {
            "project": {
                "name": self.name,
                "question": self.question,
                "mode": self.mode,
                "description": self.description,
            }
        }
        if self.data_paths:
            d["project"]["data_paths"] = self.data_paths
        if self.success_criteria:
            d["project"]["success_criteria"] = self.success_criteria
        return d

    @classmethod
    def from_toml_dict(cls, d: dict[str, Any]) -> ProjectConfig:
        """Create from a parsed TOML dict."""
        p = d["project"]
        return cls(
            name=p["name"],
            question=p["question"],
            mode=p["mode"],
            description=p.get("description", ""),
            data_paths=p.get("data_paths", []),
            success_criteria=p.get("success_criteria", {}),
        )


@dataclass
class ExperimentConfig:
    """Configuration for an experiment within a project."""

    experiment_id: str
    name: str
    hypothesis: str
    status: str = "pending"
    builds_on: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "hypothesis": self.hypothesis,
            "status": self.status,
            "builds_on": self.builds_on,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExperimentConfig:
        return cls(
            experiment_id=d["experiment_id"],
            name=d["name"],
            hypothesis=d["hypothesis"],
            status=d.get("status", "pending"),
            builds_on=d.get("builds_on", []),
            created_at=d.get("created_at", ""),
        )


@dataclass
class RunRecord:
    """A single method execution within an experiment."""

    run_id: str
    method: str
    params: dict[str, Any]
    metrics: dict[str, float]
    hypothesis: str = ""
    observation: str = ""
    next_step: str = ""
    artifacts: list[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "method": self.method,
            "params": self.params,
            "metrics": self.metrics,
            "hypothesis": self.hypothesis,
            "observation": self.observation,
            "next_step": self.next_step,
            "artifacts": self.artifacts,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunRecord:
        return cls(
            run_id=d["run_id"],
            method=d["method"],
            params=d["params"],
            metrics=d["metrics"],
            hypothesis=d.get("hypothesis", ""),
            observation=d.get("observation", ""),
            next_step=d.get("next_step", ""),
            artifacts=d.get("artifacts", []),
            timestamp=d.get("timestamp", ""),
        )


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
