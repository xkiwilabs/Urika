"""Build curated project tree for dashboard sidebar."""
from __future__ import annotations

from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".gif"}
MARKDOWN_EXTENSIONS = {".md"}


def build_project_tree(project_dir: Path) -> list[dict]:
    """Build a curated tree of project contents for the dashboard sidebar.

    Each node is a dict with:
        label: display name
        type:  section | experiment | folder | file | image | link
        path:  relative path from project root (for files/images/links)
        children: list of child nodes (for sections/folders/experiments)

    Returns a list of top-level section nodes.
    """
    project_dir = Path(project_dir)
    sections: list[dict] = []

    # 1. Experiments
    sections.append(_build_experiments_section(project_dir))

    # 2. Projectbook
    sections.append(_build_projectbook_section(project_dir))

    # 3. Methods
    sections.append(_build_methods_section(project_dir))

    # 4. Criteria
    sections.append(_build_criteria_section(project_dir))

    # 5. Data
    sections.append(_build_data_section(project_dir))

    return sections


def _build_experiments_section(project_dir: Path) -> dict:
    """Scan experiments/ directory and build experiment nodes."""
    experiments_dir = project_dir / "experiments"
    children: list[dict] = []

    if experiments_dir.is_dir():
        exp_dirs = sorted(
            d for d in experiments_dir.iterdir() if d.is_dir()
        )
        for exp_dir in exp_dirs:
            children.append(_build_experiment_node(project_dir, exp_dir))

    return {
        "label": "Experiments",
        "type": "section",
        "children": children,
    }


def _build_experiment_node(project_dir: Path, exp_dir: Path) -> dict:
    """Build a single experiment node with its sub-folders."""
    children: list[dict] = []

    # Labbook
    labbook_dir = exp_dir / "labbook"
    if labbook_dir.is_dir():
        labbook_files = _scan_files(
            project_dir, labbook_dir, MARKDOWN_EXTENSIONS
        )
        children.append({
            "label": "Labbook",
            "type": "folder",
            "children": labbook_files,
        })

    # Artifacts (images)
    artifacts_dir = exp_dir / "artifacts"
    if artifacts_dir.is_dir():
        artifact_files = _scan_files(
            project_dir, artifacts_dir, IMAGE_EXTENSIONS
        )
        children.append({
            "label": "Artifacts",
            "type": "folder",
            "children": artifact_files,
        })

    # Presentation (link if index.html exists)
    pres_dir = exp_dir / "presentation"
    pres_index = pres_dir / "index.html"
    if pres_index.is_file():
        children.append({
            "label": "Presentation",
            "type": "link",
            "path": str(pres_index.relative_to(project_dir)),
        })

    # progress.json
    progress_file = exp_dir / "progress.json"
    if progress_file.is_file():
        children.append({
            "label": "progress.json",
            "type": "file",
            "path": str(progress_file.relative_to(project_dir)),
        })

    # experiment.json
    experiment_file = exp_dir / "experiment.json"
    if experiment_file.is_file():
        children.append({
            "label": "experiment.json",
            "type": "file",
            "path": str(experiment_file.relative_to(project_dir)),
        })

    return {
        "label": exp_dir.name,
        "type": "experiment",
        "children": children,
    }


def _build_projectbook_section(project_dir: Path) -> dict:
    """Scan projectbook/ directory for markdown files and figures."""
    pb_dir = project_dir / "projectbook"
    children: list[dict] = []

    if pb_dir.is_dir():
        allowed = MARKDOWN_EXTENSIONS | IMAGE_EXTENSIONS
        children = _scan_files(project_dir, pb_dir, allowed)

        # Also check for presentations
        for item in sorted(pb_dir.iterdir()):
            if item.is_dir() and (item / "index.html").is_file():
                children.append({
                    "label": item.name,
                    "type": "link",
                    "path": str((item / "index.html").relative_to(project_dir)),
                })

    return {
        "label": "Projectbook",
        "type": "section",
        "children": children,
    }


def _build_methods_section(project_dir: Path) -> dict:
    """Single entry pointing to methods.json if it exists."""
    children: list[dict] = []
    methods_file = project_dir / "methods.json"
    if methods_file.is_file():
        children.append({
            "label": "methods.json",
            "type": "file",
            "path": str(methods_file.relative_to(project_dir)),
        })
    return {
        "label": "Methods",
        "type": "section",
        "children": children,
    }


def _build_criteria_section(project_dir: Path) -> dict:
    """Single entry pointing to criteria.json if it exists."""
    children: list[dict] = []
    criteria_file = project_dir / "criteria.json"
    if criteria_file.is_file():
        children.append({
            "label": "criteria.json",
            "type": "file",
            "path": str(criteria_file.relative_to(project_dir)),
        })
    return {
        "label": "Criteria",
        "type": "section",
        "children": children,
    }


def _build_data_section(project_dir: Path) -> dict:
    """Entry pointing to urika.toml data info."""
    children: list[dict] = []
    toml_file = project_dir / "urika.toml"
    if toml_file.is_file():
        children.append({
            "label": "urika.toml",
            "type": "file",
            "path": str(toml_file.relative_to(project_dir)),
        })
    return {
        "label": "Data",
        "type": "section",
        "children": children,
    }


def _scan_files(
    project_dir: Path, directory: Path, extensions: set[str]
) -> list[dict]:
    """Scan a directory for files matching the given extensions."""
    files: list[dict] = []
    for item in sorted(directory.iterdir()):
        if not item.is_file():
            continue
        ext = item.suffix.lower()
        if ext not in extensions:
            continue
        file_type = "image" if ext in IMAGE_EXTENSIONS else "file"
        files.append({
            "label": item.name,
            "type": file_type,
            "path": str(item.relative_to(project_dir)),
        })
    return files
