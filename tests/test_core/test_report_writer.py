"""Tests for the versioned report writer."""

from __future__ import annotations

from pathlib import Path

from urika.core.report_writer import write_versioned


class TestWriteVersioned:
    def test_creates_new_file(self, tmp_path: Path) -> None:
        p = tmp_path / "report.md"
        write_versioned(p, "content")
        assert p.read_text() == "content"

    def test_versions_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "report.md"
        p.write_text("old")
        write_versioned(p, "new")
        assert p.read_text() == "new"
        versioned = list(tmp_path.glob("report-*.md"))
        assert len(versioned) == 1
        assert versioned[0].read_text() == "old"

    def test_multiple_versions_same_day(self, tmp_path: Path) -> None:
        p = tmp_path / "report.md"
        p.write_text("v1")
        write_versioned(p, "v2")
        write_versioned(p, "v3")
        assert p.read_text() == "v3"
        versioned = list(tmp_path.glob("report-*.md"))
        assert len(versioned) == 2

    def test_returns_path(self, tmp_path: Path) -> None:
        p = tmp_path / "report.md"
        result = write_versioned(p, "content")
        assert result == p

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        p = tmp_path / "sub" / "dir" / "report.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        write_versioned(p, "content")
        assert p.read_text() == "content"
