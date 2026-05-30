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
        # T2.6 will fill this in.
        pass
    return result
