"""Export markdown artifacts to LaTeX / PDF via pandoc.

``urika report --format latex|pdf`` and ``urika finalize --format ...``
post-process the markdown artifact the agents already wrote — agents
stay format-agnostic; export is a pure function over the file.

Three DISTINCT actionable failure modes, each its own
:class:`ExportError` message:

1. pypandoc (the Python package) is not installed → install the
   ``export`` extra (``pip install 'urika[export]'``);
2. pypandoc is installed but the pandoc *binary* is missing → distro
   install hint (apt/brew/choco). Deliberately NO
   ``pypandoc.download_pandoc()`` — zero magic downloads;
3. ``fmt="pdf"`` but no TeX engine is available → texlive hint, plus
   the note that ``--format latex`` works without one.

Versioning: ``.tex`` output is text and goes through
:func:`urika.core.report_writer.write_versioned`. PDF is binary —
``write_versioned`` writes via ``Path.write_text`` so it cannot carry
the bytes, but its history step (``shutil.copy2`` to a ``-YYYY-MM-DD``
sibling, ``-N`` suffix on same-day collisions) is binary-safe;
:func:`_version_existing` mirrors exactly that naming for an existing
``.pdf`` before pandoc overwrites the target in place.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from urika.core.report_writer import write_versioned

logger = logging.getLogger(__name__)

# Small LaTeX header include: margins + sans-serif headings, echoing
# the reveal.js deck aesthetic. Everything else is pandoc's default
# template.
_HEADER_TEX = Path(__file__).parent.parent / "templates" / "export" / "header.tex"

_PYPANDOC_MISSING = (
    "PDF/LaTeX export needs the export extra: pip install 'urika[export]'"
)
_PANDOC_BINARY_MISSING = (
    "pypandoc is installed but the pandoc binary was not found on PATH. "
    "Install it from your package manager — Debian/Ubuntu: "
    "sudo apt install pandoc; macOS: brew install pandoc; "
    "Windows: choco install pandoc — then re-run."
)
_TEX_ENGINE_MISSING = (
    "PDF needs a LaTeX engine (e.g. texlive: sudo apt install "
    "texlive-latex-recommended); `--format latex` works without one."
)


class ExportError(RuntimeError):
    """Actionable export failure — the message says what to install."""


def export_markdown(md_path: Path, fmt: str, out_dir: Path | None = None) -> Path:
    """Convert a markdown artifact to ``fmt`` in {"latex", "pdf"}.

    Returns the written path: ``<stem>.tex`` (versioned via
    ``write_versioned``) or ``<stem>.pdf`` (previous version preserved
    as a timestamped sibling — see module docstring), next to
    ``md_path`` unless ``out_dir`` is given. Raises :class:`ExportError`
    with an actionable message on any missing dependency, and
    ``ValueError`` on an unknown ``fmt``.
    """
    if fmt not in ("latex", "pdf"):
        raise ValueError(f"fmt must be 'latex' or 'pdf', got {fmt!r}")
    md_path = Path(md_path)
    if not md_path.exists():
        raise ExportError(f"Markdown artifact not found: {md_path}")

    try:
        import pypandoc
    except ImportError as exc:
        raise ExportError(_PYPANDOC_MISSING) from exc

    try:
        pypandoc.get_pandoc_path()
    except OSError as exc:
        raise ExportError(_PANDOC_BINARY_MISSING) from exc

    target_dir = Path(out_dir) if out_dir is not None else md_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    # Search both the artifact's own directory (projectbook/ figure
    # links like ``figures/x.png``) and its parent (the project dir,
    # for ``projectbook/figures/x.png``-style links) for resources.
    resource_path = os.pathsep.join([str(md_path.parent), str(md_path.parent.parent)])
    extra_args = [
        "--standalone",
        f"--include-in-header={_HEADER_TEX}",
        f"--resource-path={resource_path}",
    ]

    if fmt == "latex":
        out_path = target_dir / f"{md_path.stem}.tex"
        try:
            tex = pypandoc.convert_file(
                str(md_path), to="latex", format="markdown", extra_args=extra_args
            )
        except (RuntimeError, OSError) as exc:
            raise ExportError(f"LaTeX conversion failed: {exc}") from exc
        return write_versioned(out_path, tex)

    out_path = target_dir / f"{md_path.stem}.pdf"
    _version_existing(out_path)
    try:
        pypandoc.convert_file(
            str(md_path),
            to="pdf",
            format="markdown",
            outputfile=str(out_path),
            extra_args=extra_args,
        )
    except (RuntimeError, OSError) as exc:
        # pandoc's "pdflatex not found" (or any other pdf-stage error)
        # — the actionable fix is the same: install a TeX engine or
        # fall back to --format latex. Keep the underlying error for
        # the cases where TeX is present but the document failed.
        raise ExportError(f"{_TEX_ENGINE_MISSING} Underlying error: {exc}") from exc
    return out_path


def _version_existing(path: Path) -> None:
    """Binary-safe mirror of ``write_versioned``'s history step.

    Copies an existing ``path`` to ``<stem>-YYYY-MM-DD<suffix>``
    (``-N`` on same-day collisions) so pandoc can overwrite the target
    in place without losing the previous export.
    """
    if not path.exists():
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    versioned = path.parent / f"{path.stem}-{stamp}{path.suffix}"
    counter = 1
    while versioned.exists():
        versioned = path.parent / f"{path.stem}-{stamp}-{counter}{path.suffix}"
        counter += 1
    shutil.copy2(path, versioned)
