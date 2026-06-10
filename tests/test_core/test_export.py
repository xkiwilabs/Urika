"""Tests for the pandoc export module (``core/export.py``).

``export_markdown`` converts a markdown artifact to LaTeX or PDF via
pypandoc. The core contract is THREE DISTINCT actionable errors —
each tells the user exactly what to install:

1. pypandoc (the Python package) missing → install the export extra;
2. pypandoc present but the pandoc *binary* missing → distro install
   hint (apt/brew/choco), never an automatic download;
3. ``fmt="pdf"`` with no TeX engine → texlive hint, plus the note
   that ``--format latex`` works without one.

Unit tests mock pypandoc (a fake module injected into ``sys.modules``)
so they run everywhere; one ``@pytest.mark.integration`` test does a
real md→tex conversion, gated on pypandoc + the pandoc binary.

Versioning: ``.tex`` goes through ``write_versioned`` (text). PDF is
binary — ``write_versioned`` writes via ``write_text`` so it cannot
carry the bytes, but its history step (``shutil.copy2`` to a
``-YYYY-MM-DD`` sibling) is binary-safe; ``export_markdown`` mirrors
exactly that naming for an existing ``.pdf`` before pandoc overwrites
the target. Pinned here.
"""

from __future__ import annotations

import shutil
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from urika.core.export import ExportError, export_markdown

_FAKE_TEX = "\\documentclass{article}\n\\begin{document}fake\\end{document}\n"


def _install_fake_pypandoc(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pandoc_path: str | None = "/usr/bin/pandoc",
    convert_error: Exception | None = None,
) -> list[dict]:
    """Inject a fake ``pypandoc`` module; returns the convert_file call log."""
    calls: list[dict] = []
    fake = types.ModuleType("pypandoc")

    def get_pandoc_path() -> str:
        if pandoc_path is None:
            raise OSError("No pandoc was found")
        return pandoc_path

    def convert_file(
        source_file: str,
        to: str | None = None,
        format: str | None = None,  # noqa: A002 — pypandoc's own kwarg name
        outputfile: str | None = None,
        extra_args: list[str] | None = None,
    ) -> str:
        calls.append(
            {
                "source_file": source_file,
                "to": to,
                "format": format,
                "outputfile": outputfile,
                "extra_args": list(extra_args or []),
            }
        )
        if convert_error is not None:
            raise convert_error
        if outputfile:
            Path(outputfile).write_bytes(b"%PDF-1.4 fake pdf bytes")
            return ""
        return _FAKE_TEX

    fake.get_pandoc_path = get_pandoc_path  # type: ignore[attr-defined]
    fake.convert_file = convert_file  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypandoc", fake)
    return calls


