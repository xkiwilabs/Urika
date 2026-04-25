"""Markdown → HTML rendering helper."""

from urika.dashboard.render import render_markdown


def test_render_markdown_basic():
    html = render_markdown("# Title\n\nbody")
    assert "<h1>Title</h1>" in html
    assert "<p>body</p>" in html


def test_render_markdown_handles_empty():
    assert render_markdown("") == ""
    assert render_markdown(None) == ""


def test_render_markdown_escapes_html_in_source():
    """Literal <script> tags from agent-written reports must not execute."""
    html = render_markdown("Plain text with <script>alert(1)</script>.")
    assert "<script>" not in html or "&lt;script&gt;" in html


def test_render_markdown_supports_fenced_code():
    html = render_markdown("```python\nx = 1\n```")
    assert "<code" in html
