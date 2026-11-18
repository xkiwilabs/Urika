"""Layered code walkthrough for a method script.

Four layers, coarse to fine, for a reader who directs and verifies
analyses without writing code:

1. **Key steps**: one line per step, in script order, with line ranges.
2. **Pseudocode**: one plain line per step.
3. **Annotated snippets**: each step's source with its explanation.
4. **Full script**: the file as run, verbatim, line-numbered.

Steps are derived from the script's AST: a block of imports, each
function or class, the ``if __name__ == "__main__"`` block, and runs of
top-level statements separated by blank or comment lines. A comment
immediately above a block becomes its title. Everything here is pure
code: no model is called, nothing is invented, and an explanation that
was not supplied renders as not generated. The walkthrough is a map for
locating a step, never a substitute for checking what the run did.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from urika.core.report_writer import write_versioned

logger = logging.getLogger(__name__)

NOT_GENERATED = "Explanation not generated (deterministic walkthrough)."


@dataclass
class Step:
    index: int
    title: str
    kind: str  # imports | function | class | main | statements
    start_line: int
    end_line: int
    source: str
    calls: list[str] = field(default_factory=list)
    signature: str = ""  # functions only: name(args)


@dataclass
class Walkthrough:
    script: str
    source: str
    steps: list[Step] = field(default_factory=list)
    parse_error: str | None = None


# ── Building ───────────────────────────────────────────────────────


def build_walkthrough(source: str, *, script: str = "") -> Walkthrough:
    """Derive the step structure of *source*. Never raises: a script
    that does not parse yields no steps and a ``parse_error``."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return Walkthrough(
            script=script,
            source=source,
            parse_error=f"{exc.msg} (line {exc.lineno})",
        )
    lines = source.splitlines()
    groups = _group_top_level(tree, lines)
    steps: list[Step] = []
    for idx, (kind, nodes) in enumerate(groups, start=1):
        start = nodes[0].lineno
        end = max(getattr(n, "end_lineno", n.lineno) or n.lineno for n in nodes)
        # Pull a decorator line range into the step as well.
        for n in nodes:
            for dec in getattr(n, "decorator_list", []) or []:
                start = min(start, dec.lineno)
        title = _title_for(kind, nodes, lines, start)
        signature = (
            _signature(nodes[0])
            if isinstance(nodes[0], (ast.FunctionDef, ast.AsyncFunctionDef))
            else ""
        )
        steps.append(
            Step(
                index=idx,
                title=title,
                kind=kind,
                start_line=start,
                end_line=end,
                source="\n".join(lines[start - 1 : end]),
                calls=_calls_in(nodes),
                signature=signature,
            )
        )
    return Walkthrough(script=script, source=source, steps=steps)


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
        return False
    left, right = test.left, test.comparators[0]
    names = {
        getattr(left, "id", None),
        getattr(right, "value", None) if isinstance(right, ast.Constant) else None,
    }
    other = {
        getattr(right, "id", None),
        getattr(left, "value", None) if isinstance(left, ast.Constant) else None,
    }
    return "__name__" in names | other and "__main__" in names | other


def _group_top_level(
    tree: ast.Module, lines: list[str]
) -> list[tuple[str, list[ast.stmt]]]:
    groups: list[tuple[str, list[ast.stmt]]] = []
    prev_end = 0
    for node in tree.body:
        if _is_docstring(node) and not groups:
            prev_end = node.end_lineno or node.lineno
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if groups and groups[-1][0] == "imports":
                groups[-1][1].append(node)
            else:
                groups.append(("imports", [node]))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            groups.append(("function", [node]))
        elif isinstance(node, ast.ClassDef):
            groups.append(("class", [node]))
        elif _is_main_guard(node):
            groups.append(("main", [node]))
        else:
            separated = _separated(lines, prev_end, node.lineno)
            if groups and groups[-1][0] == "statements" and not separated:
                groups[-1][1].append(node)
            else:
                groups.append(("statements", [node]))
        prev_end = node.end_lineno or node.lineno
    return groups


