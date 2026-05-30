"""Project memory — Phase 1 (v0.4 Track 2).

Project-scoped equivalent of the global Claude Code memory directory.
A directory `<project>/memory/` with structured markdown files plus
a top-level `MEMORY.md` index. Agents read it on every run via
``load_project_memory(project_dir)``; orchestrator harvests
``<memory type="..."></memory>`` markers from agent output via
``parse_and_persist_memory_markers``.

Design locked at ``dev/plans/2026-04-28-project-memory-design.md``.
This module ships Phase 1: read path + auto-capture + manual writers.
Curator (Phase 3) defers to v0.5.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date as _date
from pathlib import Path

from urika.core.atomic_write import write_json_atomic

logger = logging.getLogger(__name__)


_TYPES = ("user", "feedback", "instruction", "decision", "reference")

# v0.5.0 token-budget caps (Decision 2 of the memory-deepening plan).
# Token estimate uses ``estimate_tokens`` (bytes / 3.5) — biased UP so
# the curator fires slightly early rather than late on non-ASCII text.
SOFT_CAP_TOKENS = 5_000
HARD_CAP_TOKENS = 10_000
SOFT_CAP_ENTRIES = 30


def estimate_tokens(text: str) -> int:
    """Conservative byte-heuristic token count (bytes / 3.5).

    Biases the estimate UP so non-Latin scripts and code don't sneak
    under the cap. The failure mode is curator-fires-slightly-early,
    which is harmless. See dev/plans/2026-05-17-v0.5.0-memory-deepening.md
    Decision 2.
    """
    return int(len(text.encode("utf-8")) / 3.5)


_MEMORY_RE = re.compile(
    r"<memory\s+type=[\"'](?P<type>[^\"']+)[\"']\s*>(?P<body>.*?)</memory>",
    re.IGNORECASE | re.DOTALL,
)
_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def memory_dir(project_dir: Path) -> Path:
    return project_dir / "memory"


def index_path(project_dir: Path) -> Path:
    return memory_dir(project_dir) / "MEMORY.md"


def is_enabled(project_dir: Path) -> bool:
    """Project setting ``[memory] auto_capture = true|false`` gates
    auto-capture. Default ``true`` per the design.
    """
    import tomllib

    toml_path = project_dir / "urika.toml"
    if not toml_path.exists():
        return True
    try:
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
    except Exception:
        return True
    return bool(data.get("memory", {}).get("auto_capture", True))


def _slugify(text: str) -> str:
    s = _SLUG_RE.sub("_", text.lower()).strip("_")
    return s[:48] or "entry"


def _entry_path(project_dir: Path, mem_type: str, slug: str) -> Path:
    return memory_dir(project_dir) / f"{mem_type}_{slug}.md"


def list_entries(project_dir: Path) -> list[dict[str, str]]:
    """Return one row per memory entry: {filename, type, slug,
    description, body_preview}. Empty list when memory dir is missing.
    """
    d = memory_dir(project_dir)
    if not d.is_dir():
        return []
    out = []
    for path in sorted(d.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        text = path.read_text(encoding="utf-8")
        meta, body = _split_frontmatter(text)
        out.append(
            {
                "filename": path.name,
                "type": meta.get("type", _infer_type_from_filename(path.name)),
                "name": meta.get("name", path.stem),
                "description": meta.get("description", ""),
                "body_preview": body.strip().replace("\n", " ")[:120],
            }
        )
    return out


def _infer_type_from_filename(name: str) -> str:
    for t in _TYPES:
        if name.startswith(f"{t}_"):
            return t
    return "other"


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return ``({meta_key: value}, body)`` for a doc with optional
    YAML-ish frontmatter fenced by ``---``. Permissive — we only need
    the half-dozen keys the design uses (``name``, ``description``,
    ``type``, ``created``, ``last_used``).
    """
    if not text.startswith("---\n"):
        return {}, text
    rest = text[4:]
    end = rest.find("\n---\n")
    if end < 0:
        return {}, text
    head = rest[:end]
    body = rest[end + len("\n---\n") :]
    meta: dict[str, str] = {}
    for line in head.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, body


_PREAMBLE = (
    "The following persistent project memory shapes how you should "
    "approach this project. Honor these preferences and decisions "
    "unless the user explicitly overrides them in this session."
)
_HEADER_NORMAL = "## Project Memory"
_HEADER_OVER_BUDGET = "## Project Memory (over budget — run urika memory curate)"


def _render_entry(project_dir: Path, entry: dict[str, str]) -> str | None:
    """Render one memory entry as the markdown block it occupies in
    the injection. Returns None if the file can't be read.
    """
    d = memory_dir(project_dir) / entry["filename"]
    try:
        text = d.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read memory file %s: %s", d, exc)
        return None
    _meta, body = _split_frontmatter(text)
    chunk = [f"### {entry['type']}: {entry['name']}"]
    if entry["description"]:
        chunk.append(f"_{entry['description']}_")
    chunk.append("")
    chunk.append(body.strip())
    chunk.append("")
    return "\n".join(chunk)


