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

import logging
import re
from datetime import date as _date
from pathlib import Path

logger = logging.getLogger(__name__)


_TYPES = ("user", "feedback", "instruction", "decision", "reference")
# Soft cap: when injected memory exceeds this byte count, agents
# still see it but a warning fires. Hard cap is 4× this in
# ``load_project_memory`` — past which the inject is truncated and
# an explicit "[memory truncated …]" line appears.
_SOFT_CAP_BYTES = 5_000
_HARD_CAP_BYTES = 20_000

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
    body = rest[end + len("\n---\n"):]
    meta: dict[str, str] = {}
    for line in head.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, body


def load_project_memory(project_dir: Path) -> str:
    """Read every memory file, return a system-prompt-ready block.

    Empty string when memory dir is missing or empty. Soft-capped at
    5 KB (warns); hard-capped at 20 KB (truncates + appends a
    truncation marker).
    """
    entries = list_entries(project_dir)
    if not entries:
        return ""
    parts: list[str] = ["## Project Memory", ""]
    parts.append(
        "The following persistent project memory shapes how you should "
        "approach this project. Honor these preferences and decisions "
        "unless the user explicitly overrides them in this session."
    )
    parts.append("")
    for e in entries:
        d = memory_dir(project_dir) / e["filename"]
        try:
            text = d.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "Could not read memory file %s: %s", d, exc
            )
            continue
        _meta, body = _split_frontmatter(text)
        parts.append(f"### {e['type']}: {e['name']}")
        if e["description"]:
            parts.append(f"_{e['description']}_")
        parts.append("")
        parts.append(body.strip())
        parts.append("")
    blob = "\n".join(parts).rstrip() + "\n"
    if len(blob) > _SOFT_CAP_BYTES:
        logger.warning(
            "Project memory exceeds soft cap (%d > %d bytes) — "
            "consider running `urika memory list` and pruning",
            len(blob),
            _SOFT_CAP_BYTES,
        )
    if len(blob) > _HARD_CAP_BYTES:
        truncated = blob[: _HARD_CAP_BYTES]
        return (
            truncated
            + "\n\n[memory truncated at hard cap — run `urika memory list` to prune]\n"
        )
    return blob


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
            logger.debug(
                "Skipping memory marker with unknown type %r", mem_type
            )
            return ""
        if not body:
            return ""
        try:
            path = save_entry(
                project_dir, mem_type=mem_type, body=body
            )
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