@pytest.fixture
def md_path(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    book = proj / "projectbook"
    book.mkdir(parents=True)
    path = book / "final-report.md"
    path.write_text(
        "# Final Report\n\nR²=0.41.\n\n![fig](figures/fig1.png)\n",
        encoding="utf-8",
    )
    return path


class TestLatexExport:
    def test_writes_tex_next_to_markdown(self, md_path: Path, monkeypatch) -> None:
        _install_fake_pypandoc(monkeypatch)
        out = export_markdown(md_path, "latex")
        assert out == md_path.parent / "final-report.tex"
        assert out.read_text(encoding="utf-8") == _FAKE_TEX

    def test_passes_standalone_header_and_resource_path(
        self, md_path: Path, monkeypatch
    ) -> None:
        calls = _install_fake_pypandoc(monkeypatch)
        export_markdown(md_path, "latex")
        (call,) = calls
        assert call["to"] == "latex"
        assert call["source_file"] == str(md_path)
        args = call["extra_args"]
        assert "--standalone" in args
        header_args = [a for a in args if a.startswith("--include-in-header=")]
        assert len(header_args) == 1
        header = Path(header_args[0].split("=", 1)[1])
        assert header.name == "header.tex"
        assert header.exists(), "the bundled header.tex template must exist"
        resource_args = [a for a in args if a.startswith("--resource-path=")]
        assert len(resource_args) == 1
        # Both the artifact's own dir (projectbook/) and the project
        # dir must be searchable so relative figure links resolve.
        assert str(md_path.parent) in resource_args[0]
        assert str(md_path.parent.parent) in resource_args[0]

    def test_rewrites_are_versioned(self, md_path: Path, monkeypatch) -> None:
        _install_fake_pypandoc(monkeypatch)
        out = export_markdown(md_path, "latex")
        old = out.read_text(encoding="utf-8")
        export_markdown(md_path, "latex")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sibling = out.parent / f"final-report-{stamp}.tex"
        assert sibling.exists(), "re-export must keep the previous .tex version"
        assert sibling.read_text(encoding="utf-8") == old

    def test_out_dir_honored(self, md_path: Path, tmp_path: Path, monkeypatch) -> None:
        _install_fake_pypandoc(monkeypatch)
        out_dir = tmp_path / "elsewhere"
        out = export_markdown(md_path, "latex", out_dir=out_dir)
        assert out == out_dir / "final-report.tex"
        assert out.exists()

    def test_conversion_failure_raises_export_error(
        self, md_path: Path, monkeypatch
    ) -> None:
        _install_fake_pypandoc(
            monkeypatch, convert_error=RuntimeError("pandoc died, exitcode 1")
        )
        with pytest.raises(ExportError, match="pandoc died"):
            export_markdown(md_path, "latex")


class TestPdfExport:
    def test_writes_pdf_via_outputfile(self, md_path: Path, monkeypatch) -> None:
        calls = _install_fake_pypandoc(monkeypatch)
        out = export_markdown(md_path, "pdf")
        assert out == md_path.parent / "final-report.pdf"
        assert out.read_bytes().startswith(b"%PDF")
        (call,) = calls
        assert call["outputfile"] == str(out)

    def test_tectonic_fallback_when_pdflatex_absent(
        self, md_path: Path, monkeypatch
    ) -> None:
        """Conda-only boxes have tectonic, not pdflatex — pandoc must
        be pointed at it explicitly or the PDF stage fails."""
        import urika.core.export as export_mod

        calls = _install_fake_pypandoc(monkeypatch)
        monkeypatch.setattr(
            export_mod.shutil,
            "which",
            lambda name: "/usr/bin/tectonic" if name == "tectonic" else None,
        )
        export_markdown(md_path, "pdf")
        (call,) = calls
        assert "--pdf-engine=tectonic" in call["extra_args"]

    def test_no_engine_override_when_pdflatex_present(
        self, md_path: Path, monkeypatch
    ) -> None:
        import urika.core.export as export_mod

        calls = _install_fake_pypandoc(monkeypatch)
        monkeypatch.setattr(export_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
        export_markdown(md_path, "pdf")
        (call,) = calls
        assert not any("--pdf-engine" in a for a in call["extra_args"])

    def test_existing_pdf_is_versioned_binary_safely(
        self, md_path: Path, monkeypatch
    ) -> None:
        _install_fake_pypandoc(monkeypatch)
        out = md_path.parent / "final-report.pdf"
        old_bytes = b"%PDF-1.4 old binary \x00\x01\x02 content"
        out.write_bytes(old_bytes)
        export_markdown(md_path, "pdf")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sibling = out.parent / f"final-report-{stamp}.pdf"
        assert sibling.exists(), "re-export must keep the previous .pdf version"
        assert sibling.read_bytes() == old_bytes
        assert out.read_bytes().startswith(b"%PDF-1.4 fake")

    def test_versioned_sibling_never_overwritten_same_day(
        self, md_path: Path, monkeypatch
    ) -> None:
        _install_fake_pypandoc(monkeypatch)
        export_markdown(md_path, "pdf")
        export_markdown(md_path, "pdf")
        export_markdown(md_path, "pdf")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert (md_path.parent / f"final-report-{stamp}.pdf").exists()
        assert (md_path.parent / f"final-report-{stamp}-1.pdf").exists()

    def test_missing_tex_engine_raises_actionable_error(
        self, md_path: Path, monkeypatch
    ) -> None:
        _install_fake_pypandoc(
            monkeypatch,
            convert_error=RuntimeError(
                "pdflatex not found. Please select a different --pdf-engine"
            ),
        )
        with pytest.raises(ExportError) as excinfo:
            export_markdown(md_path, "pdf")
        message = str(excinfo.value)
        assert "LaTeX engine" in message
        assert "texlive" in message
        assert "--format latex" in message, (
            "the error must point at the no-TeX-needed fallback"
        )


class TestDistinctErrors:
    def test_pypandoc_missing_points_at_export_extra(
        self, md_path: Path, monkeypatch
    ) -> None:
        # None in sys.modules makes ``import pypandoc`` raise ImportError.
        monkeypatch.setitem(sys.modules, "pypandoc", None)
        with pytest.raises(ExportError, match=r"urika\[export\]"):
            export_markdown(md_path, "latex")

    def test_pandoc_binary_missing_points_at_distro_install(
        self, md_path: Path, monkeypatch
    ) -> None:
        _install_fake_pypandoc(monkeypatch, pandoc_path=None)
        with pytest.raises(ExportError) as excinfo:
            export_markdown(md_path, "latex")
        message = str(excinfo.value)
        assert "apt install pandoc" in message
        assert "brew install pandoc" in message
        assert "urika[export]" not in message, (
            "binary-missing must be distinct from package-missing"
        )

    def test_unknown_format_raises_value_error(
        self, md_path: Path, monkeypatch
    ) -> None:
        _install_fake_pypandoc(monkeypatch)
        with pytest.raises(ValueError, match="docx"):
            export_markdown(md_path, "docx")

    def test_missing_markdown_artifact_raises_export_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _install_fake_pypandoc(monkeypatch)
        with pytest.raises(ExportError, match="not found"):
            export_markdown(tmp_path / "nope.md", "latex")


class TestHeaderTemplate:
    def test_header_sets_margins(self) -> None:
        from urika.core.export import _HEADER_TEX

        body = _HEADER_TEX.read_text(encoding="utf-8")
        assert "geometry" in body, "header.tex must set page margins"
        assert "sffamily" in body, "header.tex must set sans-serif headings"


@pytest.mark.integration
def test_real_pandoc_markdown_to_latex(tmp_path: Path) -> None:
    """Real md→tex conversion — only runs when pypandoc AND the pandoc
    binary are both available (absent on most CI/dev boxes)."""
    pytest.importorskip("pypandoc")
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc binary not installed")
    md = tmp_path / "report.md"
    md.write_text("# Title\n\nSome **bold** prose.\n", encoding="utf-8")
    out = export_markdown(md, "latex")
    body = out.read_text(encoding="utf-8")
    assert "\\documentclass" in body
    assert "Some \\textbf{bold} prose." in body