def load_project_memory(project_dir: Path, session_id: str | None = None) -> str:
    """Read every memory file, return a system-prompt-ready block.

    Empty string when memory dir is missing or empty. When the total
    rendered block exceeds :data:`HARD_CAP_TOKENS`, oldest entries
    (by mtime) are dropped until the result fits and the section
    header is replaced with an "over budget" marker telling the user
    to run ``urika memory curate``.

    When ``session_id`` is provided AND the soft cap is exceeded
    (either by tokens or entry count), flag the session as
    "curator-due" so the orchestrator can run the curator at the
    next strategic checkpoint (see :func:`is_curator_due` /
    :func:`mark_curator_ran`). When ``session_id`` is ``None``
    (the default for existing callers) the flag file is never
    touched.
    """
    entries = list_entries(project_dir)
    if not entries:
        return ""

    # Pair each entry with its rendered body + mtime so we can drop
    # oldest-first when over budget.
    rendered: list[tuple[float, int, str]] = []  # (mtime, orig_idx, text)
    for idx, e in enumerate(entries):
        chunk = _render_entry(project_dir, e)
        if chunk is None:
            continue
        path = memory_dir(project_dir) / e["filename"]
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        rendered.append((mtime, idx, chunk))

    if not rendered:
        return ""

    # Helper to assemble the final blob from a chunks-in-original-order
    # sequence, with the chosen header.
    def _assemble(chunks_in_order: list[str], header: str) -> str:
        parts = [header, "", _PREAMBLE, ""]
        parts.extend(chunks_in_order)
        return "\n".join(parts).rstrip() + "\n"

    full_blob = _assemble([c for _, _, c in rendered], _HEADER_NORMAL)
    full_tokens = estimate_tokens(full_blob)
    soft_exceeded = full_tokens > SOFT_CAP_TOKENS or len(rendered) > SOFT_CAP_ENTRIES

    # Signal curator-due BEFORE the early-return path so the flag is
    # set even when we're still under the hard cap.
    if session_id is not None and soft_exceeded:
        _signal_curator_due(project_dir, session_id)

    if full_tokens <= HARD_CAP_TOKENS:
        if soft_exceeded:
            logger.warning(
                "Project memory exceeds soft cap (%d > %d tokens or %d > %d entries)"
                " — curator should run",
                full_tokens,
                SOFT_CAP_TOKENS,
                len(rendered),
                SOFT_CAP_ENTRIES,
            )
        return full_blob

    # Over hard cap: drop oldest entries (smallest mtime) until under.
    # Sort newest-first; take entries while accumulated token count fits.
    by_newest = sorted(rendered, key=lambda r: r[0], reverse=True)
    kept: list[tuple[float, int, str]] = []
    for mtime, idx, chunk in by_newest:
        candidate = kept + [(mtime, idx, chunk)]
        # Re-assemble in original ordering to estimate accurately.
        ordered = [c for _, _, c in sorted(candidate, key=lambda r: r[1])]
        if estimate_tokens(_assemble(ordered, _HEADER_OVER_BUDGET)) > HARD_CAP_TOKENS:
            break
        kept = candidate

    kept_in_order = [c for _, _, c in sorted(kept, key=lambda r: r[1])]
    logger.warning(
        "Project memory exceeds hard cap (%d > %d tokens) — "
        "dropped %d oldest entries; run `urika memory curate`",
        full_tokens,
        HARD_CAP_TOKENS,
        len(rendered) - len(kept),
    )
    return _assemble(kept_in_order, _HEADER_OVER_BUDGET)


# ---------------------------------------------------------------------------
# Session-scoped curator-due flag (v0.5.0 Task 2.3)
#
# When ``load_project_memory`` is called with a ``session_id`` and the
# soft cap is crossed, the session is recorded in
# ``<project>/memory/.curator-flag.json`` under a ``pending_sessions``
# list. The orchestrator queries this with :func:`is_curator_due`
# before each strategic checkpoint, fires the curator agent, then
# clears the flag with :func:`mark_curator_ran`. Once-per-session.
# ---------------------------------------------------------------------------
_FLAG_FILENAME = ".curator-flag.json"


def _flag_path(project_dir: Path) -> Path:
    return memory_dir(project_dir) / _FLAG_FILENAME


def _read_flag(project_dir: Path) -> dict:
    p = _flag_path(project_dir)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_flag(project_dir: Path, data: dict) -> None:
    write_json_atomic(_flag_path(project_dir), data)


