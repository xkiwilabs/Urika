"""Tests for source path scanner."""

from __future__ import annotations

from pathlib import Path

from urika.core.source_scanner import scan_source_path, ScanResult


class TestScanSourcePath:
    def test_classifies_csv_files(self, tmp_path: Path) -> None:
        (tmp_path / "data.csv").write_text("x,y\n1,2\n")
        result = scan_source_path(tmp_path)
        assert len(result.data_files) == 1

    def test_classifies_pdfs_as_papers(self, tmp_path: Path) -> None:
        (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
        result = scan_source_path(tmp_path)
        assert len(result.papers) == 1

    def test_classifies_markdown_as_docs(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Title\n")
        result = scan_source_path(tmp_path)
        assert len(result.docs) == 1

    def test_classifies_python_as_code(self, tmp_path: Path) -> None:
        (tmp_path / "script.py").write_text("print('hello')\n")
        result = scan_source_path(tmp_path)
        assert len(result.code) == 1

    def test_nested_directories(self, tmp_path: Path) -> None:
        sub = tmp_path / "data" / "group1"
        sub.mkdir(parents=True)
        (sub / "trial1.csv").write_text("a,b\n1,2\n")
        (sub / "trial2.csv").write_text("a,b\n3,4\n")
        result = scan_source_path(tmp_path)
        assert len(result.data_files) == 2

    def test_data_directories_grouped(self, tmp_path: Path) -> None:
        sub1 = tmp_path / "2Player"
        sub2 = tmp_path / "3Player"
        sub1.mkdir()
        sub2.mkdir()
        (sub1 / "t1.csv").write_text("x\n1\n")
        (sub2 / "t2.csv").write_text("x\n2\n")
        result = scan_source_path(tmp_path)
        assert len(result.data_directories) >= 2

    def test_single_file_path(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("x,y\n1,2\n")
        result = scan_source_path(f)
        assert len(result.data_files) == 1

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = scan_source_path(tmp_path)
        assert len(result.data_files) == 0
        assert len(result.papers) == 0

    def test_summary_string(self, tmp_path: Path) -> None:
        (tmp_path / "data.csv").write_text("x\n1\n")
        (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4")
        result = scan_source_path(tmp_path)
        summary = result.summary()
        assert "Data files" in summary

    def test_skips_dotfiles(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden.csv").write_text("x\n1\n")
        (tmp_path / "visible.csv").write_text("x\n1\n")
        result = scan_source_path(tmp_path)
        assert len(result.data_files) == 1

    def test_multiple_file_types(self, tmp_path: Path) -> None:
        (tmp_path / "data.csv").write_text("x\n1\n")
        (tmp_path / "data.parquet").write_bytes(b"fake")
        (tmp_path / "readme.md").write_text("# Hi\n")
        (tmp_path / "thesis.pdf").write_bytes(b"%PDF")
        (tmp_path / "script.py").write_text("x=1\n")
        result = scan_source_path(tmp_path)
        assert len(result.data_files) == 2
        assert len(result.docs) == 1
        assert len(result.papers) == 1
        assert len(result.code) == 1

    def test_scan_result_dataclass_fields(self) -> None:
        result = ScanResult(root=Path("/tmp"))
        assert result.data_files == []
        assert result.papers == []
        assert result.docs == []
        assert result.code == []
        assert result.data_directories == []


class TestSpecializedClassifications:
    """Coverage for the specialized type lists — images / audio / video
    / timeseries / spatial / domain-data — and the compound ``.nii.gz``
    dual classification. Pre-this-class only CSV/PDF/MD/Python/Parquet
    were tested; a neuroscience user uploading ``.nii.gz`` was running
    into untested code in production."""

    def test_image_extensions_classified_into_data_and_images(
        self, tmp_path: Path
    ) -> None:
        for ext in (".png", ".jpg", ".tiff"):
            (tmp_path / f"img{ext}").write_bytes(b"\x00")
        result = scan_source_path(tmp_path)
        assert len(result.images) == 3
        # Also in data_files (it's a dataset, just specialized).
        assert len(result.data_files) >= 3

    def test_nifti_uncompressed_classified_as_image(self, tmp_path: Path) -> None:
        (tmp_path / "scan.nii").write_bytes(b"\x00")
        result = scan_source_path(tmp_path)
        assert any(p.name == "scan.nii" for p in result.images)

    def test_nifti_gz_compound_extension_dual_classified(
        self, tmp_path: Path
    ) -> None:
        """``.nii.gz`` is a neuroimaging-specific compound suffix; the
        scanner branch at source_scanner.py:164 must classify it as
        BOTH data_files and images."""
        (tmp_path / "scan.nii.gz").write_bytes(b"\x00")
        result = scan_source_path(tmp_path)
        assert any(p.name == "scan.nii.gz" for p in result.data_files)
        assert any(p.name == "scan.nii.gz" for p in result.images)

    def test_audio_extensions(self, tmp_path: Path) -> None:
        for ext in (".wav", ".mp3", ".flac"):
            (tmp_path / f"a{ext}").write_bytes(b"\x00")
        result = scan_source_path(tmp_path)
        assert len(result.audio) == 3

    def test_video_extensions(self, tmp_path: Path) -> None:
        (tmp_path / "v.mp4").write_bytes(b"\x00")
        (tmp_path / "v.avi").write_bytes(b"\x00")
        result = scan_source_path(tmp_path)
        assert len(result.video) == 2

    def test_timeseries_hdf5_edf_classified(self, tmp_path: Path) -> None:
        for ext in (".hdf5", ".edf", ".mat", ".nwb"):
            (tmp_path / f"ts{ext}").write_bytes(b"\x00")
        result = scan_source_path(tmp_path)
        assert len(result.timeseries) >= 4

    def test_spatial_extensions(self, tmp_path: Path) -> None:
        for ext in (".ply", ".pcd", ".c3d", ".obj"):
            (tmp_path / f"s{ext}").write_bytes(b"\x00")
        result = scan_source_path(tmp_path)
        assert len(result.spatial) >= 4

    def test_domain_data_extensions_classified_as_data(
        self, tmp_path: Path
    ) -> None:
        """SPSS/Stata/Feather/Arrow/RData are domain-data — must land
        in ``data_files`` even though they don't have a specialized
        sub-bucket. (Used by `enrich_workspace` to pattern the [data]
        block.)"""
        for ext in (".sav", ".dta", ".feather", ".arrow", ".rdata"):
            (tmp_path / f"d{ext}").write_bytes(b"\x00")
        result = scan_source_path(tmp_path)
        names = {p.name for p in result.data_files}
        assert names == {"d.sav", "d.dta", "d.feather", "d.arrow", "d.rdata"}

    def test_tsv_excel_json_jsonl_tabular_branches(self, tmp_path: Path) -> None:
        for fname, content in (
            ("d.tsv", b"x\ty\n1\t2\n"),
            ("d.xlsx", b"\x00"),
            ("d.xls", b"\x00"),
            ("d.json", b"{}"),
            ("d.jsonl", b"{}\n"),
        ):
            (tmp_path / fname).write_bytes(content)
        result = scan_source_path(tmp_path)
        names = {p.name for p in result.data_files}
        assert names >= {"d.tsv", "d.xlsx", "d.xls", "d.json", "d.jsonl"}

    def test_mixed_specialized_and_tabular(self, tmp_path: Path) -> None:
        """A real research project has tabular + images + papers + code
        all together — assert they're correctly partitioned across the
        seven category buckets."""
        (tmp_path / "metadata.csv").write_text("x\n1\n")
        (tmp_path / "scan1.nii.gz").write_bytes(b"\x00")
        (tmp_path / "trial.wav").write_bytes(b"\x00")
        (tmp_path / "recording.edf").write_bytes(b"\x00")
        (tmp_path / "model.ply").write_bytes(b"\x00")
        (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "readme.md").write_text("# notes\n")
        (tmp_path / "analyse.py").write_text("x=1\n")
        result = scan_source_path(tmp_path)
        assert len(result.data_files) >= 5  # csv + nii.gz + wav + edf + ply
        assert len(result.images) >= 1  # nii.gz
        assert len(result.audio) >= 1
        assert len(result.timeseries) >= 1
        assert len(result.spatial) >= 1
        assert len(result.papers) >= 1
        assert len(result.docs) >= 1
        assert len(result.code) >= 1
