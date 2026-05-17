"""In-memory builder-session state for the dashboard's interactive
new-project wizard (v0.4.5 Track 1).

A ``BuilderSession`` represents one in-flight interactive
project-setup conversation: it owns an ``asyncio.Queue`` of events
emitted by ``urika.core.builder_loop.run_builder_loop`` plus a
pending-question ``asyncio.Future`` for the wait-for-user-answer
state. The background task running the loop is also held here so
abort/cleanup can cancel it.

State is in-memory; a server restart drops all in-flight sessions.
Acceptable for v0.4.5 because:

  - The workspace scaffold is already on disk (the dashboard's
    existing ``POST /projects`` writes it before this loop starts),
    so a server restart loses only the agent Q&A transcript, not
    project data.
  - On-disk session resumption is a v0.5+ candidate if real usage
    shows server-restart-mid-loop is a frequent problem.

Concurrency: at most one builder session per project at a time —
keyed by project name. A second ``start`` for the same project
returns 409 until the first session is ``done`` or aborted.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from urika.core.builder_loop import BuilderEvent, BuilderQuestion

logger = logging.getLogger(__name__)


@dataclass
class BuilderSession:
    session_id: str
    project_name: str
    project_dir: Path
    events: "asyncio.Queue[BuilderEvent]" = field(
        default_factory=lambda: asyncio.Queue()
    )
    pending_question: "asyncio.Future[str] | None" = None
    pending_question_data: "BuilderQuestion | None" = None
    task: "asyncio.Task | None" = None
    done: bool = False
    aborted: bool = False
    final_suggestions: dict | None = None


# Keyed by project_name (not session_id) because at most one
# builder session per project is allowed at a time. The check is
# trivial this way.
_active: dict[str, BuilderSession] = {}


def get_for_project(project_name: str) -> BuilderSession | None:
    return _active.get(project_name)


def register(session: BuilderSession) -> None:
    _active[session.project_name] = session


def unregister(project_name: str) -> None:
    _active.pop(project_name, None)


def all_active() -> dict[str, BuilderSession]:
    """Snapshot of every currently-active builder session.

    Useful for the dashboard's debug / admin pages — not consumed
    by the wizard itself, which always looks up by project name.
    """
    return dict(_active)
