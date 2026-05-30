"""Memory curator dispatch — invokes the agent, parses decisions,
optionally applies them.

The curator agent role (see ``urika.agents.roles.memory_curator``)
proposes ``merge`` / ``archive`` / ``flag_stale`` / ``flag_contradiction``
decisions on the project's memory directory. This module is the
runtime glue that:

  1. Renders the current memory directory as the curator's user
     message.
  2. Invokes the agent via the supplied :class:`~urika.agents.runner.AgentRunner`.
  3. Parses ``decisions`` out of the agent's fenced JSON response
     using the shared brace-balanced extractor.
  4. (When ``apply=True``) commits the decisions to disk.

T2.5 ships steps 1-3 (dry-run). T2.6 wires up step 4 — gated on the
caller asking for it so the dashboard / CLI can show a diff first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from urika.agents.runner import AgentRunner

logger = logging.getLogger(__name__)


@dataclass
class CuratorResult:
    """Outcome of a curator run.

    ``decisions`` is the list of proposed actions parsed from the
    agent's response (each a dict like
    ``{"action": "archive", "filename": "user_foo.md", "reason": "..."}``).
    ``applied`` is True only when the apply path actually ran (T2.6).
    ``error`` is set if the agent invocation itself failed.
    """

    decisions: list[dict[str, Any]] = field(default_factory=list)
    applied: bool = False
    error: str | None = None


def _build_curator_input(project_dir: Path) -> str:
    """Render the current memory dir as the curator's user message.

    Includes one section per entry with filename and full file text
    (frontmatter + body). Archived entries (``memory/archive/``) are
    NOT included — curator decisions act on live entries only.

    Returns an empty-ish header-only block when the memory dir is
    empty; the curator will then return ``decisions: []``.
    """
    from urika.core import project_memory

    entries = project_memory.list_entries(project_dir)
    md = project_memory.memory_dir(project_dir)
    parts = ["# Current memory directory\n"]
    for entry in entries:
        path = md / entry["filename"]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read memory entry %s: %s", path, exc)
            continue
        parts.append(f"---\n## {entry['filename']}\n\n{text}\n")
    return "\n".join(parts)


async def run_curator(
    project_dir: Path,
    runner: AgentRunner,
    apply: bool = False,
) -> CuratorResult:
    """Run the memory curator. Returns proposed decisions.

    ``apply=False`` (default): dry-run — return decisions, mutate
    nothing. Suitable for the dashboard preview / CLI ``--dry-run``
    surfaces.

    ``apply=True``: also commits the decisions to the memory dir
    (T2.6 — archive / merge / flag actions).
    """
    from urika.agents.roles import memory_curator as role
    from urika.orchestrator.parsing import _extract_json_blocks

    user_message = _build_curator_input(project_dir)
    agent_role = role.get_role()
    cfg = agent_role.build_config(project_dir=project_dir)

    try:
        agent_result = await runner.run(cfg, user_message)
    except Exception as exc:  # noqa: BLE001 — surface as error, don't crash caller
        logger.warning(
            "Memory curator invocation failed: %s: %s", type(exc).__name__, exc
        )
        return CuratorResult(error=f"{type(exc).__name__}: {exc}")

    if not agent_result.success:
        return CuratorResult(error=agent_result.error or "curator agent failed")

    blocks = _extract_json_blocks(agent_result.text_output or "")
    decisions: list[dict[str, Any]] = []
    for block in blocks:
        d = block.get("decisions")
        if isinstance(d, list):
            decisions.extend(item for item in d if isinstance(item, dict))

    result = CuratorResult(decisions=decisions, applied=False)
    if apply:
        result.applied = _apply_decisions(project_dir, decisions)
    return result


def _apply_decisions(project_dir: Path, decisions: list[dict[str, Any]]) -> bool:
    """Commit each decision to the memory directory.

    Decision-level errors do NOT abort the batch — a single malformed
    entry (e.g. ``merge`` missing ``into``/``from``, or ``archive``
    pointing at a nonexistent file) is logged and skipped so the rest
    of the curator's decisions still land. The function returns True
    once the batch has been processed even when individual decisions
    were no-ops; ``applied=True`` means "we ran the apply path", not
    "every decision succeeded".
    """
    from urika.core.project_memory import (
        archive_entry,
        memory_dir,
        rebuild_index,
    )

    md = memory_dir(project_dir)
    for d in decisions:
        action = d.get("action")
        try:
            if action == "archive":
                fn = d.get("filename")
                if isinstance(fn, str):
                    archive_entry(project_dir, fn, _skip_index=True)
            elif action == "merge":
                keep = d.get("into")
                if not isinstance(keep, str):
                    continue
                from_list = [f for f in d.get("from", []) if isinstance(f, str)]
                _apply_merge(md, keep, from_list)
                for fn in from_list:
                    archive_entry(project_dir, fn, _skip_index=True)
            elif action in ("flag_stale", "flag_contradiction"):
                _apply_flag(md, d)
        except Exception as exc:  # noqa: BLE001 — per-decision errors don't abort the batch
            logger.warning(
                "Curator decision %r failed: %s: %s",
                action,
                type(exc).__name__,
                exc,
            )
            continue
    rebuild_index(project_dir)
    return True


def _apply_merge(memory_dir_path: Path, keep: str, from_list: list[str]) -> None:
    """Concatenate ``from_list`` entries' contents onto the ``keep``
    entry, separated by markdown ``---`` rules. Callers archive the
    ``from`` entries separately after this returns so the merge is
    visible even if the archive step later fails.
    """
    keep_path = memory_dir_path / keep
    if not keep_path.is_file():
        return
    keep_text = keep_path.read_text(encoding="utf-8")
    add: list[str] = []
    for fn in from_list:
        src = memory_dir_path / fn
        if not src.is_file():
            continue
        add.append(src.read_text(encoding="utf-8"))
    if add:
        merged = keep_text + "\n\n---\n\n" + "\n\n---\n\n".join(add)
        keep_path.write_text(merged, encoding="utf-8")


def _apply_flag(memory_dir_path: Path, decision: dict[str, Any]) -> None:
    """Inject a ``flagged_stale: <reason>`` or ``flagged_contradiction:
    <reason>`` line into the entry's frontmatter. Idempotent — if a
    flag with that key already exists in the file (regardless of
    reason text), this is a no-op rather than appending a duplicate.

    For ``flag_contradiction`` decisions that name multiple files via
    a ``between`` list, the flag is applied to the FIRST file in the
    list (the curator is expected to issue one decision per file when
    flagging both sides — the ``between`` shorthand here is best-
    effort fallback).
    """
    fn = decision.get("filename") or (decision.get("between") or [None])[0]
    if not isinstance(fn, str):
        return
    path = memory_dir_path / fn
    if not path.is_file():
        return
    flag_key = (
        "flagged_stale"
        if decision.get("action") == "flag_stale"
        else "flagged_contradiction"
    )
    reason = (
        str(decision.get("reason", "")).replace("\n", " ").replace("\r", " ").strip()
    )
    text = path.read_text(encoding="utf-8")
    # Idempotent: don't add the same flag twice.
    if f"{flag_key}:" in text:
        return
    lines = text.splitlines()
    inserted = False
    if lines and lines[0] == "---":
        # Find the closing --- and inject the flag before it.
        for i, line in enumerate(lines[1:], start=1):
            if line == "---":
                lines.insert(i, f"{flag_key}: {reason}")
                inserted = True
                break
    else:
        lines = ["---", f"{flag_key}: {reason}", "---"] + lines
        inserted = True
    if not inserted:
        logger.warning(
            "Could not flag %s — frontmatter has opening --- but no closing marker",
            path,
        )
        return
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