def _separated(lines: list[str], prev_end: int, next_start: int) -> bool:
    """True when a blank or comment line sits between two statements."""
    for ln in range(prev_end + 1, next_start):
        text = lines[ln - 1].strip() if ln - 1 < len(lines) else ""
        if text == "" or text.startswith("#"):
            return True
    return False


def _leading_comment(lines: list[str], start_line: int) -> str:
    """Comment lines directly above *start_line*, joined, or ''."""
    out: list[str] = []
    ln = start_line - 1
    while ln >= 1:
        text = lines[ln - 1].strip()
        if text.startswith("#"):
            out.append(text.lstrip("#").strip())
            ln -= 1
            continue
        break
    out.reverse()
    out = [o for o in out if o and not re.fullmatch(r"[-=~*#]+", o)]
    return " ".join(out)


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        args = ast.unparse(node.args)
    except Exception:  # noqa: BLE001 — unparse is best-effort
        args = ""
    return f"{node.name}({args})"


def _title_for(
    kind: str, nodes: list[ast.stmt], lines: list[str], start_line: int
) -> str:
    comment = _leading_comment(lines, start_line)
    first = nodes[0]
    if kind == "imports":
        return comment or "Import libraries"
    if kind == "function":
        assert isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef))
        return comment or f"Define function {_signature(first)}"
    if kind == "class":
        assert isinstance(first, ast.ClassDef)
        return comment or f"Define class {first.name}"
    if kind == "main":
        return "Run as a script (main block)"
    if comment:
        return comment
    return _derived_statement_title(nodes)


def _derived_statement_title(nodes: list[ast.stmt]) -> str:
    first = nodes[0]
    calls = _calls_in([first])
    if isinstance(first, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = []
        tgt_nodes = first.targets if isinstance(first, ast.Assign) else [first.target]
        for t in tgt_nodes:
            try:
                targets.append(ast.unparse(t))
            except Exception as exc:  # noqa: BLE001 — unparse is best-effort
                logger.debug("could not unparse assignment target: %s", exc)
        what = ", ".join(targets) or "a value"
        if calls:
            return f"Compute {what} with {calls[0]}"
        return f"Set {what}"
    if calls:
        return f"Call {calls[0]}"
    if isinstance(first, ast.For):
        return "Loop over items"
    if isinstance(first, ast.If):
        return "Conditional step"
    if isinstance(first, ast.With):
        return "Context-managed step"
    return type(first).__name__.lower().replace("stmt", "") + " step"


def _calls_in(nodes: list[ast.stmt], limit: int = 8) -> list[str]:
    seen: list[str] = []
    for node in nodes:
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            fn = sub.func
            name = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else None
            )
            if name and name not in seen and name not in ("print", "len", "str"):
                seen.append(name)
            if len(seen) >= limit:
                return seen
    return seen


# ── Pseudocode ─────────────────────────────────────────────────────


def default_pseudocode(walkthrough: Walkthrough) -> list[str]:
    """One numbered plain line per step, derived from titles and calls."""
    out: list[str] = []
    for s in walkthrough.steps:
        line = f"{s.index}. {s.title}"
        if s.kind == "function" and s.signature and s.signature not in s.title:
            line += f" (function {s.signature})"
        if s.kind == "function" and s.calls:
            line += f" — uses {', '.join(s.calls[:4])}"
        elif s.kind == "statements" and s.calls and s.calls[0] not in s.title:
            line += f" — uses {', '.join(s.calls[:3])}"
        out.append(line)
    return out


# ── Rendering ──────────────────────────────────────────────────────


