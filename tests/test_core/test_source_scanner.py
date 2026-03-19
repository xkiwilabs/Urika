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
