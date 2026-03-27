"""Scan a source path and classify files by type."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Core tabular/structured data
_TABULAR_EXTENSIONS = {".csv", ".tsv", ".parquet", ".xlsx", ".xls", ".json", ".jsonl"}

# Domain-specific statistical data formats
DOMAIN_DATA_EXTENSIONS = {
    ".sav",
    ".dta",
    ".sas7bdat",
    ".xpt",
    ".rds",
    ".rdata",
    ".feather",
    ".arrow",
}

# Specialized data type categories
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",
    ".gif",
    ".svg",
    ".dicom",
    ".dcm",
    ".nii",
    ".nii.gz",
}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
TIMESERIES_EXTENSIONS = {".hdf5", ".h5", ".hdf", ".mat", ".edf", ".bdf", ".nwb", ".mff"}
SPATIAL_EXTENSIONS = {".ply", ".pcd", ".las", ".laz", ".c3d", ".obj", ".stl"}

# Union of all data extensions
DATA_EXTENSIONS = (
    _TABULAR_EXTENSIONS
    | DOMAIN_DATA_EXTENSIONS
    | IMAGE_EXTENSIONS
    | AUDIO_EXTENSIONS
    | VIDEO_EXTENSIONS
    | TIMESERIES_EXTENSIONS
    | SPATIAL_EXTENSIONS
)

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
    images: list[Path] = field(default_factory=list)
    audio: list[Path] = field(default_factory=list)
    video: list[Path] = field(default_factory=list)
    timeseries: list[Path] = field(default_factory=list)
    spatial: list[Path] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable summary of what was found."""
        lines: list[str] = []
        if self.data_files:
            lines.append(f"Data files: {len(self.data_files)}")

            # Break down by specialized type
            specialized_count = 0
            for label, file_list in [
                ("Images", self.images),
                ("Audio", self.audio),
                ("Video", self.video),
                ("Time series", self.timeseries),
                ("Spatial", self.spatial),
            ]:
                if file_list:
                    formats = sorted(
                        {f.suffix.upper().lstrip(".") for f in file_list}
                    )
                    lines.append(
                        f"  {label}: {len(file_list)} ({', '.join(formats)})"
                    )
                    specialized_count += len(file_list)

            tabular_count = len(self.data_files) - specialized_count
            if tabular_count > 0:
                tabular_files = [
                    f
                    for f in self.data_files
                    if f.suffix.lower()
                    in (_TABULAR_EXTENSIONS | DOMAIN_DATA_EXTENSIONS)
                ]
                if tabular_files:
                    formats = sorted(
                        {f.suffix.upper().lstrip(".") for f in tabular_files}
                    )
                    lines.append(
                        f"  Tabular: {len(tabular_files)} ({', '.join(formats)})"
                    )

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

    # Handle compound extensions like .nii.gz
    name_lower = f.name.lower()
    if name_lower.endswith(".nii.gz"):
        result.data_files.append(f)
        result.images.append(f)
        return

    if ext in DATA_EXTENSIONS:
        result.data_files.append(f)
        # Also classify into specialized type lists
        if ext in IMAGE_EXTENSIONS:
            result.images.append(f)
        elif ext in AUDIO_EXTENSIONS:
            result.audio.append(f)
        elif ext in VIDEO_EXTENSIONS:
            result.video.append(f)
        elif ext in TIMESERIES_EXTENSIONS:
            result.timeseries.append(f)
        elif ext in SPATIAL_EXTENSIONS:
            result.spatial.append(f)
    elif ext in PAPER_EXTENSIONS:
        result.papers.append(f)
    elif ext in DOC_EXTENSIONS:
        result.docs.append(f)
    elif ext in CODE_EXTENSIONS:
        result.code.append(f)
