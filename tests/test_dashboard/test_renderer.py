"""Tests for dashboard file content renderer."""
from urika.dashboard.renderer import render_file_content


class TestRenderFileContent:
    def test_markdown_to_html(self):
        html = render_file_content("# Hello\n\nWorld **bold**", "test.md")
        assert "<h1>" in html or "<h1" in html
        assert "Hello" in html
        assert "<strong>" in html or "<b>" in html

    def test_markdown_tables(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = render_file_content(md, "test.md")
        assert "<table" in html

    def test_json_formatted(self):
        html = render_file_content('{"key": "value", "num": 42}', "test.json")
        assert "key" in html
        assert "<pre" in html

    def test_python_code_block(self):
        html = render_file_content("def foo():\n    return 42", "test.py")
        assert "<pre" in html
        assert "def foo" in html

    def test_unknown_as_pre(self):
        html = render_file_content("plain text content", "test.txt")
        assert "<pre" in html
        assert "plain text" in html

    def test_empty_content(self):
        html = render_file_content("", "test.md")
        assert isinstance(html, str)