def render_walkthrough_markdown(
    walkthrough: Walkthrough,
    *,
    explanations: dict[int, str] | None = None,
    pseudocode: list[str] | None = None,
    method_name: str = "",
) -> str:
    """Render the four layers. *explanations* maps step index → prose
    (supplied by a caller that has it; nothing is invented here)."""
    name = Path(walkthrough.script).name if walkthrough.script else "script"
    expl = explanations or {}
    lines: list[str] = [
        f"# Code walkthrough: {name}",
        "",
        f"- **Method:** {method_name or Path(name).stem}",
        f"- **Script:** `{walkthrough.script or name}`",
        (
            "- **How this was made:** Generated by code from the script as it "
            "was run. Step boundaries and titles come from the script's own "
            "structure and comments. No model was involved."
        ),
        "",
        (
            "Use it to *locate* a step (where are features scaled? which rows are "
            "dropped?) and then check that step against what you asked for. It "
            "does not verify anything by itself."
        ),
        "",
        "## 1. Key steps",
        "",
    ]
    if walkthrough.parse_error:
        lines += [
            (
                f"The script could not be parsed ({walkthrough.parse_error}), so no "
                "steps, pseudocode or snippets are available. The full script is "
                "below."
            ),
            "",
        ]
    else:
        for s in walkthrough.steps:
            lines.append(f"{s.index}. {s.title} (lines {s.start_line}–{s.end_line})")
        lines.append("")

    lines += ["## 2. Pseudocode", ""]
    if walkthrough.parse_error:
        lines += ["_Not available: the script could not be parsed._", ""]
    else:
        lines += [
            "```text",
            *(pseudocode or default_pseudocode(walkthrough)),
            "```",
            "",
        ]

    lines += ["## 3. Annotated snippets", ""]
    if walkthrough.parse_error:
        lines += ["_Not available: the script could not be parsed._", ""]
    else:
        for s in walkthrough.steps:
            lines += [
                f"### Step {s.index}: {s.title}",
                "",
                f"Lines {s.start_line}–{s.end_line}."
                + (f" Calls: {', '.join(s.calls)}." if s.calls else ""),
                "",
                expl.get(s.index, NOT_GENERATED),
                "",
                "```python",
                s.source,
                "```",
                "",
            ]

    lines += ["## 4. Full script", "", "```text"]
    width = max(3, len(str(max(1, len(walkthrough.source.splitlines())))))
    for i, text in enumerate(walkthrough.source.splitlines(), start=1):
        lines.append(f"{i:>{width}} | {text}")
    lines += ["```", ""]
    return "\n".join(lines)


# ── Finalize hook ──────────────────────────────────────────────────


def _inside(path: Path, root: Path) -> bool:
    """True when *path* (symlinks resolved) lies within *root*."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def generate_walkthroughs(project_dir: Path) -> list[Path]:
    """Write ``methods/<name>_walkthrough.md`` for every final method in
    findings.json whose script exists. Missing or malformed findings,
    or a missing script, produce no file; nothing is invented."""
    findings_path = project_dir / "projectbook" / "findings.json"
    if not findings_path.exists():
        return []
    try:
        findings: Any = json.loads(findings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("findings.json unreadable for walkthroughs: %s", exc)
        return []
    entries = findings.get("final_methods") if isinstance(findings, dict) else None
    if not isinstance(entries, list):
        return []
    written: list[Path] = []
    methods_dir = project_dir / "methods"
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        script = str(entry.get("script") or "").strip()
        if not name or not script:
            continue
        script_path = project_dir / script
        if not _inside(script_path, project_dir):
            # findings.json is agent-written; never read outside the project.
            logger.warning("Walkthrough refused: %s is outside the project", script)
            continue
        if not script_path.is_file():
            logger.info("Walkthrough skipped: %s not found", script)
            continue
        try:
            source = script_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Walkthrough skipped for %s: %s", script, exc)
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "method"
        md = render_walkthrough_markdown(
            build_walkthrough(source, script=script), method_name=name
        )
        methods_dir.mkdir(parents=True, exist_ok=True)
        written.append(write_versioned(methods_dir / f"{slug}_walkthrough.md", md))
    return written