def is_curator_due(project_dir: Path, session_id: str) -> bool:
    """True if the curator should run for this session (soft cap was
    crossed AND it hasn't run in this session yet).
    """
    flag = _read_flag(project_dir)
    return session_id in set(flag.get("pending_sessions", []))


def mark_curator_ran(project_dir: Path, session_id: str) -> None:
    """Clear the curator-due flag for ``session_id`` after the curator
    has executed in that session.
    """
    flag = _read_flag(project_dir)
    pending = set(flag.get("pending_sessions", []))
    pending.discard(session_id)
    flag["pending_sessions"] = sorted(pending)
    _write_flag(project_dir, flag)


def _signal_curator_due(project_dir: Path, session_id: str) -> None:
    flag = _read_flag(project_dir)
    pending = set(flag.get("pending_sessions", []))
    pending.add(session_id)
    flag["pending_sessions"] = sorted(pending)
    _write_flag(project_dir, flag)


def save_entry(
    project_dir: Path,
    *,
    mem_type: str,
    body: str,
    description: str = "",
    slug: str | None = None,
) -> Path:
    """Write a single memory entry. Returns the file path written."""
    if mem_type not in _TYPES:
        raise ValueError(f"Unknown memory type {mem_type!r}; must be one of {_TYPES}")
    d = memory_dir(project_dir)
    d.mkdir(parents=True, exist_ok=True)
    if slug is None:
        slug = _slugify(description or body.strip().split("\n", 1)[0] or mem_type)
    path = _entry_path(project_dir, mem_type, slug)
    today = _date.today().isoformat()
    name = f"{mem_type}_{slug}"
    description_line = description.strip() or body.strip().split("\n", 1)[0][:120]
    frontmatter = (
        "---\n"
        f"name: {name}\n"
        f"description: {description_line}\n"
        f"type: {mem_type}\n"
        f"created: {today}\n"
        f"last_used: {today}\n"
        "---\n\n"
    )
    path.write_text(frontmatter + body.strip() + "\n", encoding="utf-8")
    rebuild_index(project_dir)
    return path


def delete_entry(project_dir: Path, filename: str) -> bool:
    """Remove a memory entry by filename. Trashes to ``memory/.trash/``
    rather than deleting outright. Returns True if removed.
    """
    src = memory_dir(project_dir) / filename
    if not src.exists():
        return False
    trash = memory_dir(project_dir) / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    src.replace(trash / filename)
    rebuild_index(project_dir)
    return True


def rebuild_index(project_dir: Path) -> None:
    """Regenerate ``MEMORY.md`` from the entries on disk."""
    entries = list_entries(project_dir)
    by_type: dict[str, list[dict[str, str]]] = {t: [] for t in _TYPES}
    for e in entries:
        by_type.setdefault(e["type"], []).append(e)
    lines = ["# Urika Project Memory Index", ""]
    for t in _TYPES:
        rows = by_type.get(t, [])
        if not rows:
            continue
        lines.append(f"## {t.capitalize()}")
        for e in rows:
            link = f"[{e['filename']}]({e['filename']})"
            desc = e["description"] or e["body_preview"]
            lines.append(f"- {link} — {desc}")
        lines.append("")
    if not entries:
        lines.append("_(empty — no entries yet)_")
        lines.append("")
    index_path(project_dir).parent.mkdir(parents=True, exist_ok=True)
    index_path(project_dir).write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8"
    )


def parse_and_persist_memory_markers(
    project_dir: Path, agent_text: str
) -> tuple[str, list[Path]]:
    """Strip ``<memory type="...">...</memory>`` markers from agent
    output and persist each as a memory entry.

    Returns ``(stripped_text, written_paths)``. Stripped text is what
    the user sees; the markers themselves never leak into the chat
    panel.

    No-op when ``[memory] auto_capture = false`` in the project's
    ``urika.toml``.
    """
    if not agent_text or "<memory" not in agent_text:
        return agent_text, []
    if not is_enabled(project_dir):
        # Strip markers anyway so the user doesn't see raw XML in
        # the chat.
        stripped = _MEMORY_RE.sub("", agent_text)
        return stripped, []

    written: list[Path] = []

    def _replace(match: re.Match) -> str:
        mem_type = match.group("type").strip().lower()
        body = match.group("body").strip()
        if mem_type not in _TYPES:
            logger.debug("Skipping memory marker with unknown type %r", mem_type)
            return ""
        if not body:
            return ""
        try:
            path = save_entry(project_dir, mem_type=mem_type, body=body)
            written.append(path)
        except Exception as exc:
            logger.warning(
                "Failed to persist memory marker (%s): %s: %s",
                mem_type,
                type(exc).__name__,
                exc,
            )
        return ""

    stripped = _MEMORY_RE.sub(_replace, agent_text)
    return stripped, written
