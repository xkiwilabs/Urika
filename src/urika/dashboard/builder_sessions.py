"""Builder-session state for the dashboard's interactive new-project
wizard (v0.4.5 Track 1; persistence added v0.10.0 Phase 6).

A ``BuilderSession`` represents one in-flight interactive
project-setup conversation: it owns an ``asyncio.Queue`` of events
emitted by ``urika.core.builder_loop.run_builder_loop`` plus a
pending-question ``asyncio.Future`` for the wait-for-user-answer
state. The background task running the loop is also held here so
abort/cleanup can cancel it.

Live state (the Queue, the pending Future, the loop Task, and the
running ``run_builder_loop`` coroutine itself) is fundamentally
in-memory and NOT serializable — a running coroutine cannot survive a
process restart. So "persistence" here does NOT resurrect a live
loop. Instead we persist the *serializable* slice of a session to
``<project_dir>/.urika/builder/session.json`` on every state
transition:

  - ``session_id`` / ``project_name``
  - the ordered transcript of resolved ``(question_text, answer)``
    pairs (so prior answers are never silently lost),
  - the current pending question text (if any),
  - ``done`` / ``aborted`` flags and ``final_suggestions``.

On a server restart the in-memory ``_active`` map is empty.
:func:`get_for_project` then checks disk: a non-terminal
``session.json`` is *rehydrated* into a ``detached=True``
``BuilderSession`` carrying the transcript + pending question but no
live task/queue. The wizard's stream endpoint can REPLAY that
transcript so the user sees where they left off.

Resume is by ANSWER-REPLAY (see
``urika.dashboard.routers.api`` ``builder/answer``): a fresh
``run_builder_loop`` is relaunched with an ``ask_user`` wrapper that
auto-answers from the persisted transcript first (matching saved
answers to questions whose text matches, in order) and only blocks
for live user input once the saved answers are exhausted. This
re-runs the loop deterministically over the already-answered portion
and continues live from the pending point. HONEST LIMITATION: if a
re-run question's text does NOT match the next saved answer
(non-deterministic agent drift), auto-answer stops and the user is
asked live from that point — a saved answer is never mis-applied to a
different question.

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

from urika.core.atomic_write import write_json_atomic

if TYPE_CHECKING:
    from urika.core.builder_loop import AskUser, BuilderEvent, BuilderQuestion

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
    # --- v0.10.0 Phase 6 persistence ---
    # Ordered list of resolved (question_text, answer) pairs. Appended
    # the moment an answer resolves a pending question; flushed to disk
    # on every transition. This is the replayable record.
    transcript: list[tuple[str, str]] = field(default_factory=list)
    # True when this session was rehydrated from disk after a restart:
    # it carries transcript + pending question but no live task/queue.
    detached: bool = False


# Keyed by project_name (not session_id) because at most one
# builder session per project is allowed at a time. The check is
# trivial this way.
_active: dict[str, BuilderSession] = {}


# ── Persistence layer ──────────────────────────────────────────────


def session_path(project_dir: Path) -> Path:
    """On-disk location of the persisted session for a project."""
    return Path(project_dir) / ".urika" / "builder" / "session.json"


def _serialize(session: BuilderSession) -> dict:
    pending = None
    if session.pending_question_data is not None:
        q = session.pending_question_data
        pending = {
            "text": q.text,
            "options": list(q.options),
            "is_terminal_choice": q.is_terminal_choice,
        }
    return {
        "session_id": session.session_id,
        "project_name": session.project_name,
        "transcript": [list(pair) for pair in session.transcript],
        "pending_question": pending,
        "done": session.done,
        "aborted": session.aborted,
        "final_suggestions": session.final_suggestions,
    }


def persist(session: BuilderSession) -> None:
    """Atomically flush the serializable slice of *session* to disk.

    Best-effort: persistence must never break the wizard, so any I/O
    failure is logged and swallowed.
    """
    try:
        path = session_path(session.project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, _serialize(session))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "builder session persist failed for %s: %s",
            session.project_name,
            exc,
        )


def delete_persisted(project_dir: Path) -> None:
    """Remove the persisted session file (on done / abort). Idempotent."""
    try:
        session_path(project_dir).unlink(missing_ok=True)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("builder session delete failed: %s", exc)


def load_persisted(project_dir: Path) -> dict | None:
    """Load the raw persisted session dict for a project, or ``None``."""
    path = session_path(project_dir)
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("builder session load failed: %s", exc)
        return None


def rehydrate(project_name: str, project_dir: Path) -> BuilderSession | None:
    """Build a ``detached`` session from a non-terminal on-disk record.

    Returns ``None`` when there's no persisted session, or it's
    terminal (done/aborted) — a finished session has nothing to
    resume. The returned session has a fresh (empty) queue and no
    live task; the wizard treats ``detached`` specially.
    """
    from urika.core.builder_loop import BuilderQuestion

    raw = load_persisted(project_dir)
    if raw is None:
        return None
    if raw.get("done") or raw.get("aborted"):
        return None

    transcript = [
        (str(pair[0]), str(pair[1]))
        for pair in (raw.get("transcript") or [])
        if isinstance(pair, (list, tuple)) and len(pair) == 2
    ]
    pending_data = None
    pending = raw.get("pending_question")
    if isinstance(pending, dict) and pending.get("text"):
        pending_data = BuilderQuestion(
            text=str(pending["text"]),
            options=list(pending.get("options") or []),
            is_terminal_choice=bool(pending.get("is_terminal_choice")),
        )

    return BuilderSession(
        session_id=str(raw.get("session_id") or ""),
        project_name=project_name,
        project_dir=Path(project_dir),
        pending_question_data=pending_data,
        final_suggestions=raw.get("final_suggestions"),
        transcript=transcript,
        detached=True,
    )


def make_replay_ask_user(
    transcript: list[tuple[str, str]],
    live_ask_user: "AskUser",
    *,
    on_replay=None,
):
    """Wrap *live_ask_user* so a relaunched loop replays saved answers.

    Returns an ``ask_user(BuilderQuestion) -> str`` coroutine that:

      1. Consumes the persisted *transcript* in order. For each new
         question whose text exactly matches the next saved pair's
         question text, it returns the saved answer WITHOUT calling
         the live ``ask_user`` (the user isn't re-asked). If
         *on_replay* is given it's called as ``on_replay(q, answer)``
         so the caller can mirror the replayed Q&A to its UI / record
         it onto a fresh session.
      2. The moment a question's text does NOT match the next saved
         pair — i.e. the agent drifted and produced a different
         question on the re-run — auto-answer stops permanently and
         every subsequent question (including this one) goes to the
         live ``ask_user``. A saved answer is never applied to a
         mismatched question.
      3. Once the transcript is exhausted, all further questions go
         live.

    This is the honest "resume" mechanism: it re-runs the loop
    deterministically over the already-answered portion and continues
    live from the pending point.
    """
    index = 0
    drifted = False

    async def _ask(q: "BuilderQuestion") -> str:
        nonlocal index, drifted
        if not drifted and index < len(transcript):
            saved_q, saved_a = transcript[index]
            if q.text == saved_q:
                index += 1
                if on_replay is not None:
                    on_replay(q, saved_a)
                return saved_a
            # Agent drift: stop replaying, ask live from here on.
            drifted = True
        return await live_ask_user(q)

    return _ask


# ── Registry ───────────────────────────────────────────────────────


def get_for_project(
    project_name: str, project_dir: Path | None = None
) -> BuilderSession | None:
    """Return the active session for a project, rehydrating from disk
    if needed.

    If an in-memory session exists it always wins. Otherwise, when a
    *project_dir* is supplied, a non-terminal persisted session is
    rehydrated into a ``detached`` session, registered, and returned —
    so an interrupted wizard surfaces after a server restart instead
    of vanishing.
    """
    session = _active.get(project_name)
    if session is not None:
        return session
    if project_dir is not None:
        rehydrated = rehydrate(project_name, project_dir)
        if rehydrated is not None:
            _active[project_name] = rehydrated
            return rehydrated
    return None


def register(session: BuilderSession) -> None:
    _active[session.project_name] = session
    persist(session)


def unregister(project_name: str) -> None:
    _active.pop(project_name, None)


def all_active() -> dict[str, BuilderSession]:
    """Snapshot of every currently-active builder session.

    Useful for the dashboard's debug / admin pages — not consumed
    by the wizard itself, which always looks up by project name.
    """
    return dict(_active)
