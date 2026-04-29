"""Orchestrator conversation session persistence — per-project."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class OrchestratorSession:
    session_id: str
    started: str
    updated: str
    older_summary: str = ""
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OrchestratorSession:
        return cls(
            session_id=d["session_id"],
            started=d["started"],
            updated=d["updated"],
            older_summary=d.get("older_summary", ""),
            recent_messages=d.get("recent_messages", []),
            preview=d.get("preview", ""),
        )


def _sessions_dir(project_dir: Path) -> Path:
    d = project_dir / ".urika" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def save_session(project_dir: Path, session: OrchestratorSession) -> None:
    session.updated = _now_iso()
    path = _sessions_dir(project_dir) / f"{session.session_id}.json"
    path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")
    # Cap session retention at 20 per project. The helper sorts by filename
    # (which is timestamp-prefixed via _timestamp_id), so the file we just
    # wrote is the freshest and won't be pruned. Failure here must not
    # block the save — a partial filesystem error shouldn't lose the
    # session we just persisted.
    try:
        prune_old_sessions(project_dir, keep=20)
    except Exception:
        pass


def load_session(project_dir: Path, session_id: str) -> OrchestratorSession | None:
    path = _sessions_dir(project_dir) / f"{session_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return OrchestratorSession.from_dict(data)


def list_sessions(project_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    sessions_dir = _sessions_dir(project_dir)
    files = sorted(sessions_dir.glob("*.json"), reverse=True)[:limit]
    result = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({
                "session_id": data["session_id"],
                "started": data.get("started", ""),
                "updated": data.get("updated", ""),
                "preview": data.get("preview", ""),
                "turn_count": len(data.get("recent_messages", [])) // 2,
                "has_older_summary": bool(data.get("older_summary")),
            })
        except Exception:
            continue
    return result


def get_most_recent(project_dir: Path) -> OrchestratorSession | None:
    sessions = list_sessions(project_dir, limit=1)
    if not sessions:
        return None
    return load_session(project_dir, sessions[0]["session_id"])


def create_new_session() -> OrchestratorSession:
    now = _now_iso()
    return OrchestratorSession(
        session_id=_timestamp_id(),
        started=now,
        updated=now,
    )


def delete_session(project_dir: Path, session_id: str) -> bool:
    path = _sessions_dir(project_dir) / f"{session_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def prune_old_sessions(project_dir: Path, keep: int = 20) -> int:
    sessions_dir = _sessions_dir(project_dir)
    files = sorted(sessions_dir.glob("*.json"), reverse=True)
    if len(files) <= keep:
        return 0
    to_delete = files[keep:]
    for f in to_delete:
        f.unlink()
    return len(to_delete)
