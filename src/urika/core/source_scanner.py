"""Scan a source path and classify files by type."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DATA_EXTENSIONS = {".csv", ".tsv", ".parquet", ".xlsx", ".xls", ".json", ".jsonl"}
DOC_EXTENSIONS = {".md", ".txt", ".rst", ".html"}
CODE_EXTENSIONS = {".py", ".r", ".jl", ".ipynb"}
PAPER_EXTENSIONS = {".pdf"}


@dataclass
class ScanResult:
    """Result of scanning a source path."""

    root: Path
    data_files: list[Path] = field(default_factory=list)
    data_directories: list[Path] = field(default_factory=list)
    docs: list[Path] = field(default_factory=list)
    papers: list[Path] = field(default_factory=list)
    code: list[Path] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable summary of what was found."""
        lines: list[str] = []
        if self.data_files:
            lines.append(f"Data files: {len(self.data_files)}")
            for d in self.data_directories:
                count = sum(
                    1 for f in self.data_files if d in f.parents or f.parent == d
                )
                lines.append(f"  {d.relative_to(self.root)}/ — {count} files")
        if self.docs:
            lines.append(f"Documentation: {len(self.docs)}")
            for d in self.docs:
                lines.append(f"  {d.relative_to(self.root)}")
        if self.papers:
            lines.append(f"Research papers: {len(self.papers)}")
            for p in self.papers:
                lines.append(f"  {p.relative_to(self.root)}")
        if self.code:
            lines.append(f"Code files: {len(self.code)}")
            for c in self.code:
                lines.append(f"  {c.relative_to(self.root)}")
        if not lines:
            lines.append("No recognized files found.")
        return "\n".join(lines)


def scan_source_path(path: Path) -> ScanResult:
    """Scan a path and classify all files by type."""
    result = ScanResult(root=path if path.is_dir() else path.parent)

    if path.is_file():
        _classify_file(path, result)
        return result

    if not path.is_dir():
        return result

    data_dirs: set[Path] = set()
    for f in sorted(path.rglob("*")):
        if not f.is_file():
            continue
        if f.name.startswith("."):
            continue
        _classify_file(f, result)
        if f.suffix.lower() in DATA_EXTENSIONS:
            data_dirs.add(f.parent)

    result.data_directories = sorted(data_dirs)
    return result


def _classify_file(f: Path, result: ScanResult) -> None:
    """Classify a single file into the appropriate list."""
    ext = f.suffix.lower()
    if ext in DATA_EXTENSIONS:
        result.data_files.append(f)
    elif ext in PAPER_EXTENSIONS:
        result.papers.append(f)
    elif ext in DOC_EXTENSIONS:
        result.docs.append(f)
    elif ext in CODE_EXTENSIONS:
        result.code.append(f)
