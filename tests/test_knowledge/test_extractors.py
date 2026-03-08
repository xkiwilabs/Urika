"""Tests for knowledge extractors."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from urika.knowledge.extractors import extract_pdf, extract_text, extract_url


class TestExtractText:
    def test_extracts_txt_content(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text("These are my research notes.")
        result = extract_text(f)
        assert result == "These are my research notes."

    def test_extracts_md_content(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.md"
        f.write_text("# Heading\n\nSome content.")
        result = extract_text(f)
        assert "Heading" in result

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("")
        with pytest.raises(ValueError, match="empty"):
            extract_text(f)

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            extract_text(tmp_path / "nope.txt")


class TestExtractPdf:
    def test_extracts_pdf_content(self, tmp_path: Path) -> None:
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page 1 content"
        mock_reader.pages = [mock_page]

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = extract_pdf(pdf_path)
        assert result == "Page 1 content"

    def test_multi_page_pdf(self, tmp_path: Path) -> None:
        mock_reader = MagicMock()
        page1 = MagicMock()
        page1.extract_text.return_value = "Page 1"
        page2 = MagicMock()
        page2.extract_text.return_value = "Page 2"
        mock_reader.pages = [page1, page2]

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = extract_pdf(pdf_path)
        assert "Page 1" in result
        assert "Page 2" in result

    def test_empty_pdf_raises(self, tmp_path: Path) -> None:
        mock_reader = MagicMock()
        mock_reader.pages = []

        pdf_path = tmp_path / "empty.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        with patch("pypdf.PdfReader", return_value=mock_reader):
            with pytest.raises(ValueError, match="empty"):
                extract_pdf(pdf_path)

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            extract_pdf(tmp_path / "nope.pdf")


class TestExtractUrl:
    _public_addrinfo = [(2, 1, 6, "", ("93.184.216.34", 0))]

    def test_extracts_html_content(self) -> None:
        html = b"<html><body><h1>Title</h1><p>Some text content.</p></body></html>"
        mock_response = MagicMock()
        mock_response.read.return_value = html
        mock_response.headers.get_content_charset.return_value = "utf-8"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "urika.knowledge.extractors.socket.getaddrinfo",
                return_value=self._public_addrinfo,
            ),
            patch("urika.knowledge.extractors.urlopen", return_value=mock_response),
        ):
            result = extract_url("https://example.com")
        assert "Title" in result
        assert "Some text content" in result
        assert "<h1>" not in result

    def test_empty_response_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.read.return_value = b""
        mock_response.headers.get_content_charset.return_value = "utf-8"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "urika.knowledge.extractors.socket.getaddrinfo",
                return_value=self._public_addrinfo,
            ),
            patch("urika.knowledge.extractors.urlopen", return_value=mock_response),
        ):
            with pytest.raises(ValueError, match="Empty"):
                extract_url("https://example.com")

    def test_unreachable_raises(self) -> None:
        with (
            patch(
                "urika.knowledge.extractors.socket.getaddrinfo",
                return_value=self._public_addrinfo,
            ),
            patch(
                "urika.knowledge.extractors.urlopen",
                side_effect=OSError("Connection refused"),
            ),
        ):
            with pytest.raises(ValueError, match="fetch"):
                extract_url("https://unreachable.example.com")

    def test_rejects_file_scheme(self) -> None:
        with pytest.raises(ValueError, match="http"):
            extract_url("file:///etc/passwd")

    def test_rejects_ftp_scheme(self) -> None:
        with pytest.raises(ValueError, match="http"):
            extract_url("ftp://example.com/file")

    def test_rejects_localhost(self) -> None:
        with patch(
            "urika.knowledge.extractors.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 0))],
        ):
            with pytest.raises(ValueError, match="private"):
                extract_url("https://evil.com/admin")

    def test_rejects_private_ip(self) -> None:
        with patch(
            "urika.knowledge.extractors.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("192.168.1.1", 0))],
        ):
            with pytest.raises(ValueError, match="private"):
                extract_url("https://evil.com/admin")

    def test_rejects_link_local(self) -> None:
        with patch(
            "urika.knowledge.extractors.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("169.254.169.254", 0))],
        ):
            with pytest.raises(ValueError, match="private"):
                extract_url("https://evil.com/metadata")
