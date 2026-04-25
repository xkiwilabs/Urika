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

    def test_markdown_fenced_code_block(self):
        """Fenced code blocks in markdown render as <pre><code>."""
        md = "```python\ndef foo():\n    return 42\n```"
        html = render_file_content(md, "test.md")
        assert "<pre>" in html
        assert "<code" in html
        assert "def foo" in html

    def test_markdown_relative_image_rewritten_to_api_raw(self):
        """Relative image src in rendered markdown is rewritten to /api/raw."""
        md = "![caption](artifacts/plot.png)"
        html = render_file_content(md, "test.md", base_dir="experiments/exp-001")
        # Image should be rewritten; absolute links left alone
        assert "/api/raw?path=" in html
        assert "experiments/exp-001/artifacts/plot.png" in html.replace("%2F", "/")

    def test_invalid_json_falls_back_to_pre(self):
        """Malformed JSON renders as a plain <pre> block, not a crash."""
        html = render_file_content("{not valid json", "test.json")
        assert "<pre>" in html
        assert "not valid json" in html
        # Must not contain the language-json code block wrapper when invalid
        assert "language-json" not in html

    def test_escape_html_in_plain_file(self):
        """Angle brackets in plain files are escaped so they don't inject HTML."""
        html = render_file_content("<script>alert(1)</script>", "test.txt")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
